"""The file system's front: open, close, read and write."""

import enum
from dataclasses import dataclass

from ..glossary import cpv, modelOnly
from .directory import ACCOUNT_ENTRY, FILE_ENTRY, Directory
from .disc import GRANULE_BYTES, Disc
from .files import ConsecutiveFile, File, FileHeader, Organization
from .keyedfile import KeyedFile

from .errors import (END_OF_FILE, KEY_NOT_FOUND, NO_KEY, NO_SUCH_FILE, WRONG_MODE,
                     FileError)


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
    position: tuple = (0, 0)
    discAccesses: int = 0
    isOpen: bool = True

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

    In CP-V this is OPNF, CLS, RDF and WRTF, around 25,000 lines. The model has consecutive
    and keyed files, opened IN or OUT; random files, deleting, and OPEN's access checks
    come in later iterations.
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

    cpvNames = {
        "system": modelOnly("The system the file system belongs to"),
        "settings": modelOnly("Disc size and timing"),
        "disc": modelOnly("The file area's granules"),
        "accounts": cpv("ACNCFU", source="UTS.txt:464", note="The account directory"),
        "openFiles": cpv("CFU", source="OPNF.txt:616-620",
                         note="The files open now. OPEN scans the CFUs for the file before "
                              "the directories"),
        "handles": modelOnly("Each user's open handles, so they can be closed at the end"),
    }

    @cpv("OPNFIL", "TFCHKOPN", source="OPNF.txt:115, OPNF.txt:503-620",
         note="CP-V also takes the open/close lock (OPNCLSUS); the system does that around "
              "this call")
    def openFile(self, user, name, mode, account=None,
                 organization=Organization.CONSECUTIVE):
        """Open the file ``name`` in ``account`` (the user's own by default). A file opened
        OUT is created with ``organization``; one opened IN has its own."""
        account = account or user.account
        if mode is FileMode.IN:
            file = self.openFiles.get((account, name))
            if file is None:
                file, accesses = self.lookUp(account, name)
                self.openFiles[(account, name)] = file
            else:
                accesses = 0
        else:
            self.disc.allocator.ensure(1)
            file = self.newFile(FileHeader(name, account), organization)
            accesses = 1
        file.openCount += 1
        handle = FileHandle(user, file, mode, discAccesses=accesses)
        self.handles.setdefault(user, []).append(handle)
        return handle

    @cpv("ORG", source="OPNF.txt:1015-1038",
         note="The organization picks the code that reads and writes the file")
    def newFile(self, header, organization):
        if organization is Organization.KEYED:
            settings = self.settings
            return KeyedFile(header, self.disc, settings.keyLength, settings.spareBytes,
                             settings.rebuildAfterSlides)
        return ConsecutiveFile(header, self.disc)

    @cpv("FNDKEY", "SETUPUB", source="FIX1.txt:2194, RDF.txt:1575",
         note="The account directory, then the file directory, then the header")
    def lookUp(self, account, name):
        """The file, and the disc accesses the search took."""
        files, accesses = self.accounts.search(account)
        file = None
        if files is not None:
            file, more = files.search(name)
            accesses += more
        if file is None:
            raise FileError(NO_SUCH_FILE, f"no file {name} in {account}")
        return file, accesses + 1

    @cpv("SEQ0", "SETUPUB", source="RDF.txt:3136-3268, RDF.txt:1575",
         note="At the end of the file CP-V returns TYC 7, code X'06'")
    def readRecord(self, handle, key=None):
        """The record for ``key`` in a keyed file, or else the next record in order; None
        at the end of the file."""
        self.checkMode(handle, FileMode.IN)
        file = handle.file
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
        self.disc.allocator.ensure(len(text) // (GRANULE_BYTES - 400) + 3)
        if isinstance(file, KeyedFile):
            if key is None:
                raise FileError(NO_KEY, f"a keyed write to {file.header.name} needs a key")
            handle.discAccesses += file.write(key, text)
        else:
            handle.discAccesses += file.append(text)

    @cpv("CLSFIL", "CLSFIL4", source="CLS.txt:1443-1530, CLS.txt:1994-1998",
         note="A new file goes into its directory at close")
    def closeFile(self, handle, mayWait=True):
        """Close ``handle``. ``mayWait`` is False when the monitor closes it at step end:
        then nothing waits for granules, which come from the map if the stack is short."""
        if not handle.file.inDirectory and mayWait:
            self.disc.allocator.ensure(2)           # directory blocks it may need
        handle.isOpen = False
        self.handles[handle.user].remove(handle)
        file = handle.file
        file.openCount -= 1
        if not file.inDirectory:
            handle.discAccesses += file.close()
            handle.discAccesses += self.enter(file) + 1     # and the header
        elif file.openCount == 0:
            del self.openFiles[(file.header.account, file.header.name)]

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
