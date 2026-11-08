"""Random files: a run of granules from ALLOCAT, read and written by granule number."""

import pytest

from cpvmodel import FileError, FileMode, Organization, Program, System
from cpvmodel.filesystem import BEYOND_END, GRANULE_BYTES, SHORT_TRANSFER

from .scripts import Script, fileDcb, happened, openFile


class RandomUser(Program):
    """Creates RAND with ``size`` granules, then optionally writes, reads it back, and
    deletes it."""

    def __init__(self, size=4, lifecycle=False):
        self.rand = fileDcb("RAND", organization=Organization.RANDOM, size=size)
        self.lifecycle = lifecycle
        self.read = None

    def run(self, m):
        m.open(self.rand, mode=FileMode.OUT)
        if self.lifecycle:
            m.write(self.rand, "data", key=0)
        m.close(self.rand)
        if self.lifecycle:
            m.open(self.rand, mode=FileMode.IN)
            self.read = m.read(self.rand, key=0)
            m.close(self.rand, release=True)


def testTheRunComesFromAllocatWhileTheUserWaits():
    system = System()
    system.startUser("u", RandomUser(), priority=0xF8)
    assert system.run() == "shutdown"
    assert happened(system, "u", "RESOURCE_BLOCK(ALLOCATOR): RUNNING -> AWAITING_RESOURCE")
    assert system.files.fileNames("GUEST") == ["RAND"]


def testTheRunIsContiguous():
    system = System()
    system.startUser("u", RandomUser(size=6), priority=0xF8)
    system.run()
    file, _ = system.files.lookUp("GUEST", "RAND")
    addresses = [granule.address for granule in file.run]
    assert addresses == list(range(addresses[0], addresses[0] + 6))


def randomFile(size=4):
    """A random file made straight through the file system (the monitor needs no ALLOCAT
    for it), and a user."""
    system = System()
    user = system.startUser("tester", Script(), priority=0xF8)
    files = system.files
    files.close(user, openFile(files, user, "RAND", FileMode.OUT,
                               organization=Organization.RANDOM, size=size))
    file, _ = files.lookUp("GUEST", "RAND")
    return system, user, file


def testWritesAndReadsByGranuleNumber():
    system, user, _ = randomFile()
    files = system.files
    out = openFile(files, user, "RAND", FileMode.OUT, organization=Organization.RANDOM, size=4)
    files.write(user, out, "third", key=2)
    files.write(user, out, "fourth")             # continues at the next granule
    files.close(user, out)
    dcb = openFile(files, user, "RAND")
    assert files.read(user, dcb, key=2) == "third"
    assert files.read(user, dcb) == "fourth"


def testATransferSpanningGranulesMovesThePositionPastThem():
    _, _, file = randomFile()
    assert file.write(0, "A" * GRANULE_BYTES + "B") == 2
    text, granules = file.read(0, GRANULE_BYTES + 1)
    assert text == "A" * GRANULE_BYTES + "B" and granules == 2


def testAGranuleNumberPastTheEndIsAnError():
    _, _, file = randomFile(size=2)
    with pytest.raises(FileError) as error:
        file.read(2, 10)
    assert error.value.code == BEYOND_END


def testAWriteThatRunsOffTheEndMovesWhatFits():
    _, _, file = randomFile(size=2)
    with pytest.raises(FileError) as error:
        file.write(1, "C" * (2 * GRANULE_BYTES))
    assert error.value.code == SHORT_TRANSFER
    assert file.contents[1] == "C" * GRANULE_BYTES


def testDeletingARandomFileGivesItsRunBack():
    system = System()
    total = system.files.disc.granuleCount
    program = RandomUser(size=10, lifecycle=True)
    system.startUser("u", program, priority=0xF8)
    system.run()
    disc = system.files.disc
    assert program.read == "data"
    assert system.files.fileNames("GUEST") == []
    assert disc.freeCount() + len(disc.granules) == total
