"""The file system's front: open, close, read and write."""

import enum
from dataclasses import dataclass

from ..glossary import cpv, modelOnly
from .directory import ACCOUNT_ENTRY, FILE_ENTRY, Directory
from .disc import GRANULE_BYTES, Disc, DiscFull
from .files import ConsecutiveFile, File, FileHeader, Organization
from .keyedfile import KeyedFile
from .randomfile import RandomFile

from .access import AccessCheck, Protection
from .allocation import GranuleShortage
from .errors import (ACCESS_REFUSED, END_OF_FILE, KEY_NOT_FOUND, NO_KEY, NO_SUCH_FILE,
                     WRONG_MODE, FileError)


class FileMode(enum.Enum):
    """What a program opens a file for."""
    IN = 1
    OUT = 2


cpv("FUNCTION", "BAFUNM", source="UTS.txt:448-460",
    note="CP-V also has INOUT, OUTIN and UPDATE")(FileMode)

FileMode.cpvNames = {
    "IN": cpv("CLSFIL", source="CLS.txt:1443-1530", note="Read an existing file"),
    "OUT": cpv("CLSFIL4", source="CLS.txt:1994-1998",
               note="Write a new file; it goes into the directory at close"),
}


@modelOnly("Disc timing; CP-V's comes from the RADs and disc packs")
@dataclass(frozen=True)
class FileSystemSettings:
    """``discTime`` is the time, in ticks, of one disc access (a granule read or written, or
    an index block searched). It is 0 by default, so file operations take no time unless a
    scenario asks for it. The keyed-file values are the DCB defaults ``DFRDL0``: "254
    SLIDES, 2 CONSEC, 102 BYTES SPARE"."""
    discTime: int = 0
    discGranules: int = 512
    keyLength: int = 11
    spareBytes: int = 102
    rebuildAfterSlides: int = 254

    cpvNames = {
        "discTime": modelOnly("Ticks per disc access"),
        "discGranules": modelOnly("Granules in the file area"),
        "keyLength": cpv("KEYM", source="UTS.txt:588"),
        "spareBytes": cpv("WRDL0", "DFRDL0", source="UTS.txt:609, OPNF.txt:1841"),
        "rebuildAfterSlides": cpv("LSLIDES", "DFRDL0", source="UTS.txt:660, OPNF.txt:1841"),
    }


@cpv("DCB", source="UTS.txt:448-530",
     note="The data control block: the program's own record of an open file")
@dataclass(eq=False)
class FileHandle:
    """A program's open file: how it was opened, and where it is in the file."""
    user: object
    file: File
    mode: FileMode
    position: object = (0, 0)
    discAccesses: int = 0
    isOpen: bool = True
    ownFile: bool = True

    cpvNames = {
        "user": modelOnly("The user whose program holds the handle"),
        "file": cpv("CFU", source="UTS.txt:446-452",
                    note="DCB word 1 points at the file's CFU"),
        "mode": cpv("FUNCTION", source="UTS.txt:448-460"),
        "position": cpv("SEQPOS", source="RDF.txt:3136-3138",
                        note="Where the next sequential read starts: (granule, segment), or "
                             "(index block, entry) in a keyed file"),
        "discAccesses": modelOnly("Disc accesses not yet charged to the user"),
        "isOpen": modelOnly("False once closed"),
        "ownFile": cpv("USR", "CHKFLACN", source="OBSE.txt:190, OBSE.txt:293-304",
                       note="The DCB's USR bit X'4000' clear: the user's own file, or as good "
                            "as (write access, or :SYS with an empty password)"),
    }

    @modelOnly("The disc accesses since last asked, for the system to charge as I/O time")
    def takeDiscAccesses(self):
        count, self.discAccesses = self.discAccesses, 0
        return count


@cpv("OPNFIL", "CLSFIL", "SEQ0", source="OPNF.txt:115, CLS.txt:1443, RDF.txt:3136",
     note="OPEN, CLOSE, READ and WRITE for files")
