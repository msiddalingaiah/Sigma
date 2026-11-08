"""The thread spike: handoff, preemption, I/O queues, breaks, aborts, errors and clean-up."""

import threading

import pytest

from cpvmodel import Break, Event, SchedulerSettings
from cpvmodel.threadspike import DCB, Program, ThreadedSystem


class Cruncher(Program):
    def __init__(self, ticks):
        self.ticks = ticks

    def run(self, m):
        self.compute(self.ticks)


class Reader(Program):
    def __init__(self, records):
        self.data = DCB("DATA", list(records))
        self.got = []

    def run(self, m):
        while (record := m.read(self.data)) is not None:
            self.got.append(record)
            self.compute(5)


class Sleeper(Program):
    def run(self, m):
        m.wait(50)
        self.compute(1)


class BreakCatcher(Program):
    caught = False

    def run(self, m):
        try:
            self.compute(1000)
        except Break:
            self.caught = True
            self.compute(5)


class Broken(Program):
    def run(self, m):
        self.compute(1)
        raise ValueError("a bug in the program")


def happened(system, name, what):
    return [entry.time for entry in system.trace if entry.user == name and entry.what == what]


def allFinished(system):
    return not system.contexts and not any(
        thread.name.startswith("user ") and thread.is_alive() for thread in threading.enumerate())


def testAProgramRunsInItsThreadAndEnds():
    system = ThreadedSystem()
    reader = Reader(["A", "B", "C"])
    system.startProgram("reader", reader, priority=0xF8)
    assert system.run() == "shutdown"
    assert reader.got == ["A", "B", "C"]
    assert allFinished(system)


def testComputeIsCutIntoQuantaAndUsersTakeTurns():
    system = ThreadedSystem(settings=SchedulerSettings(quantum=100))
    system.startProgram("alpha", Cruncher(200), priority=0xF8)
    system.startProgram("beta", Cruncher(200), priority=0xF8)
    system.run()
    dispatched = [(entry.time, entry.user) for entry in system.trace
                  if entry.what.startswith("dispatched")]
    assert dispatched[:4] == [(0, "alpha"), (100, "beta"), (200, "alpha"), (300, "beta")]


def testTwoReadersQueueForTheDisc():
    """Each read is a 10-tick disc transfer. With one disc, two readers' six reads are
    served one at a time: the last completes at 60, not 30."""
    system = ThreadedSystem(discTime=10)
    first, second = Reader("ABC"), Reader("XYZ")
    system.startProgram("first", first, priority=0xF8)
    system.startProgram("second", second, priority=0xF8)
    system.run()
    completions = [entry.time for entry in system.trace if "IO_COMPLETE" in entry.what]
    assert completions == [10, 20, 30, 40, 50, 60]
    assert first.got == list("ABC") and second.got == list("XYZ")


def testAWaitSleepsAndWakes():
    system = ThreadedSystem()
    system.startProgram("sleeper", Sleeper(), priority=0xF8)
    system.run()
    assert happened(system, "sleeper", "WAKE_UP: ASLEEP -> READY") == [50]
    assert happened(system, "sleeper", "ended") == [51]


def testABreakIsRaisedInTheProgram():
    system = ThreadedSystem()
    catcher = BreakCatcher()
    user = system.startProgram("catcher", catcher, priority=0xF8)
    system.reportAt(50, user, Event.BREAK)
    system.run()
    assert catcher.caught
    assert happened(system, "catcher", "ended") == [55]


def testAnUncaughtBreakEndsTheUser():
    system = ThreadedSystem()
    user = system.startProgram("plain", Cruncher(1000), priority=0xF8)
    system.reportAt(50, user, Event.BREAK)
    system.run()
    assert happened(system, "plain",
                    "ended: break with no break routine: back to the command processor") == [50]
    assert allFinished(system)


def testAnAbortUnwindsAWaitingUsersThread():
    system = ThreadedSystem()
    user = system.startProgram("sleeper", Sleeper(), priority=0xF8)
    system.reportAt(20, user, Event.ABORT)
    system.run()
    assert happened(system, "sleeper", "ended: aborted") == [20]
    assert allFinished(system)


def testAnErrorInAProgramReachesTheRunLoop():
    system = ThreadedSystem()
    system.startProgram("broken", Broken(), priority=0xF8)
    with pytest.raises(ValueError):
        system.run()
    assert allFinished(system)


def testRunsAreDeterministic():
    def traceOf():
        system = ThreadedSystem(settings=SchedulerSettings(quantum=30), discTime=7)
        system.startProgram("r1", Reader("ABCDE"), priority=0xF8)
        system.startProgram("r2", Reader("VWXYZ"), priority=0xF4)
        system.startProgram("c", Cruncher(120), priority=0xF8)
        system.run()
        return [str(entry) for entry in system.trace]

    assert traceOf() == traceOf() == traceOf()


def testShutdownUnwindsWaitingThreads():
    system = ThreadedSystem()
    system.startProgram("s1", Sleeper(), priority=0xF8)
    system.startProgram("s2", Sleeper(), priority=0xF8)
    system.run(tickLimit=10)
    assert len(system.contexts) == 2
    system.shutdown()
    assert allFinished(system)
