"""A user's program: a class whose ``run`` makes CALs on the Monitor."""

from .glossary import modelOnly


@modelOnly("A user's program; in CP-V a load module the user runs")
class Program:
    """A user's program. A subclass writes ``run(self, m)``: ``m`` is the ``Monitor``, whose
    methods are the CALs, so CP-V's ``M:READ`` is ``m.read(dcb)``. A program declares its DCBs
    as attributes. Computing isn't a CAL; it is the program's own ``self.compute(ticks)``.

    The program runs in its user's thread, which the system suspends and resumes: in a CAL
    that waits, while computing, and when the user is preempted or swapped out. The program
    doesn't see any of that; a CAL just returns when it is done.
    """

    context = None

    @modelOnly("The program; it ends when this returns")
    def run(self, m):
        raise NotImplementedError

    @modelOnly("The program's own work: run for ``ticks``. The clock, the quantum and "
               "interrupts may cut it into slices; the program doesn't notice")
    def compute(self, ticks):
        self.context.computeFor(ticks)


@modelOnly("Entering the user's break routine (M:INT) after a break key")
class Break(Exception):
    """Raised in a program when the user presses break. A program that catches it goes on;
    one that doesn't goes back to the command processor."""