class FileSystem:
    """Files in accounts, and the programs that open them.

    - **Directories:** the account directory maps an account to its file directory, which
      maps a file name to the file.
    - **Open** finds a file already open and shares it, or looks it up in the directories.
      Every program has its own handle, with its own position.
      A file opened OUT is new, and goes into its directory only when it is closed,
      replacing any file of the same name.
    - **Read and write** go through a handle, by key in a keyed file, or in order. Every
      granule touched, and every index or directory block searched, is a disc access, which
      the system charges as I/O time.

    - **Access:** OPEN checks the file's protection (``AccessCheck``). Closing with release
      deletes the file.

    In CP-V this is OPNF, CLS, RDF and WRTF, around 25,000 lines. The model has consecutive,
    keyed and random files, opened IN or OUT; not UPDATE, INOUT or OUTIN, synonyms, or
    expiration dates.
    """

    def __init__(self, system, settings=None):
        self.system = system
        self.settings = settings or FileSystemSettings()
        self.disc = Disc(self.settings.discGranules, system)
        self.disc.allocator.adjust()                # as ALLOCAT does at boot
        self.disc.allocator.commit()
        self.accounts = Directory(self.disc, ACCOUNT_ENTRY)
        self.openFiles = {}
        self.handles = {}
        self.access = AccessCheck()

    cpvNames = {
        "system": modelOnly("The system the file system belongs to"),
        "settings": modelOnly("Disc size and timing"),
        "disc": modelOnly("The file area's granules"),
        "accounts": cpv("ACNCFU", source="UTS.txt:464", note="The account directory"),
        "openFiles": cpv("CFU", source="OPNF.txt:616-620",
                         note="The files open now. OPEN scans the CFUs for the file before "
                              "the directories"),
        "handles": modelOnly("Each user's open handles, so they can be closed at the end"),
        "access": cpv("SECCHK", source="OBSE.txt:310"),
    }

    @cpv("OPNFIL", "TFCHKOPN", source="OPNF.txt:115, OPNF.txt:503-620",
         note="CP-V also takes the open/close lock (OPNCLSUS); the system does that around "
              "this call")
    def openFile(self, user, name, mode, account=None,
                 organization=Organization.CONSECUTIVE, size=None, password=None,
                 protection=None):
        """Open the file ``name`` in ``account`` (the user's own by default). A file opened
        OUT is created with ``organization`` (a random file with ``size`` granules) and,
        when it is closed, ``protection``. ``password`` is the one to give for a file that
        has one."""
        account = account or user.account
        if mode is FileMode.IN:
            file = self.openFiles.get((account, name))
            if file is None:
                file, accesses = self.lookUp(account, name)
            else:
                accesses = 0
            own = self.access.check(user, file.header, True, password)
            self.openFiles[(account, name)] = file
        else:
            old, accesses = self.search(account, name)
            if old is None:
                self.access.checkCreate(user, account, name)
                own = True
            else:
                own = self.access.check(user, old.header, False, password)
                self.checkReplace(old, organization)
            self.disc.allocator.ensure(1)
            header = FileHeader(name, account, protection=protection or Protection())
            file = self.newFile(user, header, organization, size)
            accesses += 1
        file.openCount += 1
        handle = FileHandle(user, file, mode, discAccesses=accesses, ownFile=own)
        if isinstance(file, RandomFile):
            handle.position = 0
        self.handles.setdefault(user, []).append(handle)
        return handle

    @cpv("ORG", source="OPNF.txt:1015-1038",
         note="The organization picks the code that reads and writes the file")
    def newFile(self, user, header, organization, size=None):
        if organization is Organization.KEYED:
            settings = self.settings
            return KeyedFile(header, self.disc, settings.keyLength, settings.spareBytes,
                             settings.rebuildAfterSlides)
        if organization is Organization.RANDOM:
            return self.newRandomFile(user, header, size)
        return ConsecutiveFile(header, self.disc)

    @cpv("GRANDPUB", "GNBG", source="GRAND.txt:102-117, GRAN.txt:253",
         note="The run is asked of ALLOCAT; the user waits for the answer (E:QFAC) and opens "
              "again")
    def newRandomFile(self, user, header, size):
        if not size or size < 1:
            raise FileError(WRONG_MODE, f"{header.name}: a random file needs a size")
        allocator = self.disc.allocator
        answer = allocator.takeRunAnswer(user)
        if answer is None:
            allocator.requestRun(user, size)
            raise GranuleShortage(f"a run of {size} granules")
        if not answer or len(answer) != size:
            if answer:
                allocator.releaseRun(answer)
            raise DiscFull()
        file = RandomFile(header, self.disc, size)
        file.allocate(self.disc.claimRun(answer))
        return file

    @cpv("3D1", "OPENER03", source="OPNF.txt:545-563",
         note="Random may not replace keyed or consecutive, nor the other way round")
    def checkReplace(self, old, organization):
        if (old.header.organization is Organization.RANDOM) != (organization is Organization.RANDOM):
            raise FileError(ACCESS_REFUSED,
                            f"{old.header.name}: a random file and a non-random one can't "
                            "replace each other")

    @cpv("FNDKEY", source="FIX1.txt:2194",
         note="The account directory, then the file directory")
    def search(self, account, name):
        """The file or None, and the disc accesses the search took."""
        files, accesses = self.accounts.search(account)
        file = None
        if files is not None:
            file, more = files.search(name)
            accesses += more
        return file, accesses

    @cpv("FNDKEY", "SETUPUB", source="FIX1.txt:2194, RDF.txt:1575",
         note="The account directory, then the file directory, then the header")
    def lookUp(self, account, name):
        """The file, and the disc accesses the search took."""
        file, accesses = self.search(account, name)
        if file is None:
            raise FileError(NO_SUCH_FILE, f"no file {name} in {account}")
        return file, accesses + 1

    @cpv("SEQ0", "SETUPUB", source="RDF.txt:3136-3268, RDF.txt:1575",
         note="At the end of the file CP-V returns TYC 7, code X'06'")
    def readRecord(self, handle, key=None, size=None):
        """The record for ``key`` in a keyed file, or else the next record in order; None
        at the end of the file. In a random file, ``key`` is a granule number and ``size``
        the bytes wanted (a granule by default)."""
        self.checkMode(handle, FileMode.IN)
        file = handle.file
        if isinstance(file, RandomFile):
            start = handle.position if key is None else key
            text, moved = file.read(start, size if size is not None else GRANULE_BYTES)
            handle.position = start + max(moved, 1)
            handle.discAccesses += moved
            return text
        if isinstance(file, KeyedFile):
            if key is not None:
                text, accesses = file.read(key)
                handle.discAccesses += accesses
                if text is None:
                    raise FileError(KEY_NOT_FOUND, f"no key {key} in {file.header.name}")
                return text
            _, text, handle.position, accesses = file.readNext(handle.position)
            handle.discAccesses += accesses
            return text
        text, handle.position, touched = file.read(handle.position)
        handle.discAccesses += touched
        return text

    @cpv("SEQ0", "ENTKEYUB", source="WRTF.txt:273-505, WRTF.txt:1532")
    def writeRecord(self, handle, text, key=None):
        """Write a record: at the end of a consecutive file, or under ``key`` in a keyed
        file (replacing any record with that key)."""
        self.checkMode(handle, FileMode.OUT)
        file = handle.file
        if isinstance(file, RandomFile):
            start = handle.position if key is None else key
            handle.position = start + max(1, min(file.size - start, -(-len(text) // GRANULE_BYTES)))
            moved = file.write(start, text)
            handle.discAccesses += moved
            return
        self.disc.allocator.ensure(len(text) // (GRANULE_BYTES - 400) + 3)
        if isinstance(file, KeyedFile):
            if key is None:
                raise FileError(NO_KEY, f"a keyed write to {file.header.name} needs a key")
            handle.discAccesses += file.write(key, text)
        else:
            handle.discAccesses += file.append(text)

    @cpv("CLSFIL", "CLSFIL4", source="CLS.txt:1443-1530, CLS.txt:1994-1998",
         note="A new file goes into its directory at close")
    def closeFile(self, handle, release=False, mayWait=True):
        """Close ``handle``; with ``release``, delete the file. ``mayWait`` is False when the
        monitor closes it at step end: then nothing waits for granules, which come from the
        map if the stack is short."""
        if not handle.file.inDirectory and mayWait and not release:
            self.disc.allocator.ensure(2)           # directory blocks it may need
        handle.isOpen = False
        self.handles[handle.user].remove(handle)
        file = handle.file
        file.openCount -= 1
        if release and self.deleteOnClose(handle):
            return
        if not file.inDirectory:
            handle.discAccesses += file.close()
            handle.discAccesses += self.enter(file) + 1     # and the header
        elif file.openCount == 0:
            del self.openFiles[(file.header.account, file.header.name)]

    @cpv("CLSFIL", "CLSFIL2", "DELF", source="CLS.txt:1443-1672",
         note="Returns True if the close released the file")
    def deleteOnClose(self, handle):
        """A close with release (REL). Nothing is deleted while someone else has the file
        open, or when the user may not delete it; then it is an ordinary close. A new file
        (OUT) isn't in the directory yet, so only its granules go."""
        file, user = handle.file, handle.user
        name = file.header.name
        if file.openCount > 0:
            self.system.log(user, f"release of {name} ignored: someone else has it open")
            return False
        if not file.inDirectory:
            file.release()
            self.system.log(user, f"discards {name}")
            return True
        if not self.access.mayDelete(user, handle):
            self.system.log(user, f"release of {name} dropped: not the user's file")
            return False
        files = self.accounts.find(file.header.account)
        _, accesses = files.remove(name)
        self.openFiles.pop((file.header.account, name), None)
        file.release()
        handle.discAccesses += accesses + 1
        self.system.log(user, f"deletes {name}")
        return True

    @modelOnly("CP-V closes a program's open DCBs when its job step ends; where wasn't traced")
    def closeAll(self, user):
        """Close whatever ``user`` left open. A new file that can't be entered (the disc is
        full) is dropped and its granules released."""
        for handle in list(self.handles.get(user, [])):
            try:
                self.closeFile(handle, mayWait=False)
            except FileError:
                handle.file.release()
                self.system.log(user, f"{handle.file.header.name} dropped: the disc is full")
        self.handles.pop(user, None)

    @cpv("INST", source="WRTF.txt:608",
         note="CP-V releases the file it replaces as well; when another user still has that "
              "file open isn't modelled")
    def enter(self, file):
        """Put ``file`` in its account's directory. Returns the disc accesses."""
        header = file.header
        files, accesses = self.accounts.search(header.account)
        if files is None:
            files = Directory(self.disc, FILE_ENTRY)
            accesses += self.accounts.insert(header.account, files)
        old, more = files.search(header.name)
        if old is not None:
            old.release()
        accesses += more + files.insert(header.name, file)
        file.inDirectory = True
        return accesses

    @cpv("K15", source="WRTF.txt:15, WRTF.txt:244", note="OPERATION ERROR: the DCB isn't open for it")
    def checkMode(self, handle, mode):
        if not handle.isOpen or handle.mode is not mode:
            raise FileError(WRONG_MODE, f"{handle.file.header.name} isn't open {mode.name}")

    @cpv("STUQFAC", source="SCHED.txt:1707-1745",
         note="The scheduler's release routine for ALLOCATOR (E:UQFAC) calls this")
    def commitAllocation(self):
        self.disc.allocator.commit()

    @modelOnly("The names of an account's files, in order")
    def fileNames(self, account):
        files = self.accounts.find(account)
        return files.names() if files is not None else []
