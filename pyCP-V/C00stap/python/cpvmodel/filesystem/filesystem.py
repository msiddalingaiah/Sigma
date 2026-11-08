"""The file system's front: open, close, read and write."""

import enum
from dataclasses import dataclass, field

from ..glossary import cpv, modelOnly
from .directory import Directory
from .disc import Disc
from .files import ConsecutiveFile, FileHeader

NO_SUCH_FILE = 0x03             # as FIX1 handles it; OPEN's own codes weren't read
END_OF_FILE = 0x06
WRONG_MODE = 0x15               # an operation error


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


@modelOnly("CP-V reports file errors with a code in the DCB and goes to the program's error "
           "address, or aborts it; the model throws this into the program")
class FileError(Exception):
    def __init__(self, code, message):
        super().__init__(f"X'{code:02X}': {message}")
        self.code = code


@modelOnly("Disc timing; CP-V's comes from the RADs and disc packs")
@dataclass(frozen=True)
class FileSystemSettings:
    """``discTime`` is the time, in ticks, of one disc access (a granule read or written, or
    a directory looked up). It is 0 by default, so file operations take no time unless a
    scenario asks for it."""
    discTime: int = 0
    discGranules: int = 512

    cpvNames = {
        "discTime": modelOnly("Ticks per disc access"),
        "discGranules": modelOnly("Granules in the file area"),
    }


@cpv("CFU", "NOU", source="UTS.txt:446-452",
     note="CURRENT FILE USAGE: one per open file, shared by every DCB that has it open")
@dataclass(eq=False)
class OpenFile:
    """A file that is open, shared by everyone who has it open."""
    header: FileHeader
    file: ConsecutiveFile
    users: int = 0
    isNew: bool = False

    cpvNames = {
        "header": cpv("FITSIZE", source="WRTF.txt:44-46"),
        "file": cpv("FDA", source="UTS.txt:448-460"),
        "users": cpv("NOU", source="UTS.txt:450", note="Number of users"),
        "isNew": cpv("CLSFIL4", source="CLS.txt:1994-1998",
                     note="Opened OUT: not in the directory until it is closed"),
    }


@cpv("DCB", source="UTS.txt:448-530",
     note="The data control block: the program's own record of an open file")
