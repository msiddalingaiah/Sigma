"""The system: user slots, the state queues, a clock, and the loop that runs users.

Users compute, sleep, do I/O and yield. Sleeping and I/O go through event reports and the
transition table (``EventRouter``). Still shallow: each ``Compute`` step is one whole quantum,
and nobody is preempted or swapped. Events that come due while a user computes are reported
at their own time, but the running user isn't interrupted.
"""

from dataclasses import dataclass

from .eventrouter import EventRouter
from .events import Event, PriorityBoost
from .futureevents import FutureEvents
from .glossary import cpv, modelOnly
from .program import Compute, DoIo, Sleep, Yield
from .statequeues import StateQueues
from .user import User, UserState


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
    """A CP-V system reduced to scheduling: users, their queues, events, and time."""

    def __init__(self, userSlots=8):
        self.clock = 0
        self.users = [User(number) for number in range(1, userSlots + 1)]
        self.freeSlots = list(self.users)
        self.stateQueues = StateQueues()
        self.router = EventRouter(self)
        self.futureEvents = FutureEvents()
        self.currentUser = None
        self.usersInSystem = 0
        self.ghostsKeptAtShutdown = 0
        self.trace = []

    cpvNames = {
        "clock": modelOnly("Simulated time in ticks. CP-V counts time per user in J:DELTAT "
                           "with clock 4"),
        "users": cpv("SMUIS", source="SSDAT.txt:336-381",
                     note="The per-user tables have SMUIS entries"),
        "freeSlots": cpv("SNULL", "SB:HQ", source="SCHED.txt:317, SSDAT.txt:390-394",
                         note="The queue of the SNULL state"),
        "stateQueues": cpv("SB:HQ", "SB:TQ", source="SSDAT.txt:390-394"),
        "router": cpv("RCE0", source="SCHED.txt:1371-1404"),
        "futureEvents": modelOnly("Reports that the clock and devices will make later"),
        "currentUser": cpv("S:CUN", source="TCATCH.txt:173"),
        "usersInSystem": cpv("S:CUIS", source="SSDAT.txt:51"),
        "ghostsKeptAtShutdown": cpv("GOODNGT", source="SCHED.txt:1065-1084",
                                    note="CP-V stores the negative: ZAP sets GOODNGT to -2"),
        "trace": modelOnly("What happened, for tests and for reading"),
    }

    @cpv("ADD1", "S:CUIS", "UB:PRIOB", source="SCHED.txt:1922-1980",
         note="Also takes the head of the SNULL queue (LOGON, MBS). The JIT granule, "
              "flags and page count aren't modelled yet")
    def startUser(self, name, program, priority):
        """Start a user at base ``priority`` (CP-V numbering: lower is more urgent). Like
        every new user, they start with the interactive boost, so they run soon."""
        if not self.freeSlots:
            raise NoFreeSlot(name)
        user = self.freeSlots.pop(0)
        user.name = name
        user.program = program
        user.basePriority = priority
        user.inCore = True
        user.ioInFlight = 0
        self.usersInSystem += 1
        self.router.makeReady(user, PriorityBoost.INTERACTIVE)
        self.log(user, "started")
        return user

    @cpv("T:SE", "SE1", "S:CUN", "S:PRIODEC", source="SCHED.txt:1021-1209",
         note="Also does a swap schedule first, and loads the map and access locks")
    def dispatch(self):
        """Pick the most urgent ready user and make them the current user, or return None."""
        user = self.stateQueues.firstReady()
        if user is None:
            return None
        self.router.changeState(user, UserState.RUNNING)
        if user.priority < user.basePriority:
            user.priority += 1
        self.log(user, f"dispatched at {user.priority:#04x}")
        return user

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
            if user.state is UserState.RUNNING:
                self.endQuantum(user)
        elif isinstance(request, Sleep):
            self.futureEvents.schedule(self.clock + request.ticks, user, Event.WAKE_UP)
            self.router.report(user, Event.SLEEP)
        elif isinstance(request, DoIo):
            user.ioInFlight += 1
            self.futureEvents.schedule(self.clock + request.ticks, user, Event.IO_COMPLETE)
            self.router.report(user, Event.IO_STARTED)
        elif isinstance(request, Yield):
            self.router.report(user, Event.YIELD)
        else:
            raise TypeError(f"{user.name}: unknown request {request!r}")

    @cpv("T:ACCTEX", "T:CHSE0", source="SCHED.txt:980-1012",
         note="CP-V ends the quantum when the time in J:DELTAT runs out")
    def endQuantum(self, user):
        """Back to the base priority, and to the tail of the band's queue."""
        self.router.makeReady(user, PriorityBoost.COMPUTE)

    @cpv("STEP70", "S:CUIS", "SNULL", source="STEP.txt:117-150",
         note="Also frees the JIT page and processor counts")
    def endUser(self, user):
        self.router.changeState(user, UserState.FREE_SLOT)
        user.program = None
        self.usersInSystem -= 1
        self.freeSlots.append(user)
        self.log(user, "ended")

    @cpv("S:CUIS", "GOODNGT", "X'404'", source="SCHED.txt:1065-1084",
         note="Checked when nobody is ready; ends with SCREECH X'404'")
    def isShutDown(self):
        return self.usersInSystem - self.ghostsKeptAtShutdown <= 0

    @modelOnly("Time passes; reports that come due on the way are made at their own time")
    def advanceClock(self, ticks):
        end = self.clock + ticks
        while (due := self.futureEvents.popDue(end)) is not None:
            self.clock, user, event = due
            self.router.report(user, event)
        self.clock = end

    @cpv("C:IDLE", "WAIT", source="SCHED.txt:1085-1126",
         note="CP-V waits for an interrupt, then tries T:SE again")
    def idleUntil(self, time):
        self.log(None, "idle")
        self.advanceClock(time - self.clock)

    @modelOnly("The simulation loop: dispatch, execute, repeat")
    def run(self, tickLimit=100_000):
        """Run until the system shuts down, nothing more can happen, or the clock reaches
        ``tickLimit``. Returns "shutdown", "stuck" or "tickLimit"."""
        while self.clock < tickLimit:
            user = self.currentUser or self.dispatch()
            if user is not None:
                self.execute(user)
                continue
            if self.isShutDown():
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
