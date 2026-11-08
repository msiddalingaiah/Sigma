"""The file system: directories, consecutive files, open and close, and disc time."""

import pytest

from cpvmodel import (Close, Compute, FileError, FileMode, FileSystemSettings, Open, ReadRecord,
                      Sleep, System, WriteRecord)
from cpvmodel.filesystem import GRANULE_BYTES, NO_SUCH_FILE, WRONG_MODE


def program(*steps):
    yield from steps


def happened(system, name, what):
    return [entry.time for entry in system.trace if entry.user == name and entry.what == what]


def writer(name, records, account=None):
    handle = yield Open(name, FileMode.OUT, account)
    for text in records:
        yield WriteRecord(handle, text)
    yield Close(handle)


def reader(name, into, account=None):
    handle = yield Open(name, FileMode.IN, account)
    while (text := (yield ReadRecord(handle))) is not None:
        into.append(text)
    yield Close(handle)


def userOf(system, name="u"):
    return system.startUser(name, program(), priority=0xF8)


# --- Directly through the FileSystem -------------------------------------------------------

def testRecordsComeBackInOrder():
    system = System()
    files, user = system.files, userOf(system)
    out = files.openFile(user, "DATA", FileMode.OUT)
    for text in ("ONE", "TWO", "THREE"):
        files.writeRecord(out, text)
    files.closeFile(out)
    handle = files.openFile(user, "DATA", FileMode.IN)
    assert [files.readRecord(handle) for _ in range(4)] == ["ONE", "TWO", "THREE", None]


def testALongRecordIsSplitAcrossGranules():
    system = System()
    files, user = system.files, userOf(system)
    out = files.openFile(user, "BIG", FileMode.OUT)
    files.writeRecord(out, "X" * 5000)
    files.closeFile(out)
    file, _ = files.lookUp("GUEST", "BIG")
    assert len(file.granules) == 3                 # 1728 + 2048 + the rest
    assert file.granules[0].capacity == GRANULE_BYTES - 320
    handle = files.openFile(user, "BIG", FileMode.IN)
    assert files.readRecord(handle) == "X" * 5000
    assert handle.takeDiscAccesses() == 3 + 3      # the open, then three granules


def testANewFileIsntInTheDirectoryUntilClosed():
    system = System()
    files, user = system.files, userOf(system)
    out = files.openFile(user, "NEW", FileMode.OUT)
    files.writeRecord(out, "A")
    with pytest.raises(FileError) as error:
        files.openFile(user, "NEW", FileMode.IN)
    assert error.value.code == NO_SUCH_FILE
    files.closeFile(out)
    assert files.fileNames("GUEST") == ["NEW"]


def testReplacingAFileReleasesTheOldGranules():
    system = System()
    files, user = system.files, userOf(system)
    for text in ("OLD", "NEW"):
        out = files.openFile(user, "F", FileMode.OUT)
        files.writeRecord(out, text)
        files.closeFile(out)
    assert files.disc.freeCount() == 512 - 1 - 2   # the file, and the two directories
    handle = files.openFile(user, "F", FileMode.IN)
    assert files.readRecord(handle) == "NEW"


def testReadersShareTheOpenFileButNotThePosition():
    system = System()
    files, user = system.files, userOf(system)
    out = files.openFile(user, "S", FileMode.OUT)
    files.writeRecord(out, "A")
    files.writeRecord(out, "B")
    files.closeFile(out)
    first = files.openFile(user, "S", FileMode.IN)
    second = files.openFile(user, "S", FileMode.IN)
    assert first.file is second.file and first.file.openCount == 2
    assert second.takeDiscAccesses() == 0          # found among the open files
    assert files.readRecord(first) == "A"
    assert files.readRecord(second) == "A"
    files.closeFile(first)
    files.closeFile(second)
    assert files.openFiles == {}


def testReadingAFileOpenedOutIsAnError():
    system = System()
    files, user = system.files, userOf(system)
    out = files.openFile(user, "W", FileMode.OUT)
    with pytest.raises(FileError) as error:
        files.readRecord(out)
    assert error.value.code == WRONG_MODE


def testAccountsKeepTheirOwnFiles():
    system = System()
    files, user = system.files, userOf(system)
    for account in ("ALPHA", "BETA"):
        out = files.openFile(user, "SAME", FileMode.OUT, account)
        files.writeRecord(out, account)
        files.closeFile(out)
    handle = files.openFile(user, "SAME", FileMode.IN, "BETA")
    assert files.readRecord(handle) == "BETA"


# --- Through programs -----------------------------------------------------------------------

def testAProgramWritesAndAnotherReads():
    got = []
    system = System()
    system.startUser("writer", writer("DATA", ["ONE", "TWO"]), priority=0xF8)

    def lateReader():
        yield Sleep(100)
        yield from reader("DATA", got)

    system.startUser("reader", lateReader(), priority=0xF8)
    assert system.run() == "shutdown"
    assert got == ["ONE", "TWO"]


def testAnUncaughtFileErrorEndsTheUser():
    system = System()
    system.startUser("lost", reader("MISSING", []), priority=0xF8)
    system.run()
    assert happened(system, "lost", "ended: file error X'03': no file MISSING in GUEST") == [0]


def testAProgramCanCatchAFileError():
    caught = []

    def careful():
        try:
            yield Open("MISSING", FileMode.IN)
        except FileError as error:
            caught.append(error.code)
        yield Compute(1)

    system = System()
    system.startUser("careful", careful(), priority=0xF8)
    assert system.run() == "shutdown"
    assert caught == [NO_SUCH_FILE]


def testFileOperationsTakeDiscTime():
    """Open OUT: one access; three one-granule writes; close: the account directory
    searched and written (3, creating the account's entry), the new file directory searched
    and written (3), and the header (1). At 10 ticks an access that is 110 ticks."""
    system = System(fileSettings=FileSystemSettings(discTime=10))
    system.startUser("writer", writer("T", ["A", "B", "C"]), priority=0xF8)
    system.run()
    assert happened(system, "writer", "ended") == [110]
    assert len(happened(system, "writer", "IO_STARTED: RUNNING -> IO_WAIT")) == 5


def testOpenAndCloseAreOneUserAtATime():
    """With disc time, an open holds the open/close lock while it waits for the disc, so
    a second user opening at the same time blocks on OPEN_CLOSE."""
    system = System(fileSettings=FileSystemSettings(discTime=10))
    system.startUser("a", writer("A", ["1"]), priority=0xF8)
    system.startUser("b", writer("B", ["2"]), priority=0xF8)
    system.run()
    blocked = "RESOURCE_BLOCK(OPEN_CLOSE): RUNNING -> AWAITING_RESOURCE"
    assert happened(system, "b", blocked)
    assert system.files.fileNames("GUEST") == ["A", "B"]


def testFilesLeftOpenAreClosedWhenTheUserEnds():
    def forgetful():
        handle = yield Open("KEPT", FileMode.OUT)
        yield WriteRecord(handle, "SAVED")

    system = System()
    system.startUser("forgetful", forgetful(), priority=0xF8)
    system.run()
    assert system.files.fileNames("GUEST") == ["KEPT"]
