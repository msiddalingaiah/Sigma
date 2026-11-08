"""The exit path: quanta, preemption, the minimum run, and signals."""

from cpvmodel import Break, Event, Program, SchedulerSettings, System, UserState

from .scripts import Script, compute, io, sleep



def happened(system, name, what):
    return [entry.time for entry in system.trace if entry.user == name and entry.what == what]


def dispatchTimes(system, name):
    return [entry.time for entry in system.trace
            if entry.user == name and entry.what.startswith("dispatched")]


def testALongComputeIsCutIntoQuanta():
    system = System(settings=SchedulerSettings(quantum=100))
    system.startUser("cruncher", Script(compute(250)), priority=0xF8)
    assert system.run() == "shutdown"
    assert happened(system, "cruncher", "quantum ended") == [100, 200]
    assert system.clock == 250


def testEqualUsersAlternateAtQuantumEnds():
    system = System(settings=SchedulerSettings(quantum=100))
    system.startUser("alpha", Script(compute(200)), priority=0xF8)
    system.startUser("beta", Script(compute(200)), priority=0xF8)
    system.run()
    # Each finishes its step exactly as its second quantum ends, so it is dispatched once
    # more only to end (its exit CAL).
    assert dispatchTimes(system, "alpha") == [0, 200, 400]
    assert dispatchTimes(system, "beta") == [100, 300, 400]


def preemptionScenario(minimumRun, ioTicks):
    """The cruncher's first quantum ends at 100. The editor then starts I/O and the cruncher
    runs again, now at its base X'F8'. When the I/O ends the editor is ready at X'F6'."""
    system = System(settings=SchedulerSettings(quantum=100, minimumRun=minimumRun))
    system.startUser("cruncher", Script(compute(1000)), priority=0xF8)
    system.startUser("editor", Script(io(ioTicks), compute(5)), priority=0xF8)
    system.run()
    return system


def testAMoreUrgentUserPreemptsAtTheInterrupt():
    system = preemptionScenario(minimumRun=10, ioTicks=120)
    assert happened(system, "cruncher", "preempted") == [220]
    assert 220 in dispatchTimes(system, "editor")
    assert 225 in dispatchTimes(system, "cruncher")


def testNoPreemptionBeforeTheMinimumRun():
    # The cruncher is dispatched again at 200 (quantum end) and the I/O ends at 205.
    system = preemptionScenario(minimumRun=10, ioTicks=105)
    assert happened(system, "cruncher", "preempted") == []
    assert dispatchTimes(system, "editor") == [100, 300]


def testWithNoMinimumRunThePreemptionIsImmediate():
    system = preemptionScenario(minimumRun=0, ioTicks=105)
    assert happened(system, "cruncher", "preempted") == [205]


class BreakCatcher(Program):
    """Computes, and has a break routine: it catches Break and computes a little more."""

    def __init__(self, log):
        self.log = log

    def run(self, m):
        try:
            self.compute(1000)
        except Break:
            self.log.append("caught")
            self.compute(5)


def breakCatcher(log):
    return BreakCatcher(log)


def testABreakIsThrownIntoTheProgram():
    log = []
    system = System()
    user = system.startUser("catcher", breakCatcher(log), priority=0xF8)
    system.reportAt(50, user, Event.BREAK)
    assert system.run() == "shutdown"
    assert log == ["caught"]
    assert system.clock == 55
    assert happened(system, "catcher", "ended") == [55]


def testAnUncaughtBreakGoesBackToTheCommandProcessor():
    system = System()
    user = system.startUser("plain", Script(compute(1000)), priority=0xF8)
    system.reportAt(50, user, Event.BREAK)
    system.run()
    assert happened(system, "plain",
                    "ended: break with no break routine: back to the command processor") == [50]


def testAbortWakesASleeper():
    system = System()
    user = system.startUser("sleeper", Script(sleep(500), compute(5)), priority=0xF8)
    system.reportAt(100, user, Event.ABORT)
    assert system.run() == "shutdown"
    assert happened(system, "sleeper", "ABORT: ASLEEP -> READY") == [100]
    assert happened(system, "sleeper", "ended: aborted") == [100]
    assert system.clock == 100                  # the wake-up at 500 was dropped


def testAnErrorWaitsForTheIoToFinish():
    system = System()
    user = system.startUser("reader", Script(io(100), compute(5)), priority=0xF8)
    system.reportAt(20, user, Event.ERROR)
    system.run(tickLimit=50)
    assert user.state is UserState.IO_WAIT      # flagged, not woken
    system.run()
    assert happened(system, "reader", "ended: error") == [100]


def testBreakAndControlYTogetherActAsControlY():
    """CP-V clears all four flags and acts on the most important one only."""
    log = []
    system = System()
    user = system.startUser("catcher", breakCatcher(log), priority=0xF8)
    system.reportAt(50, user, Event.BREAK)
    system.reportAt(50, user, Event.CONTROL_Y)
    system.run()
    assert log == []
    assert happened(system, "catcher", "ended: control-Y: back to the command processor") == [50]
