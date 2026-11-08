"""Event reports in a running system: sleeping, I/O, yielding, and the priority boosts."""

import pytest

from cpvmodel import (Compute, DoIo, Event, InconsistentEvent, Sleep, System, UserState,
                      Yield)


def program(*steps):
    yield from steps


def statesOf(system, name):
    return [entry.what for entry in system.trace if entry.user == name and "->" in entry.what]


def testSleepThenWakeUpWithTheSpecialComputeBoost():
    system = System()
    user = system.startUser("sleeper", program(Sleep(50), Compute(1)), priority=0xF8)
    system.dispatch()
    system.execute(user)
    assert user.state is UserState.ASLEEP
    assert system.currentUser is None
    system.advanceClock(50)
    assert user.state is UserState.READY
    assert user.priority == 0xF8 - 3


def testIoWaitEndsWhenTheIoCompletesWithTheIoBoost():
    system = System()
    user = system.startUser("reader", program(DoIo(20), Compute(1)), priority=0xF8)
    system.dispatch()
    system.execute(user)
    assert user.state is UserState.IO_WAIT
    assert user.ioInFlight == 1
    system.advanceClock(20)
    assert user.state is UserState.READY
    assert user.ioInFlight == 0
    assert user.priority == 0xF8 - 2


def testIoAlreadyDoneMeansNoWait():
    system = System()
    user = system.startUser("fast", program(), priority=0xF8)
    system.dispatch()
    system.router.report(user, Event.IO_STARTED)        # UB:MF is 0: GRANT
    assert user.state is UserState.RUNNING
    assert system.currentUser is user


def testWakeUpForAUserWhoIsNotAsleepIsIgnored():
    system = System()
    user = system.startUser("alpha", program(), priority=0xF8)
    system.router.report(user, Event.WAKE_UP)
    assert user.state is UserState.READY


def testSleepWhileReadyIsInconsistent():
    system = System()
    user = system.startUser("alpha", program(), priority=0xF8)
    with pytest.raises(InconsistentEvent):
        system.router.report(user, Event.SLEEP)


def testYieldGoesBehindEqualPriorities():
    system = System()
    system.startUser("polite", program(Yield(), Compute(1)), priority=0xF8)
    system.startUser("other", program(Compute(1)), priority=0xF8)
    system.run()
    order = [entry.user for entry in system.trace if entry.what.startswith("dispatched")]
    assert order[:3] == ["polite", "other", "polite"]


def testRealTimeUsersDontFloat():
    system = System()
    user = system.startUser("rt", program(), priority=0x80)
    assert user.priority == 0x80


def testAWokenUserRunsWhileOthersWait():
    system = System()
    system.startUser("editor", program(Compute(5), DoIo(30), Compute(5)), priority=0xF8)
    system.startUser("cruncher", program(*[Compute(10) for _ in range(10)]), priority=0xF8)
    assert system.run() == "shutdown"
    assert statesOf(system, "editor") == ["IO_STARTED: RUNNING -> IO_WAIT",
                                          "IO_COMPLETE: IO_WAIT -> READY"]
    trace = [(entry.time, entry.user) for entry in system.trace
             if entry.what.startswith("dispatched")]
    # Woken at 35 with the I/O boost, the editor runs as soon as the cruncher's quantum ends.
    assert (45, "editor") in trace


def testIdleUntilTheNextEvent():
    system = System()
    system.startUser("sleeper", program(Sleep(100), Compute(1)), priority=0xF8)
    assert system.run() == "shutdown"
    assert any(entry.what == "idle" for entry in system.trace)
    assert system.clock == 101


def testAUserWaitingForeverLeavesTheSystemStuck():
    system = System()
    user = system.startUser("waiter", program(), priority=0xF8)
    system.dispatch()
    system.router.report(user, Event.WAIT_FOR_INTERRUPT)
    assert system.run() == "stuck"
