"""Resources: blocking, release (flush, specific, last in first out), open/close, and signals."""

import pytest

from cpvmodel import (Compute, Event, InconsistentEvent, OpenClose, Release, Resource,
                      SchedulerSettings, System, UserState, WaitFor)


def program(*steps):
    yield from steps


def happened(system, name, what):
    return [entry.time for entry in system.trace if entry.user == name and entry.what == what]


def releaseOrder(system):
    return [entry.user for entry in system.trace if entry.what.startswith("released from")]


def testAUserBlocksAndAFlushReleasesEveryone():
    system = System()
    a = system.startUser("a", program(WaitFor(Resource.DISC_PAGE), Compute(1)), priority=0xF8)
    b = system.startUser("b", program(WaitFor(Resource.DISC_PAGE), Compute(1)), priority=0xF8)
    system.startUser("mm", program(Compute(50), Release(Resource.DISC_PAGE)), priority=0xFC)
    system.run(tickLimit=10)
    assert a.state is b.state is UserState.AWAITING_RESOURCE
    assert a.blockedOn is Resource.DISC_PAGE
    assert system.run() == "shutdown"
    assert sorted(releaseOrder(system)) == ["a", "b"]
    assert happened(system, "a", "released from DISC_PAGE") == [50]


def testAReleasedUserGetsTheSpecialComputeBoost():
    system = System()
    a = system.startUser("a", program(WaitFor(Resource.DISC_PAGE), Compute(1)), priority=0xF8)
    system.run(tickLimit=1)
    system.scheduler.report(a, Event.RESOURCE_RELEASE, Resource.DISC_PAGE)
    assert a.state is UserState.READY
    assert a.priority == 0xF8 - 3


def testReleaseWithNobodyWaitingDoesNothing():
    system = System()
    user = system.startUser("a", program(Release(Resource.DISC_PAGE), Compute(1)), priority=0xF8)
    assert system.run() == "shutdown"
    assert releaseOrder(system) == []


def testBlockingIsOnlyForTheRunningUser():
    system = System()
    user = system.startUser("a", program(), priority=0xF8)
    with pytest.raises(InconsistentEvent):
        system.scheduler.report(user, Event.RESOURCE_BLOCK, Resource.DISC_PAGE)


def openCloseContention():
    """Each user opens a file for 50 ticks; with a 20-tick quantum the others get to run,
    and block, while a holds the open/close."""
    system = System(settings=SchedulerSettings(quantum=20))
    for name in ("a", "b", "c"):
        system.startUser(name, program(OpenClose(50)), priority=0xF8)
    assert system.run() == "shutdown"
    return system


def testOnlyOneUserAtATimeOpensAndCloses():
    system = openCloseContention()
    events = [(entry.user, entry.what) for entry in system.trace
              if entry.what.startswith("open/close")]
    holders = [user for user, what in events if what == "open/close starts"]
    assert len(holders) == 3
    for i in range(0, 6, 2):                    # every start is followed by its own done
        assert events[i][1] == "open/close starts" and events[i + 1] == (events[i][0],
                                                                         "open/close done")
    assert happened(system, "b", "RESOURCE_BLOCK(OPEN_CLOSE): RUNNING -> AWAITING_RESOURCE")
    assert system.scheduler.resources.openCloseUser is None


def testOpenCloseWaitersAreReleasedLastInFirstOut():
    """CP-V quirk: a blocked user goes on the head of the resource's queue, and a release
    takes the head. a opens first; b, then c, block; c gets in before b."""
    system = openCloseContention()
    starts = [entry.user for entry in system.trace if entry.what == "open/close starts"]
    assert starts == ["a", "c", "b"]


def testASpecificReleaseReleasesOnlyThatUser():
    system = System()
    a = system.startUser("a", program(WaitFor(Resource.ENQUEUE), Compute(1)), priority=0xF8)
    b = system.startUser("b", program(WaitFor(Resource.ENQUEUE), Compute(1)), priority=0xF8)
    system.run(tickLimit=1)
    system.scheduler.report(a, Event.RESOURCE_RELEASE, Resource.ENQUEUE)
    assert a.state is UserState.READY
    assert b.state is UserState.AWAITING_RESOURCE


def testASpecificReleaseForAUserWhoIsntBlockedDoesNothing():
    system = System()
    a = system.startUser("a", program(WaitFor(Resource.ENQUEUE), Compute(1)), priority=0xF8)
    other = system.startUser("other", program(Compute(5)), priority=0xFC)
    system.run(tickLimit=1)
    system.scheduler.report(other, Event.RESOURCE_RELEASE, Resource.ENQUEUE)
    assert a.state is UserState.AWAITING_RESOURCE


def testAnAbortReleasesAUserWaitingInEnq():
    system = System()
    a = system.startUser("a", program(WaitFor(Resource.ENQUEUE), Compute(1)), priority=0xF8)
    system.reportAt(30, a, Event.ABORT)
    assert system.run() == "shutdown"
    assert happened(system, "a", "ended: aborted") == [30]


def testAnAbortWaitsForTheReleaseOfOtherResources():
    system = System()
    a = system.startUser("a", program(WaitFor(Resource.DISC_PAGE), Compute(1)), priority=0xF8)
    system.reportAt(30, a, Event.ABORT)
    system.run(tickLimit=60)
    assert a.state is UserState.AWAITING_RESOURCE           # flagged, still blocked
    system.reportAt(100, a, Event.RESOURCE_RELEASE, Resource.DISC_PAGE)
    system.run()
    assert happened(system, "a", "ended: aborted") == [100]
