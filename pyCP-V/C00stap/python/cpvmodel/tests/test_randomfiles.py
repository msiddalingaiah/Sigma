"""Random files: a run of granules from ALLOCAT, read and written by granule number."""

import pytest

from cpvmodel import (Close, FileError, FileMode, Open, Organization, ReadRecord, System,
                      WriteRecord)
from cpvmodel.filesystem import BEYOND_END, GRANULE_BYTES, SHORT_TRANSFER, GranuleShortage


def happened(system, name, what):
    return [entry.time for entry in system.trace if entry.user == name and entry.what == what]


def randomProgram(steps, size=4, results=None):
    """Opens RAND OUT with ``size`` granules, then runs ``steps(handle)``."""
    def body():
        handle = yield Open("RAND", FileMode.OUT, organization=Organization.RANDOM, size=size)
        yield from steps(handle)
        yield Close(handle)
    return body()


def testTheRunComesFromAllocatWhileTheUserWaits():
    system = System()
    system.startUser("u", randomProgram(lambda handle: iter(())), priority=0xF8)
    assert system.run() == "shutdown"
    assert happened(system, "u", "RESOURCE_BLOCK(ALLOCATOR): RUNNING -> AWAITING_RESOURCE")
    assert system.files.fileNames("GUEST") == ["RAND"]


def testTheRunIsContiguous():
    system = System()
    system.startUser("u", randomProgram(lambda handle: iter(()), size=6), priority=0xF8)
    system.run()
    file, _ = system.files.lookUp("GUEST", "RAND")
    addresses = [granule.address for granule in file.run]
    assert addresses == list(range(addresses[0], addresses[0] + 6))


def openRandom(system, size=4):
    """A random file made through a program, then opened by the test directly."""
    system.startUser("maker", randomProgram(lambda handle: iter(()), size=size), priority=0xF8)
    system.run()
    user = system.startUser("tester", iter(()), priority=0xF8)
    return system.files, user


def testWritesAndReadsByGranuleNumber():
    system = System()
    files, user = openRandom(system)
    with pytest.raises(GranuleShortage):          # the new run: ask ALLOCAT, then again
        files.openFile(user, "RAND", FileMode.OUT, organization=Organization.RANDOM, size=4)
    system.run()
    out = files.openFile(user, "RAND", FileMode.OUT, organization=Organization.RANDOM, size=4)
    files.writeRecord(out, "third", key=2)
    files.writeRecord(out, "fourth")             # continues at the next granule
    files.closeFile(out)
    handle = files.openFile(user, "RAND", FileMode.IN)
    assert files.readRecord(handle, key=2) == "third"
    assert files.readRecord(handle) == "fourth"


def testATransferSpanningGranulesMovesThePositionPastThem():
    system = System()
    files, user = openRandom(system)
    file, _ = files.lookUp("GUEST", "RAND")
    moved = file.write(0, "A" * GRANULE_BYTES + "B")
    assert moved == 2
    text, granules = file.read(0, GRANULE_BYTES + 1)
    assert text == "A" * GRANULE_BYTES + "B" and granules == 2


def testAGranuleNumberPastTheEndIsAnError():
    system = System()
    files, user = openRandom(system, size=2)
    file, _ = files.lookUp("GUEST", "RAND")
    with pytest.raises(FileError) as error:
        file.read(2, 10)
    assert error.value.code == BEYOND_END


def testAWriteThatRunsOffTheEndMovesWhatFits():
    system = System()
    files, user = openRandom(system, size=2)
    file, _ = files.lookUp("GUEST", "RAND")
    with pytest.raises(FileError) as error:
        file.write(1, "C" * (2 * GRANULE_BYTES))
    assert error.value.code == SHORT_TRANSFER
    assert file.contents[1] == "C" * GRANULE_BYTES


def testDeletingARandomFileGivesItsRunBack():
    def lifecycle():
        handle = yield Open("RAND", FileMode.OUT, organization=Organization.RANDOM, size=10)
        yield WriteRecord(handle, "data", key=0)
        yield Close(handle)
        again = yield Open("RAND", FileMode.IN)
        yield ReadRecord(again, key=0)
        yield Close(again, release=True)

    system = System()
    total = system.files.disc.granuleCount
    system.startUser("u", lifecycle(), priority=0xF8)
    system.run()
    disc = system.files.disc
    assert system.files.fileNames("GUEST") == []
    assert disc.freeCount() + len(disc.granules) == total
