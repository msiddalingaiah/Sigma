"""Granule allocation: the bit map, the stack and its thresholds, and the ALLOCAT ghost."""

import pytest

from cpvmodel import (Close, Compute, FileMode, FileSystemSettings, Open, Sleep, System,
                      UserState, WriteRecord)
from cpvmodel.filesystem import DISC_FULL, AllocationMap, Disc, GranuleShortage
from cpvmodel.scheduler.statequeues import REAL_TIME_BAND


def program(*steps):
    yield from steps


def happened(system, name, what):
    return [entry.time for entry in system.trace if entry.user == name and entry.what == what]


def bigWriter(records, size=2000):
    handle = yield Open("BIG", FileMode.OUT)
    for _ in range(records):
        yield WriteRecord(handle, "X" * size)
    yield Close(handle)


# --- The map --------------------------------------------------------------------------------

def testTheMapSearchGoesOnFromWhereItStopped():
    allocationMap = AllocationMap(10)
    assert [allocationMap.take() for _ in range(3)] == [1, 2, 3]
    allocationMap.give(1)
    assert allocationMap.take() == 4             # not 1: the search continues from 3


def testReleasingAFreeGranuleIsADualAllocation():
    allocationMap = AllocationMap(10)
    allocationMap.give(5)
    assert allocationMap.dualAllocations == [5]


# --- The stack ------------------------------------------------------------------------------

def testTheStackStartsAtItsHighLevel():
    system = System()
    stack = system.files.disc.allocator.stack
    assert stack.count() == stack.highLevel - 1  # less the account directory's block


def testALowStackStartsAllocat():
    system = System()
    allocator = system.files.disc.allocator
    while allocator.stack.count() > allocator.stack.lowThreshold:
        system.files.disc.getGranule()
    assert allocator.allocatRunning
    assert any(user.name == "ALLOCAT" for user in system.users)


def testAllocatsFillIsInvisibleUntilTheCommit():
    system = System()
    allocator = system.files.disc.allocator
    while allocator.stack.count() > 5:
        allocator.get()
    allocator.adjust()
    assert allocator.stack.count() == 5
    assert len(allocator.stack.pendingFill) == allocator.stack.highLevel - 5
    allocator.commit()
    assert allocator.stack.count() == allocator.stack.highLevel


def testAHighStackIsEmptiedToItsLowLevel():
    disc = Disc(400)
    allocator = disc.allocator
    granules = [disc.getGranule() for _ in range(200)]
    for granule in granules:
        disc.releaseGranule(granule)
    assert allocator.stack.count() > allocator.stack.highLevel
    allocator.adjust()
    assert allocator.stack.count() == allocator.stack.lowLevel
    assert disc.freeCount() == 400


def testAReleaseWithTheStackFullGoesToAllocat():
    disc = Disc(400)
    allocator = disc.allocator
    granules = [disc.getGranule() for _ in range(130)]
    for granule in granules:
        disc.releaseGranule(granule)
    assert allocator.stack.count() == allocator.stack.capacity
    assert len(allocator.stack.pendingReleases) == 2
    allocator.adjust()
    assert allocator.stack.pendingReleases == []
    assert disc.freeCount() == 400


def testAUserWhoNeedsMoreThanTheStackHasMustWait():
    system = System()
    allocator = system.files.disc.allocator
    while allocator.stack.count() > 2:
        allocator.get()
    with pytest.raises(GranuleShortage):
        allocator.ensure(3)
    assert allocator.allocatRunning


# --- With the scheduler -----------------------------------------------------------------------

def testAWriterWaitsForAllocatAndGoesOn():
    system = System()
    writer = system.startUser("writer", bigWriter(100), priority=0xF8)
    assert system.run() == "shutdown"
    waited = happened(system, "writer", "RESOURCE_BLOCK(ALLOCATOR): RUNNING -> AWAITING_RESOURCE")
    released = happened(system, "writer", "released from ALLOCATOR")
    assert waited and released and released[0] > waited[0]
    assert happened(system, "ALLOCAT", "ended")
    assert system.files.fileNames("GUEST") == ["BIG"]


def testEveryGranuleIsAccountedFor():
    system = System()
    system.startUser("writer", bigWriter(100), priority=0xF8)
    system.run()
    disc = system.files.disc
    assert disc.freeCount() + len(disc.granules) == disc.granuleCount


def testAFullDiscIsAFileErrorForTheProgram():
    system = System(fileSettings=FileSystemSettings(discGranules=30))
    system.startUser("writer", bigWriter(100), priority=0xF8)
    system.run()
    ended = [entry.what for entry in system.trace
             if entry.user == "writer" and entry.what.startswith("ended")]
    assert ended == ["ended: file error X'00': no granule left on the disc"]


# --- The scheduler quirk ALLOCAT brought out ---------------------------------------------------

def testABoostBelowX_C0_QueuesABackgroundUserAsRealTime():
    """CP-V quirk (CHSE1, CHSRT): the test is on the boosted priority. A user with base
    X'C2' starts 6 below it, at X'BC': real time, so into the real-time band, at the base."""
    system = System()
    early = system.startUser("early", program(Compute(10)), priority=0xE0)
    late = system.startUser("late", program(Compute(10)), priority=0xC2)
    queues = system.scheduler.stateQueues
    assert queues.bandOf[late] == REAL_TIME_BAND and late.priority == 0xC2
    assert system.scheduler.dispatch() is late


def testAFileLeftOpenIsClosedEvenWithTheStackShort():
    """The program ends with its file open and the stack empty: the monitor closes it at
    step end without waiting, taking the directory's granule from the map."""
    def leaver():
        handle = yield Open("LEFT", FileMode.OUT)
        yield WriteRecord(handle, "data")
        yield Sleep(100)

    system = System()
    allocator = system.files.disc.allocator
    leaverUser = system.startUser("leaver", leaver(), priority=0xF8)
    system.run(tickLimit=50)
    assert leaverUser.state is UserState.ASLEEP
    while allocator.stack.count() > 0:
        allocator.get()
    system.run()
    assert "LEFT" in system.files.fileNames("GUEST")
