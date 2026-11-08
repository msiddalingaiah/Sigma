"""The system: the components put together, a clock, and the loop that runs users.

``System`` is the machine: the user slots, core memory, time, the things that will happen
later, the users' threads, and the trace. The components do the work: the ``Scheduler``, the
``IoSystem``, the ``TerminalController`` and the ``FileSystem``. Programs reach them through
the ``Monitor``'s CALs.

The run loop is CP-V's interrupt level and execution scheduler: it dispatches a user, runs
their thread until it computes or hands back from a CAL, runs their computing in slices that
the quantum and interrupts may cut, and makes everything due happen at its time.
"""

import threading
from dataclasses import dataclass

from .filesystem import FileError, FileSystem
from .futureevents import FutureEvents
from .glossary import cpv, modelOnly
from .iosystem import IoSystem
from .memory import Memory
from .monitor import Monitor
from .program import Break
from .scheduler import Scheduler
from .terminals import EchoSession, TerminalController
from .user import User
from .usercontext import UserContext, UserEnded


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


@modelOnly("The machine; CP-V has no single counterpart")
class System:
    """A CP-V system reduced to its components, its users and time."""

    def __init__(self, userSlots=8, settings=None, memoryPages=64, terminalLines=4,
                 terminalSettings=None, session=EchoSession, fileSettings=None):
        self.clock = 0
        self.users = [User(number) for number in range(1, userSlots + 1)]
        self.freeSlots = list(self.users)
        self.memory = Memory(memoryPages)
        self.runUntil = None
        self.loopTurn = threading.Semaphore(0)
        self.contexts = {}
        self.futureEvents = FutureEvents()
        self.trace = []
        self.scheduler = Scheduler(self, settings)
        self.io = IoSystem(self)
        self.terminals = TerminalController(self, terminalLines, terminalSettings, session)
        self.files = FileSystem(self, fileSettings)

    cpvNames = {
        "clock": modelOnly("Simulated time in ticks. CP-V counts time per user in J:DELTAT "
                           "with clock 4"),
        "users": cpv("SMUIS", source="SSDAT.txt:336-381",
                     note="The per-user tables have SMUIS entries"),
        "freeSlots": cpv("SNULL", "SB:HQ", source="SCHED.txt:317, SSDAT.txt:390-394",
                         note="The queue of the SNULL state"),
        "memory": cpv("M:FPPH", "S:PCORE", source="SCHED.txt:2255-2271, TABLES.txt:725"),
        "runUntil": modelOnly("The tick limit of the current run; a compute stops there"),
        "loopTurn": modelOnly("The loop waits on this while a user's thread runs"),
        "contexts": cpv("J:JIT", source="JIT.txt:304",
                        note="Each user's thread, where they wait while they don't run"),
        "futureEvents": modelOnly("What the clock and devices will do later"),
        "trace": modelOnly("What happened, for tests and for reading"),
        "scheduler": cpv("SCHED", source="SCHED.txt:1-20"),
        "io": cpv("IOQ", source="IOQ.txt:1"),
        "terminals": cpv("COC", "T:RCE", source="SCHED.txt:1846-1868"),
        "files": cpv("OPNFIL", "CLSFIL", source="OPNF.txt:115, CLS.txt:1443"),
    }

    # --- Users ----------------------------------------------------------------------------

    @cpv("LOGON", "ADD1", source="SCHED.txt:1869-1980",
         note="LOGON (on-line), MBS (batch) and T:GJOBSTRT (ghosts) take a slot from the "
              "SNULL queue and call ADD1")
    def startUser(self, name, program, priority, pages=4, account="GUEST", privilege=0):
        """Start a user running ``program`` (a ``Program``) at base ``priority`` (CP-V
        numbering: lower is more urgent), needing ``pages`` pages in core."""
        if not self.freeSlots:
            raise NoFreeSlot(name)
        user = self.freeSlots.pop(0)
        user.name = name
        user.program = program
        user.pages = pages
        user.account = account
        user.privilege = privilege
        self.contexts[user] = UserContext(self, user, program)
        self.scheduler.addUser(user, priority)
        self.log(user, "started")
        return user

    @modelOnly("The CALs for a user's program")
    def monitorFor(self, context):
        return Monitor(self, context.user, context)

    @cpv("STEP70", source="STEP.txt:117-150", note="Removal of a user from the system")
    def endUser(self, user, reason=None):
        context = self.contexts.pop(user, None)
        if context is not None and not context.finished:
            context.throw(UserEnded())              # unwind the program's thread
            context.resume()
        self.futureEvents.cancelFor(user)
        self.scheduler.removeUser(user)
        self.terminals.userEnded(user)
        self.files.closeAll(user)
        if user.inCore:
            self.memory.give(user.pages)
            user.inCore = False
        user.program = None
        user.computeLeft = 0
        user.inputArrivedEarly = False
        user.pendingSignals = set()
        self.freeSlots.append(user)
        self.log(user, f"ended: {reason}" if reason else "ended")

    @modelOnly("Raise ``error`` in the user's program when it next runs (a break)")
    def throwInto(self, user, error):
        self.contexts[user].throw(error)

    @modelOnly("Unwind every user's thread still waiting, at the end of a test or a demo")
    def shutdown(self):
        for user in list(self.contexts):
            self.endUser(user, "shut down")

    @modelOnly("An event that something outside the users will report at ``time``, such as "
               "a break key")
    def reportAt(self, time, user, event, detail=None):
        self.futureEvents.schedule(time, lambda: self.scheduler.report(user, event, detail),
                                   user)

    # --- The run loop ---------------------------------------------------------------------

    @cpv("T:PULLE", source="SCHED.txt:2069-2084",
         note="Back to the user: they go on computing, or their thread runs")
    def execute(self, user):
        """Run the current user: go on with their computing, or resume their thread until
        it computes, hands back from a CAL, or ends."""
        if user.computeLeft > 0:
            self.compute(user)
            return
        context = self.contexts[user]
        context.resume()
        if context.finished:
            self.finish(user, context)
            return
        kind, ticks = context.request
        if kind == "compute":
            user.computeLeft = ticks
            self.log(user, f"computes {ticks}")
            self.compute(user)
        elif user is self.scheduler.currentUser:
            self.scheduler.exitToUser(user)

    @modelOnly("The program has ended: the user ends, and a failure in the program is "
               "raised from the run")
    def finish(self, user, context):
        error = context.outcome
        if error is None:
            self.endUser(user)
        elif isinstance(error, Break):
            self.endUser(user, "break with no break routine: back to the command processor")
        elif isinstance(error, FileError):
            self.endUser(user, f"file error {error}")
        else:
            self.endUser(user, f"failed: {error!r}")
            raise error

    @modelOnly("The user computes until their computing is done, the quantum is used up, or "
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
        ``tickLimit``. Returns "shutdown", "stuck" or "tickLimit".

        CP-V shuts down in its idle loop as soon as the users in the system (less GOODNGT)
        reach 0. Its system ghosts keep that count above 0 until a ZAP. The model has no
        ghosts, so it also waits for anything still to come, such as a log-on."""
        self.runUntil = tickLimit
        while self.clock < tickLimit:
            if self.scheduler.currentUser is not None:
                self.execute(self.scheduler.currentUser)
                continue
            if self.scheduler.dispatch() is not None:
                continue
            nextTime = self.futureEvents.nextTime()
            if nextTime is None:
                return "shutdown" if self.scheduler.isShutDown() else "stuck"
            self.idleUntil(min(nextTime, tickLimit))
        return "tickLimit"

    @modelOnly("Adds a line to the trace")
    def log(self, user, what):
        self.trace.append(TraceEntry(self.clock, user.name if user else "-", what))

    @modelOnly("The trace as text")
    def traceText(self):
        return "\n".join(map(str, self.trace))
