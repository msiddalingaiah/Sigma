"""Event reports in a running system: sleeping, I/O, yielding, and the priority boosts."""

import pytest

from cpvmodel import Event, InconsistentEvent, System, UserState

from .scripts import Script, compute, io, monitorEvent, sleep



def statesOf(system, name):
    return [entry.what for entry in system.trace if entry.user == name and "->" in entry.what]


def testSleepThenWakeUpWithTheSpecialComputeBoost():
    system = System()
    user = system.startUser("sleeper", Script(sleep(50), compute(1)), priority=0xF8)
    system.scheduler.dispatch()
    system.execute(user)
    assert user.state is UserState.ASLEEP
    assert system.scheduler.currentUser is None
    system.advanceClock(50)
    assert user.state is UserState.READY
    assert user.priority == 0xF8 - 3


def testIoWaitEndsWhenTheIoCompletesWithTheIoBoost():
    system = System()
    user = system.startUser("reader", Script(io(20), compute(1)), priority=0xF8)
    system.scheduler.dispatch()
    system.execute(user)
    assert user.state is UserState.IO_WAIT
    assert user.ioInFlight == 1
    system.advanceClock(20)
    assert user.state is UserState.READY
    assert user.ioInFlight == 0
    assert user.priority == 0xF8 - 2


def testIoAlreadyDoneMeansNoWait():
    system = System()
    user = system.startUser("fast", Script(), priority=0xF8)
    system.scheduler.dispatch()
    system.scheduler.report(user, Event.IO_STARTED)        # UB:MF is 0: GRANT
    assert user.state is UserState.RUNNING
    assert system.scheduler.currentUser is user


def testWakeUpForAUserWhoIsNotAsleepIsIgnored():
    system = System()
    user = system.startUser("alpha", Script(), priority=0xF8)
    system.scheduler.report(user, Event.WAKE_UP)
    assert user.state is UserState.READY


def testSleepWhileReadyIsInconsistent():
    system = System()
    user = system.startUser("alpha", Script(), priority=0xF8)
    with pytest.raises(InconsistentEvent):
        system.scheduler.report(user, Event.SLEEP)


def testYieldGoesBehindEqualPriorities():
    system = System()
    system.startUser("polite", Script(monitorEvent(Event.YIELD), compute(1)), priority=0xF8)
    system.startUser("other", Script(compute(1)), priority=0xF8)
    system.run()
    order = [entry.user for entry in system.trace if entry.what.startswith("dispatched")]
    assert order[:3] == ["polite", "other", "polite"]


def testRealTimeUsersDontFloat():
    system = System()
    user = system.startUser("rt", Script(), priority=0x80)
    assert user.priority == 0x80


def testANewcomersBoostCanOutrankAnIoBoost():
    """The editor starts I/O at once, and the cruncher runs at X'F3' on its newcomer boost.
    When the editor's I/O ends at 30 it is ready at X'F6', less urgent than X'F3', so the
    cruncher isn't preempted. The editor runs when the cruncher's quantum ends at 250."""
    system = System()
    system.startUser("editor", Script(io(30), compute(5)), priority=0xF8)
    system.startUser("cruncher", Script(compute(400)), priority=0xF8)
    assert system.run() == "shutdown"
    assert statesOf(system, "editor") == ["IO_STARTED: RUNNING -> IO_WAIT",
                                          "IO_COMPLETE: IO_WAIT -> READY"]
    assert not any(entry.what == "preempted" for entry in system.trace)
    dispatches = [(entry.time, entry.user) for entry in system.trace
                  if entry.what.startswith("dispatched")]
    assert dispatches[:3] == [(0, "editor"), (0, "cruncher"), (250, "editor")]


def testIdleUntilTheNextEvent():
    system = System()
    system.startUser("sleeper", Script(sleep(100), compute(1)), priority=0xF8)
    assert system.run() == "shutdown"
    assert any(entry.what == "idle" for entry in system.trace)
    assert system.clock == 101


def testAUserWaitingForeverLeavesTheSystemStuck():
    system = System()
    user = system.startUser("waiter", Script(), priority=0xF8)
    system.scheduler.dispatch()
    system.scheduler.report(user, Event.WAIT_FOR_INTERRUPT)
    assert system.run() == "stuck"
