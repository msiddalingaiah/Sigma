"""``python -m cpvmodel`` runs a small demo: two computations, a user reading a tape, and a
sleeper, with 12 pages of memory for 18 pages of users, so the swap scheduler has work to do.
``python -m cpvmodel terminal`` logs a user on at a terminal, beside a cruncher.
``python -m cpvmodel docs`` regenerates the generated docs (glossary, state diagram)."""

import sys

from . import DCB, Program, SchedulerSettings, System
from .generated import writeGeneratedDocs


class Cruncher(Program):
    """Computes ``steps`` times for ``ticks``."""

    def __init__(self, steps, ticks):
        self.steps, self.ticks = steps, ticks

    def run(self, m):
        for _ in range(self.steps):
            self.compute(self.ticks)


class TapeReader(Program):
    """Reads a tape, computing a little on each record."""

    def __init__(self, records):
        self.tape = DCB("F:TAPE", device="tape", records=list(records))

    def run(self, m):
        while True:
            self.compute(5)
            if m.read(self.tape) is None:
                return


class Clock(Program):
    """Wakes up every 100 ticks to do a little work."""

    def __init__(self, ticks):
        self.ticks = ticks

    def run(self, m):
        for _ in range(self.ticks):
            m.wait(100)
            self.compute(2)


def demo():
    system = System(settings=SchedulerSettings(swapTime=10), memoryPages=12)
    system.io.addDevice("tape", 30)
    system.startUser("alpha", Cruncher(3, 200), priority=0xF8, pages=5)
    system.startUser("beta", Cruncher(3, 200), priority=0xF8, pages=5)
    system.startUser("editor", TapeReader(["A", "B"]), priority=0xF8, pages=4)
    system.startUser("clock", Clock(2), priority=0xFC, pages=4)
    outcome = system.run()
    return system, outcome


def terminalDemo():
    """A break on line 0 logs a user on (TEL is stood in for by an echo session). They type
    two commands and OFF, while a cruncher runs."""
    system = System()
    system.startUser("cruncher", Cruncher(1, 1500), priority=0xF8)
    terminals = system.terminals
    terminals.breakAt(20, 0)
    terminals.typeAt(300, 0, "HELLO")
    terminals.typeAt(700, 0, "SHOW TIME")
    terminals.typeAt(1100, 0, "OFF")
    outcome = system.run()
    return system, outcome


if __name__ == "__main__":
    if sys.argv[1:] == ["docs"]:
        for path in writeGeneratedDocs():
            print(path)
    elif sys.argv[1:] == ["terminal"]:
        system, outcome = terminalDemo()
        print(system.traceText())
        print(outcome)
        print()
        print("The terminal:")
        print(system.terminals.lines[0].printed())
    else:
        system, outcome = demo()
        print(system.traceText())
        print(outcome)
