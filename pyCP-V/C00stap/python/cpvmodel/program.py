"""What a user's program can ask for. A program is a generator that yields these."""

from dataclasses import dataclass

from .glossary import modelOnly


@modelOnly("A stand-in for user code running in slave mode until the clock-4 interrupt")
@dataclass
class Compute:
    """Run for ``ticks`` clock ticks."""
    ticks: int


@modelOnly("Stands for a wait CAL: the monitor reports E:SL, and CLOCK4 reports E:WU later")
@dataclass
class Sleep:
    """Sleep for ``ticks``, then wake up."""
    ticks: int


@modelOnly("Stands for a read or write CAL: IOQ starts the I/O (UB:MF + 1), the monitor "
           "reports E:IIP, and the device's completion reports E:IC")
@dataclass
class DoIo:
    """Start an I/O that takes ``ticks``, and wait for it."""
    ticks: int


@modelOnly("Stands for giving up the processor, as RDL's TIMSUP does (E:QE)")
@dataclass
class Yield:
    """Go to the back of the queue."""


@modelOnly("Entering the user's break routine (M:INT) after a break key")
class Break(Exception):
    """Thrown into a program when the user presses break. A program that catches it goes on;
    one that doesn't goes back to the command processor."""
