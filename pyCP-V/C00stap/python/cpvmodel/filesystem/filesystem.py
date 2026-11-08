"""The file system's front: the file CALs, served on DCBs."""

from dataclasses import dataclass

from ..dcb import FileMode
from ..glossary import cpv, modelOnly
from .access import AccessCheck, Protection
from .directory import ACCOUNT_ENTRY, FILE_ENTRY, Directory
from .disc import GRANULE_BYTES, Disc, DiscFull
from .errors import (ACCESS_REFUSED, KEY_NOT_FOUND, NO_KEY, NO_SUCH_FILE, WRONG_MODE,
                     FileError)
from .files import ConsecutiveFile, FileHeader, Organization
from .keyedfile import KeyedFile
from .randomfile import RandomFile

DISC = "disc"                   # the device the file area is on


@modelOnly("Disc size and timing; CP-V's come from the RADs and disc packs")
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


@cpv("OPNFIL", "CLSFIL", "SEQ0", source="OPNF.txt:115, CLS.txt:1443, RDF.txt:3136",
     note="OPEN, CLOSE, READ and WRITE for files")
class FileSystem:
    """Files in accounts, and the file CALs on a program's DCBs.

    - **Directories:** the account directory maps an account to its file directory, which
      maps a file name to the file.
    - **Open** (``M:OPEN``) finds a file already open and shares it, or looks it up in the
      directories, and checks the file's protection (``AccessCheck``). A file opened OUT is
      new, and goes into its directory only when it is closed, replacing any file of the
      same name. Opening and closing are done as the **open/close user**, one user at a time.
    - **Read and write** (``M:READ``, ``M:WRITE``) go through the DCB, by key in a keyed file,
      by granule number in a random file, or in order. Every granule touched, and every index
      or directory block searched, is a disc access: a transfer on the disc's queue, which
      the user waits for.
    - **Close** (``M:CLOSE``) with release deletes the file.

    The services run in the user's thread, and wait where CP-V waits: for the open/close
    lock, the disc, and granules (``GETGRAN`` waits for ALLOCAT in the middle of a write).

    In CP-V this is OPNF, CLS, RDF and WRTF, around 25,000 lines. The model has consecutive,
    keyed and random files, opened IN or OUT; not UPDATE, INOUT or OUTIN, synonyms, or
    expiration dates.
    """

    def __init__(self, system, settings=None):
        self.system = system
        self.settings = settings or FileSystemSettings()
        system.io.addDevice(DISC, self.settings.discTime)
        self.disc = Disc(self.settings.discGranules, system)
        self.disc.allocator.adjust()                # as ALLOCAT does at boot
        self.disc.allocator.commit()
        self.accounts = Directory(self.disc, ACCOUNT_ENTRY)
        self.openFiles = {}
        self.openDcbs = {}
        self.access = AccessCheck()

    cpvNames = {
        "system": modelOnly("The system the file system belongs to"),
        "settings": modelOnly("Disc size and timing"),
        "disc": modelOnly("The file area's granules"),
        "accounts": cpv("ACNCFU", source="UTS.txt:464", note="The account directory"),
        "openFiles": cpv("CFU", source="OPNF.txt:616-620",
                         note="The files open now. OPEN scans the CFUs for the file before "
                              "the directories"),
        "openDcbs": modelOnly("Each user's open DCBs, so they can be closed at the end"),
        "access": cpv("SECCHK", source="OBSE.txt:310"),
    }

    # --- The CALs ---------------------------------------------------------------------------

    @cpv("OPNFIL", "OPNCLSUS", "E:OCR", source="OPNF.txt:115, OPNF.txt:1479-1487",
         note="OPEN runs as the open/close user, waiting for the lock if someone else has it")
    def open(self, user, dcb):
        """``M:OPEN``: connect ``dcb`` to its file."""
        scheduler = self.system.scheduler
        scheduler.acquireOpenClose(user)
        try:
            self.connect(user, dcb)
            self.system.log(user, f"opens {dcb.fileName} {dcb.mode.name}")
            self.waitForDisc(user, dcb.takeDiscAccesses())
        finally:
            scheduler.releaseOpenClose(user)

    @cpv("SEQ0", "SETUPUB", source="RDF.txt:3136-3268, RDF.txt:1575",
         note="At the end of the file CP-V returns TYC 7, code X'06'")
    def read(self, user, dcb, key=None, size=None):
        """``M:READ``: the record for ``key`` in a keyed file (a granule number in a random
        file, reading ``size`` bytes), or else the next record; None at the end of the
        file."""
        text = self.readRecord(dcb, key, size)
        self.waitForDisc(user, dcb.takeDiscAccesses())
        return text

    @cpv("SEQ0", "ENTKEYUB", source="WRTF.txt:273-505, WRTF.txt:1532")
    def write(self, user, dcb, text, key=None):
        """``M:WRITE``: at the end of a consecutive file, under ``key`` in a keyed file
        (replacing any record with that key), or at a granule in a random file."""
        try:
            self.writeRecord(dcb, text, key)
        finally:
            self.waitForDisc(user, dcb.takeDiscAccesses())

    @cpv("CLSFIL", "CLSFIL4", source="CLS.txt:1443-1530, CLS.txt:1994-1998",
         note="As the open/close user. A new file goes into its directory at close")
    def close(self, user, dcb, release=False):
        """``M:CLOSE``; with ``release`` (REL), delete the file."""
        scheduler = self.system.scheduler
        scheduler.acquireOpenClose(user)
        try:
            name, mode = dcb.file.header.name, dcb.mode
            self.disconnect(user, dcb, release)
            self.system.log(user, f"closes {name} {mode.name}")
            self.waitForDisc(user, dcb.takeDiscAccesses())
        finally:
            scheduler.releaseOpenClose(user)

    @modelOnly("CP-V closes a program's open DCBs when its job step ends; where wasn't traced")
    def closeAll(self, user):
        """Close whatever ``user`` left open. The monitor does it, so nothing waits. A new
        file that can't be entered (the disc is full) is dropped."""
        for dcb in list(self.openDcbs.get(user, [])):
            try:
                self.disconnect(user, dcb)
            except FileError:
                dcb.file.release()
                self.system.log(user, f"{dcb.file.header.name} dropped: the disc is full")
        self.openDcbs.pop(user, None)

    @cpv("T:IOREG", "E:IIP", source="SCHED.txt:780-787",
         note="The file code's disc transfers, queued on the disc; the user waits")
    def waitForDisc(self, user, accesses):
        self.system.io.transfer(user, DISC, accesses)

    # --- Open -----------------------------------------------------------------------------

    @cpv("OPNFIL", "TFCHKOPN", source="OPNF.txt:115, OPNF.txt:503-620")
    def connect(self, user, dcb):
        """Find or create the file for ``dcb`` and connect them, checking access."""
        name = dcb.fileName or dcb.name
        dcb.fileName = name
        account = dcb.account or user.account
        if dcb.mode is FileMode.IN:
            file = self.openFiles.get((account, name))
            if file is None:
                file, accesses = self.lookUp(account, name)
            else:
                accesses = 0
            own = self.access.check(user, file.header, True, dcb.password)
            self.openFiles[(account, name)] = file
        else:
            organization = dcb.organization or Organization.CONSECUTIVE
            old, accesses = self.search(account, name)
            if old is None:
                self.access.checkCreate(user, account, name)
                own = True
            else:
                own = self.access.check(user, old.header, False, dcb.password)
                self.checkReplace(old, organization)
            header = FileHeader(name, account, protection=dcb.protection or Protection())
            file = self.newFile(header, organization, dcb.size)
            accesses += 1
        file.openCount += 1
        dcb.file, dcb.isOpen, dcb.ownFile = file, True, own
        dcb.position = 0 if isinstance(file, RandomFile) else (0, 0)
        dcb.discAccesses += accesses
        self.openDcbs.setdefault(user, []).append(dcb)

    @cpv("ORG", source="OPNF.txt:1015-1038",
         note="The organization picks the code that reads and writes the file")
    def newFile(self, header, organization, size=None):
        if organization is Organization.KEYED:
            settings = self.settings
            return KeyedFile(header, self.disc, settings.keyLength, settings.spareBytes,
                             settings.rebuildAfterSlides)
        if organization is Organization.RANDOM:
            return self.newRandomFile(header, size)
        return ConsecutiveFile(header, self.disc)

    @cpv("GRANDPUB", "GNBG", source="GRAND.txt:102-117, GRAN.txt:253",
         note="The run is asked of ALLOCAT; the user waits for the answer (E:QFAC)")
    def newRandomFile(self, header, size):
        if not size or size < 1:
            raise FileError(WRONG_MODE, f"{header.name}: a random file needs a size")
        addresses = self.disc.allocator.getRun(size)
        if not addresses:
            raise DiscFull()
        file = RandomFile(header, self.disc, size)
        file.allocate(self.disc.claimRun(addresses))
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

    # --- Read and write ---------------------------------------------------------------------

    @cpv("SEQ0", "SETUPUB", "RWRAND", source="RDF.txt:3136-3268, RDF.txt:1575, WRTF.txt:1928")
    def readRecord(self, dcb, key=None, size=None):
        self.checkMode(dcb, FileMode.IN)
        file = dcb.file
        if isinstance(file, RandomFile):
            start = dcb.position if key is None else key
            text, moved = file.read(start, size if size is not None else GRANULE_BYTES)
            dcb.position = start + max(moved, 1)
            dcb.discAccesses += moved
            return text
        if isinstance(file, KeyedFile):
            if key is not None:
                text, accesses = file.read(key)
                dcb.discAccesses += accesses
                if text is None:
                    raise FileError(KEY_NOT_FOUND, f"no key {key} in {file.header.name}")
                return text
            _, text, dcb.position, accesses = file.readNext(dcb.position)
            dcb.discAccesses += accesses
            return text
        text, dcb.position, touched = file.read(dcb.position)
        dcb.discAccesses += touched
        return text

    @cpv("SEQ0", "ENTKEYUB", "RWRAND", source="WRTF.txt:273-505, WRTF.txt:1532, WRTF.txt:1928")
    def writeRecord(self, dcb, text, key=None):
        self.checkMode(dcb, FileMode.OUT)
        file = dcb.file
        if isinstance(file, RandomFile):
            start = dcb.position if key is None else key
            dcb.position = start + max(1, min(file.size - start, -(-len(text) // GRANULE_BYTES)))
            dcb.discAccesses += file.write(start, text)
        elif isinstance(file, KeyedFile):
            if key is None:
                raise FileError(NO_KEY, f"a keyed write to {file.header.name} needs a key")
            dcb.discAccesses += file.write(key, text)
        else:
            dcb.discAccesses += file.append(text)

    @cpv("K15", source="WRTF.txt:15, WRTF.txt:244", note="OPERATION ERROR: the DCB isn't open for it")
    def checkMode(self, dcb, mode):
        if not dcb.isOpen or dcb.mode is not mode:
            name = dcb.file.header.name if dcb.file else dcb.name
            raise FileError(WRONG_MODE, f"{name} isn't open {mode.name}")

    # --- Close ----------------------------------------------------------------------------

    @cpv("CLSFIL", "CLSFIL4", source="CLS.txt:1443-1530, CLS.txt:1994-1998")
    def disconnect(self, user, dcb, release=False):
        """Close ``dcb``'s file: enter a new one in its directory, or with ``release`` delete
        it."""
        dcb.isOpen = False
        self.openDcbs[user].remove(dcb)
        file = dcb.file
        file.openCount -= 1
        if release and self.deleteOnClose(user, dcb):
            return
        if not file.inDirectory:
            dcb.discAccesses += file.close()
            dcb.discAccesses += self.enter(file) + 1        # and the header
        elif file.openCount == 0:
            del self.openFiles[(file.header.account, file.header.name)]

    @cpv("CLSFIL", "CLSFIL2", "DELF", source="CLS.txt:1443-1672",
         note="Returns True if the close released the file")
    def deleteOnClose(self, user, dcb):
        """A close with release (REL). Nothing is deleted while someone else has the file
        open, or when the user may not delete it; then it is an ordinary close. A new file
        (OUT) isn't in the directory yet, so only its granules go."""
        file = dcb.file
        name = file.header.name
        if file.openCount > 0:
            self.system.log(user, f"release of {name} ignored: someone else has it open")
            return False
        if not file.inDirectory:
            file.release()
            self.system.log(user, f"discards {name}")
            return True
        if not self.access.mayDelete(user, dcb):
            self.system.log(user, f"release of {name} dropped: not the user's file")
            return False
        files = self.accounts.find(file.header.account)
        _, accesses = files.remove(name)
        self.openFiles.pop((file.header.account, name), None)
        file.release()
        dcb.discAccesses += accesses + 1
        self.system.log(user, f"deletes {name}")
        return True

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

    # --- For other components ---------------------------------------------------------------

    @cpv("STUQFAC", source="SCHED.txt:1707-1745",
         note="The scheduler's release routine for ALLOCATOR (E:UQFAC) calls this")
    def commitAllocation(self):
        self.disc.allocator.commit()

    @modelOnly("The names of an account's files, in order")
    def fileNames(self, account):
        files = self.accounts.find(account)
        return files.names() if files is not None else []
