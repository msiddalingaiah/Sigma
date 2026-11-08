"""Granule allocation: the bit map, the stack and its thresholds, and the ALLOCAT ghost."""

from cpvmodel import FileMode, FileSystemSettings, Program, System, UserState
from cpvmodel.filesystem import AllocationMap, Disc
from cpvmodel.scheduler.statequeues import REAL_TIME_BAND

from .scripts import Script, Writer, compute, fileDcb, happened


def bigWriter(records, size=2000):
    return Writer("BIG", ["X" * size] * records)


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


def testAUserWithTheStackEmptyWaitsInTheMiddleOfAWrite():
    """GETGRAN finds the stack empty partway through a write: the user waits for ALLOCAT's
    fill (E:QFAC), then the write goes on where it stopped."""
    system = System()
    allocator = system.files.disc.allocator
    writer = system.startUser("writer", Writer("BIG", ["X" * 5000]), priority=0xF8)
    for address in allocator.stack.addresses:          # empty, without waking ALLOCAT
        allocator.map.give(address)
    allocator.stack.addresses.clear()
    assert system.run() == "shutdown"
    assert happened(system, "writer", "waits for granules")
    assert happened(system, "writer", "released from ALLOCATOR")
    file, _ = system.files.lookUp("GUEST", "BIG")
    assert len(file.granules) == 3


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
    early = system.startUser("early", Script(compute(10)), priority=0xE0)
    late = system.startUser("late", Script(compute(10)), priority=0xC2)
    queues = system.scheduler.stateQueues
    assert queues.bandOf[late] == REAL_TIME_BAND and late.priority == 0xC2
    assert system.scheduler.dispatch() is late


def testAFileLeftOpenIsClosedEvenWithTheStackShort():
    """The program ends with its file open and the stack empty: the monitor closes it at
    step end without waiting, taking the directory's granule from the map."""
    class Leaver(Program):
        def run(self, m):
            out = fileDcb("LEFT", FileMode.OUT)
            m.open(out)
            m.write(out, "data")
            m.wait(100)

    system = System()
    allocator = system.files.disc.allocator
    leaverUser = system.startUser("leaver", Leaver(), priority=0xF8)
    system.run(tickLimit=50)
    assert leaverUser.state is UserState.ASLEEP
    while allocator.stack.count() > 0:
        allocator.get()
    system.run()
    assert "LEFT" in system.files.fileNames("GUEST")