@dataclass(eq=False)
class FileHandle:
    """A program's open file: how it was opened, and where it is in the file."""
    user: object
    openFile: OpenFile
    mode: FileMode
    position: tuple = (0, 0)
    discAccesses: int = 0
    isOpen: bool = True

    cpvNames = {
        "user": modelOnly("The user whose program holds the handle"),
        "openFile": cpv("CFU", source="UTS.txt:446-452", note="DCB word 1 has the CFU"),
        "mode": cpv("FUNCTION", source="UTS.txt:448-460"),
        "position": cpv("SEQPOS", source="RDF.txt:3136-3138",
                        note="CP-V keeps the record number and the disc address"),
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
      A file opened OUT is new, and goes into its directory only when it is closed,
      replacing any file of the same name.
    - **Read and write** go through a handle. Every granule touched, and every directory
      looked up, is a disc access, which the system charges as I/O time.

    In CP-V this is OPNF, CLS, RDF and WRTF, around 25,000 lines. The model has consecutive
    files only, opened IN or OUT; keyed and random files, deleting, and OPEN's access
    checks come in later iterations.
    """

    def __init__(self, system, settings=None):
        self.system = system
        self.settings = settings or FileSystemSettings()
        self.disc = Disc(self.settings.discGranules)
        self.accounts = Directory()
        self.openFiles = {}
        self.handles = {}

    cpvNames = {
        "system": modelOnly("The system the file system belongs to"),
        "settings": modelOnly("Disc size and timing"),
        "disc": modelOnly("The file area's granules"),
        "accounts": cpv("ACNCFU", source="UTS.txt:464", note="The account directory"),
        "openFiles": cpv("CFU", source="OPNF.txt:616-620",
                         note="OPEN scans the CFUs for the file before the directories"),
        "handles": modelOnly("Each user's open handles, so they can be closed at the end"),
    }

    @cpv("OPNFIL", "TFCHKOPN", source="OPNF.txt:115, OPNF.txt:503-620",
         note="CP-V also takes the open/close lock (OPNCLSUS); the system does that around "
              "this call")
    def openFile(self, user, name, mode, account=None):
        """Open the file ``name`` in ``account`` (the user's own by default)."""
        account = account or user.account
        handle = None
        if mode is FileMode.IN:
            openFile = self.openFiles.get((account, name))
            if openFile is None:
                header, file = self.lookUp(account, name)
                openFile = OpenFile(header, file)
                self.openFiles[(account, name)] = openFile
                accesses = 3                        # account entry, file entry, header
            else:
                accesses = 0
        else:
            header = FileHeader(name, account)
            openFile = OpenFile(header, ConsecutiveFile(header, self.disc), isNew=True)
            accesses = 1
        openFile.users += 1
        handle = FileHandle(user, openFile, mode, discAccesses=accesses)
        self.handles.setdefault(user, []).append(handle)
        return handle

    @cpv("FNDKEY", "SETUPUB", source="FIX1.txt:2194, RDF.txt:1575",
         note="The account directory, then the file directory")
    def lookUp(self, account, name):
        files = self.accounts.find(account)
        file = files.find(name) if files is not None else None
        if file is None:
            raise FileError(NO_SUCH_FILE, f"no file {name} in {account}")
        return file.header, file

    @cpv("SEQ0", source="RDF.txt:3136-3268",
         note="At the end of the file CP-V returns TYC 7, code X'06'")
    def readRecord(self, handle):
        """The next record, or None at the end of the file."""
        self.checkMode(handle, FileMode.IN)
        text, handle.position, touched = handle.openFile.file.read(handle.position)
        handle.discAccesses += touched
        return text

    @cpv("SEQ0", source="WRTF.txt:273-505")
    def writeRecord(self, handle, text):
        self.checkMode(handle, FileMode.OUT)
        handle.discAccesses += handle.openFile.file.append(text)

    @cpv("CLSFIL", "CLSFIL4", source="CLS.txt:1443-1530, CLS.txt:1994-1998",
         note="A new file goes into its directory at close")
    def closeFile(self, handle):
        handle.isOpen = False
        self.handles[handle.user].remove(handle)
        openFile = handle.openFile
        openFile.users -= 1
        if openFile.isNew:
            self.enter(openFile.file)
            handle.discAccesses += 2                # the header and the directory entry
        elif openFile.users == 0:
            del self.openFiles[(openFile.header.account, openFile.header.name)]

    @modelOnly("CP-V closes a program's open DCBs when its job step ends; where wasn't traced")
    def closeAll(self, user):
        for handle in list(self.handles.get(user, [])):
            self.closeFile(handle)
        self.handles.pop(user, None)

    @cpv("INST", source="WRTF.txt:608",
         note="CP-V releases the file it replaces as well; when another user still has that "
              "file open isn't modelled")
    def enter(self, file):
        header = file.header
        files = self.accounts.find(header.account)
        if files is None:
            files = Directory()
            self.accounts.insert(header.account, files)
        old = files.find(header.name)
        if old is not None:
            old.release()
        files.insert(header.name, file)

    @cpv("K15", source="WRTF.txt:15, WRTF.txt:244", note="OPERATION ERROR: the DCB isn't open for it")
    def checkMode(self, handle, mode):
        if not handle.isOpen or handle.mode is not mode:
            raise FileError(WRONG_MODE, f"{handle.openFile.header.name} isn't open {mode.name}")

    @modelOnly("The names of an account's files, in order")
    def fileNames(self, account):
        files = self.accounts.find(account)
        return files.names() if files is not None else []
