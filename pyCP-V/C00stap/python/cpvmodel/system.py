"""The system: the components put together, a clock, and the loop that runs users.

``System`` owns the machine-wide things: the user slots, time, the events that will happen
later, and the trace. The components do the work. So far there is one, the ``Scheduler``.

Still shallow: each ``Compute`` step is one whole quantum, and nobody is preempted or swapped.
Events that come due while a user computes are reported at their own time, but the running
user isn't interrupted.
"""

from dataclasses import dataclass

from .futureevents import FutureEvents
from .glossary import cpv, modelOnly
from .program import Compute, DoIo, Sleep, Yield
from .scheduler import Event, Scheduler
from .user import User


@modelOnly("CP-V's LOGON just does nothing when no slot is free")
class NoFreeSlot(Exception):
    """Every user slot is in use."""


@modelOnly("One line of a run's trace")
@dataclass(frozen=True)
class TraceEntry:
    time: int
    user: str
    what: str

    def __str__(self):
        return f"{self.time:6d}  {self.user:<10} {self.what}"


@modelOnly("The monitor as a whole; CP-V has no single counterpart")
class System:
    """A CP-V system reduced to its components, users and time."""

    def __init__(self, userSlots=8):
        self.clock = 0
        self.users = [User(number) for number in range(1, userSlots + 1)]
        self.freeSlots = list(self.users)
        self.scheduler = Scheduler(self)
        self.futureEvents = FutureEvents()
        self.trace = []

    cpvNames = {
        "clock": modelOnly("Simulated time in ticks. CP-V counts time per user in J:DELTAT "
                           "with clock 4"),
        "users": cpv("SMUIS", source="SSDAT.txt:336-381",
                     note="The per-user tables have SMUIS entries"),
        "freeSlots": cpv("SNULL", "SB:HQ", source="SCHED.txt:317, SSDAT.txt:390-394",
                         note="The queue of the SNULL state"),
        "scheduler": cpv("SCHED", source="SCHED.txt:1-20"),
        "futureEvents": modelOnly("Reports that the clock and devices will make later"),
        "trace": modelOnly("What happened, for tests and for reading"),
    }

    @cpv("LOGON", "ADD1", source="SCHED.txt:1869-1980",
         note="LOGON (on-line), MBS (batch) and T:GJOBSTRT (ghosts) take a slot from the "
              "SNULL queue and call ADD1")
    def startUser(self, name, program, priority):
        """Start a user at base ``priority`` (CP-V numbering: lower is more urgent)."""
        if not self.freeSlots:
            raise NoFreeSlot(name)
        user = self.freeSlots.pop(0)
        user.name = name
        user.program = program
        self.scheduler.addUser(user, priority)
        self.log(user, "started")
        return user

    @cpv("STEP70", source="STEP.txt:117-150", note="Removal of a user from the system")
    def endUser(self, user):
        self.scheduler.removeUser(user)
        user.program = None
        self.freeSlots.append(user)
        self.log(user, "ended")

    @modelOnly("The user's code runs; in CP-V the processor simply runs the user in slave mode")
    def execute(self, user):
        """Run the current user's next program step."""
        try:
            request = next(user.program)
        except StopIteration:
            self.endUser(user)
            return
        if isinstance(request, Compute):
            self.log(user, f"computes {request.ticks}")
            self.advanceClock(request.ticks)
            if user is self.scheduler.currentUser:
                self.scheduler.endQuantum(user)
        elif isinstance(request, Sleep):
            self.futureEvents.schedule(self.clock + request.ticks, user, Event.WAKE_UP)
            self.scheduler.report(user, Event.SLEEP)
        elif isinstance(request, DoIo):
            user.ioInFlight += 1
            self.futureEvents.schedule(self.clock + request.ticks, user, Event.IO_COMPLETE)
            self.scheduler.report(user, Event.IO_STARTED)
        elif isinstance(request, Yield):
            self.scheduler.report(user, Event.YIELD)
        else:
            raise TypeError(f"{user.name}: unknown request {request!r}")

    @modelOnly("Time passes; reports that come due on the way are made at their own time")
    def advanceClock(self, ticks):
        end = self.clock + ticks
        while (due := self.futureEvents.popDue(end)) is not None:
            self.clock, user, event = due
            self.scheduler.report(user, event)
        self.clock = end

    @cpv("C:IDLE", "WAIT", source="SCHED.txt:1085-1126",
         note="T:SE's idle loop: CP-V waits for an interrupt, then tries T:SE again")
    def idleUntil(self, time):
        self.log(None, "idle")
        self.advanceClock(time - self.clock)

    @modelOnly("The simulation loop: dispatch, execute, repeat")
    def run(self, tickLimit=100_000):
        """Run until the system shuts down, nothing more can happen, or the clock reaches
        ``tickLimit``. Returns "shutdown", "stuck" or "tickLimit"."""
        while self.clock < tickLimit:
            user = self.scheduler.currentUser or self.scheduler.dispatch()
            if user is not None:
                self.execute(user)
                continue
            if self.scheduler.isShutDown():
                return "shutdown"
            nextTime = self.futureEvents.nextTime()
            if nextTime is None:
                return "stuck"
            self.idleUntil(min(nextTime, tickLimit))
        return "tickLimit"

    @modelOnly("Adds a line to the trace")
    def log(self, user, what):
        self.trace.append(TraceEntry(self.clock, user.name if user else "-", what))

    @modelOnly("The trace as text")
    def traceText(self):
        return "\n".join(map(str, self.trace))
