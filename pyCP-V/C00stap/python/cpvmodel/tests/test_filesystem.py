"""The file system: directories, consecutive files, open and close, and disc time."""

import pytest

from cpvmodel import FileError, FileMode, FileSystemSettings, Program, System
from cpvmodel.filesystem import GRANULE_BYTES, NO_SUCH_FILE, WRONG_MODE

from .scripts import Reader, Script, Writer, fileDcb, happened, openFile


def userOf(system, name="u", **settings):
    return system.startUser(name, Script(), priority=0xF8, **settings)


def written(files, user, name, records):
    dcb = openFile(files, user, name, FileMode.OUT)
    for text in records:
        files.write(user, dcb, text)
    files.close(user, dcb)


# --- Directly through the FileSystem -------------------------------------------------------

def testRecordsComeBackInOrder():
    system = System()
    files, user = system.files, userOf(system)
    written(files, user, "DATA", ["ONE", "TWO", "THREE"])
    dcb = openFile(files, user, "DATA")
    assert [files.read(user, dcb) for _ in range(4)] == ["ONE", "TWO", "THREE", None]


def testALongRecordIsSplitAcrossGranules():
    system = System()
    files, user = system.files, userOf(system)
    written(files, user, "BIG", ["X" * 5000])
    file, _ = files.lookUp("GUEST", "BIG")
    assert len(file.granules) == 3                 # 1728 + 2048 + the rest
    assert file.granules[0].capacity == GRANULE_BYTES - 320
    dcb = fileDcb("BIG")
    files.connect(user, dcb)
    assert dcb.takeDiscAccesses() == 3             # account entry, file entry, header
    assert files.readRecord(dcb) == "X" * 5000
    assert dcb.takeDiscAccesses() == 3             # three granules


def testANewFileIsntInTheDirectoryUntilClosed():
    system = System()
    files, user = system.files, userOf(system)
    out = openFile(files, user, "NEW", FileMode.OUT)
    files.write(user, out, "A")
    with pytest.raises(FileError) as error:
        openFile(files, user, "NEW")
    assert error.value.code == NO_SUCH_FILE
    files.close(user, out)
    assert files.fileNames("GUEST") == ["NEW"]


def testReplacingAFileReleasesTheOldGranules():
    system = System()
    files, user = system.files, userOf(system)
    written(files, user, "F", ["OLD"])
    written(files, user, "F", ["NEW"])
    assert files.disc.freeCount() == 512 - 1 - 2   # the file, and the two directories
    dcb = openFile(files, user, "F")
    assert files.read(user, dcb) == "NEW"


def testReadersShareTheOpenFileButNotThePosition():
    system = System()
    files, user = system.files, userOf(system)
    written(files, user, "S", ["A", "B"])
    first = openFile(files, user, "S")
    second = fileDcb("S")
    files.connect(user, second)
    assert first.file is second.file and first.file.openCount == 2
    assert second.takeDiscAccesses() == 0          # found among the open files
    assert files.read(user, first) == "A"
    assert files.read(user, second) == "A"
    files.close(user, first)
    files.close(user, second)
    assert files.openFiles == {}


def testReadingAFileOpenedOutIsAnError():
    system = System()
    files, user = system.files, userOf(system)
    out = openFile(files, user, "W", FileMode.OUT)
    with pytest.raises(FileError) as error:
        files.read(user, out)
    assert error.value.code == WRONG_MODE


def testAccountsKeepTheirOwnFiles():
    system = System()
    files = system.files
    user = userOf(system, "operator", privilege=0xC0)
    for account in ("ALPHA", "BETA"):
        out = openFile(files, user, "SAME", FileMode.OUT, account=account)
        files.write(user, out, account)
        files.close(user, out)
    dcb = openFile(files, user, "SAME", account="BETA")
    assert files.read(user, dcb) == "BETA"


# --- Through programs -----------------------------------------------------------------------

def testAProgramWritesAndAnotherReads():
    system = System()
    system.startUser("writer", Writer("DATA", ["ONE", "TWO"]), priority=0xF8)
    reader = Reader("DATA", delay=100)
    system.startUser("reader", reader, priority=0xF8)
    assert system.run() == "shutdown"
    assert reader.got == ["ONE", "TWO"]


def testAnUncaughtFileErrorEndsTheUser():
    system = System()
    system.startUser("lost", Reader("MISSING"), priority=0xF8)
    system.run()
    assert happened(system, "lost", "ended: file error X'03': no file MISSING in GUEST") == [0]


def testAProgramCanCatchAFileError():
    class Careful(Program):
        caught = None

        def run(self, m):
            try:
                m.open(fileDcb("MISSING"))
            except FileError as error:
                self.caught = error.code
            self.compute(1)

    system = System()
    careful = Careful()
    system.startUser("careful", careful, priority=0xF8)
    assert system.run() == "shutdown"
    assert careful.caught == NO_SUCH_FILE


def testFileOperationsTakeDiscTime():
    """Open OUT: the account directory searched for an existing file (1) and the first
    granule (1); three one-granule writes; close: the account directory searched and
    written (3, creating the account's entry), the new file directory searched and written
    (3), and the header (1). At 10 ticks an access that is 120 ticks."""
    system = System(fileSettings=FileSystemSettings(discTime=10))
    system.startUser("writer", Writer("T", ["A", "B", "C"]), priority=0xF8)
    system.run()
    assert happened(system, "writer", "ended") == [120]
    assert len(happened(system, "writer", "IO_STARTED: RUNNING -> IO_WAIT")) == 5


def testUsersQueueForTheDisc():
    """Two readers' transfers share the one disc: each waits for the other's."""
    system = System(fileSettings=FileSystemSettings(discTime=10))
    files, owner = system.files, userOf(system, "owner")
    written(files, owner, "A", ["1", "2", "3"])
    written(files, owner, "B", ["4", "5", "6"])
    system.startUser("first", Reader("A", account="GUEST"), priority=0xF8)
    system.startUser("second", Reader("B", account="GUEST"), priority=0xF8)
    system.run()
    completions = [entry.time for entry in system.trace if "IO_COMPLETE" in entry.what]
    assert completions == sorted(set(completions))         # one at a time
    assert len(completions) == 2 * (1 + 3)                 # an open and three reads each


def testOpenAndCloseAreOneUserAtATime():
    """With disc time, an open holds the open/close lock while it waits for the disc, so
    a second user opening at the same time blocks on OPEN_CLOSE."""
    system = System(fileSettings=FileSystemSettings(discTime=10))
    system.startUser("a", Writer("A", ["1"]), priority=0xF8)
    system.startUser("b", Writer("B", ["2"]), priority=0xF8)
    system.run()
    blocked = "RESOURCE_BLOCK(OPEN_CLOSE): RUNNING -> AWAITING_RESOURCE"
    assert happened(system, "b", blocked)
    assert system.files.fileNames("GUEST") == ["A", "B"]


def testFilesLeftOpenAreClosedWhenTheUserEnds():
    class Forgetful(Program):
        def run(self, m):
            out = fileDcb("KEPT", FileMode.OUT)
            m.open(out)
            m.write(out, "SAVED")

    system = System()
    system.startUser("forgetful", Forgetful(), priority=0xF8)
    system.run()
    assert system.files.fileNames("GUEST") == ["KEPT"]
