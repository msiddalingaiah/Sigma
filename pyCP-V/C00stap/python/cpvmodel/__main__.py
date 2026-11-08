"""``python -m cpvmodel`` runs a small demo: two computations, an I/O user and a sleeper,
with 12 pages of memory for 18 pages of users, so the swap scheduler has work to do.
``python -m cpvmodel docs`` regenerates the generated docs (glossary, state diagram)."""

import sys

from . import Compute, DoIo, SchedulerSettings, Sleep, System
from .generated import writeGeneratedDocs


def cruncher(steps, ticks):
    for _ in range(steps):
        yield Compute(ticks)


def ioUser(steps):
    for _ in range(steps):
        yield Compute(5)
        yield DoIo(30)


def sleeper(steps):
    for _ in range(steps):
        yield Sleep(100)
        yield Compute(2)


def demo():
    system = System(settings=SchedulerSettings(swapTime=10), memoryPages=12)
    system.startUser("alpha", cruncher(3, 200), priority=0xF8, pages=5)
    system.startUser("beta", cruncher(3, 200), priority=0xF8, pages=5)
    system.startUser("editor", ioUser(3), priority=0xF8, pages=4)
    system.startUser("clock", sleeper(2), priority=0xFC, pages=4)
    outcome = system.run()
    return system, outcome


if __name__ == "__main__":
    if sys.argv[1:] == ["docs"]:
        for path in writeGeneratedDocs():
            print(path)
    else:
        system, outcome = demo()
        print(system.traceText())
        print(outcome)
