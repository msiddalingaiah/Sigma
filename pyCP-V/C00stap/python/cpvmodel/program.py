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


@modelOnly("Stands for a CAL that reports a resource's block event through T:REG")
@dataclass
class WaitFor:
    """Block until ``resource`` (a scheduler ``Resource``) is released."""
    resource: object


@modelOnly("Stands for monitor code that reports a resource's release event (T:RE)")
@dataclass
class Release:
    """Report that ``resource`` is available again."""
    resource: object


@modelOnly("Stands for the open/close part of an M:OPEN or M:CLOSE (CLS, OPNF)")
@dataclass
class OpenClose:
    """Open or close a file: ``ticks`` of work that only one user at a time may do."""
    ticks: int


@modelOnly("The end of an OpenClose: give up being the open/close user")
@dataclass
class OpenCloseDone:
    pass


@modelOnly("Stands for an M:READ on the terminal (M:UC), which COC's COCRD does")
@dataclass
class ReadTerminal:
    """Read a line from the user's terminal. The line is sent back into the program:
    ``text = yield ReadTerminal()``."""


@modelOnly("Stands for an M:WRITE on the terminal, which COC's COCWR does")
@dataclass
class WriteTerminal:
    """Write ``text`` to the user's terminal."""
    text: str
