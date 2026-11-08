"""The system: the components put together, a clock, and the loop that runs users.

``System`` owns the machine-wide things: the user slots, core memory, time, the things that
will happen later, and the trace. The components do the work. So far there is one, the
``Scheduler``.

A computing user runs until their step is done, their quantum runs out, or something comes
due (an interrupt). After an interrupt the scheduler runs a swap schedule; after an interrupt
or a CAL, its exit path decides whether the user goes on.
"""

from dataclasses import dataclass

from .futureevents import FutureEvents
from .glossary import cpv, modelOnly
from .memory import Memory
from .program import (Compute, DoIo, OpenClose, OpenCloseDone, Release, Sleep, WaitFor,
                      Yield)
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

    def __init__(self, userSlots=8, settings=None, memoryPages=64):
        self.clock = 0
        self.users = [User(number) for number in range(1, userSlots + 1)]
        self.freeSlots = list(self.users)
        self.memory = Memory(memoryPages)
        self.runUntil = None
        self.scheduler = Scheduler(self, settings)
        self.futureEvents = FutureEvents()
        self.trace = []

    cpvNames = {
        "clock": modelOnly("Simulated time in ticks. CP-V counts time per user in J:DELTAT "
                           "with clock 4"),
        "users": cpv("SMUIS", source="SSDAT.txt:336-381",
                     note="The per-user tables have SMUIS entries"),
        "freeSlots": cpv("SNULL", "SB:HQ", source="SCHED.txt:317, SSDAT.txt:390-394",
                         note="The queue of the SNULL state"),
        "memory": cpv("M:FPPH", "S:PCORE", source="SCHED.txt:2255-2271, TABLES.txt:725"),
        "scheduler": cpv("SCHED", source="SCHED.txt:1-20"),
        "futureEvents": modelOnly("What the clock and devices will do later"),
        "runUntil": modelOnly("The tick limit of the current run; a compute stops there"),
        "trace": modelOnly("What happened, for tests and for reading"),
    }

    @cpv("LOGON", "ADD1", source="SCHED.txt:1869-1980",
         note="LOGON (on-line), MBS (batch) and T:GJOBSTRT (ghosts) take a slot from the "
              "SNULL queue and call ADD1")
    def startUser(self, name, program, priority, pages=4):
        """Start a user at base ``priority`` (CP-V numbering: lower is more urgent), who
        needs ``pages`` pages in core."""
        if not self.freeSlots:
            raise NoFreeSlot(name)
        user = self.freeSlots.pop(0)
        user.name = name
        user.program = program
        user.pages = pages
        self.scheduler.addUser(user, priority)
        self.log(user, "started")
        return user

    @cpv("STEP70", source="STEP.txt:117-150", note="Removal of a user from the system")
    def endUser(self, user, reason=None):
        self.futureEvents.cancelFor(user)
        self.scheduler.removeUser(user)
        if user.inCore:
            self.memory.give(user.pages)
            user.inCore = False
        user.program = None
        user.computeLeft = 0
        user.pendingRequest = None
        user.pendingSignals = set()
        self.freeSlots.append(user)
        self.log(user, f"ended: {reason}" if reason else "ended")

    @modelOnly("An event that something outside the users will report at ``time``, such as "
               "a break key")
    def reportAt(self, time, user, event, detail=None):
        self.futureEvents.schedule(time, lambda: self.scheduler.report(user, event, detail),
                                   user)

    @modelOnly("The user's code runs; in CP-V the processor simply runs the user in slave mode")
    def execute(self, user):
        """Run the current user: go on with the ``Compute`` step they're in, or take their
        next step."""
        if user.computeLeft == 0:
            request = self.nextRequest(user)
            if request is None:
                return
            if not isinstance(request, Compute):
                self.call(user, request)
                return
            user.computeLeft = request.ticks
            self.log(user, f"computes {request.ticks}")
        self.compute(user)

    @modelOnly("The program's next step, or None when the program has ended")
    def nextRequest(self, user):
        if user.pendingRequest is not None:
            request, user.pendingRequest = user.pendingRequest, None
            return request
        try:
            return next(user.program)
        except StopIteration:
            self.endUser(user)
            return None

    @modelOnly("The user computes until the step is done, the quantum is used up, or "
               "an interrupt comes")
    def compute(self, user):
        ticks = min(user.computeLeft, user.quantumLeft)
        for limit in (self.futureEvents.nextTime(), self.runUntil):
            if limit is not None:
                ticks = min(ticks, max(0, limit - self.clock))
        self.clock += ticks
        user.computeLeft -= ticks
        user.quantumLeft -= ticks
        interrupted = self.runDueEvents()
        if interrupted:
            self.scheduler.swapSchedule()
        if (interrupted or user.quantumLeft <= 0) and user is self.scheduler.currentUser:
            self.scheduler.exitToUser(user)

    @cpv("TRAPEXIT", source="SCHED.txt:877-889",
         note="A CAL enters the monitor; the user comes back through TRAPEXIT")
    def call(self, user, request):
        """A step that asks the monitor for something: sleep, I/O, giving up the processor,
        a resource, or opening and closing a file."""
        if isinstance(request, Sleep):
            self.reportAt(self.clock + request.ticks, user, Event.WAKE_UP)
            self.scheduler.report(user, Event.SLEEP)
        elif isinstance(request, DoIo):
            user.ioInFlight += 1
            self.reportAt(self.clock + request.ticks, user, Event.IO_COMPLETE)
            self.scheduler.report(user, Event.IO_STARTED)
        elif isinstance(request, Yield):
            self.scheduler.report(user, Event.YIELD)
        elif isinstance(request, WaitFor):
            self.scheduler.report(user, Event.RESOURCE_BLOCK, request.resource)
        elif isinstance(request, Release):
            self.scheduler.report(user, Event.RESOURCE_RELEASE, request.resource)
        elif isinstance(request, OpenClose):
            if self.scheduler.claimOpenClose(user):
                self.log(user, "open/close starts")
                user.computeLeft = request.ticks
                user.pendingRequest = OpenCloseDone()
            else:
                user.pendingRequest = request       # try again when released (CLS 1F1)
        elif isinstance(request, OpenCloseDone):
            self.log(user, "open/close done")
            self.scheduler.endOpenClose(user)
        else:
            raise TypeError(f"{user.name}: unknown request {request!r}")
        if user is self.scheduler.currentUser:
            self.scheduler.exitToUser(user)

    @modelOnly("Interrupts: everything due by now happens")
    def runDueEvents(self):
        count = 0
        while (due := self.futureEvents.popDue(self.clock)) is not None:
            _, action = due
            action()
            count += 1
        return count

    @modelOnly("Time passes; what comes due on the way happens at its own time")
    def advanceClock(self, ticks):
        end = self.clock + ticks
        while (due := self.futureEvents.popDue(end)) is not None:
            self.clock, action = due
            action()
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
        self.runUntil = tickLimit
        while self.clock < tickLimit:
            if self.scheduler.currentUser is not None:
                self.execute(self.scheduler.currentUser)
                continue
            if self.scheduler.dispatch() is not None:
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
