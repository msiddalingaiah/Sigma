"""The system: the components put together, a clock, and the loop that runs users.

``System`` owns the machine-wide things: the user slots, core memory, time, the things that
will happen later, and the trace. The components do the work: the ``Scheduler``, the
``TerminalController`` and the ``FileSystem``.

A computing user runs until their step is done, their quantum runs out, or something comes
due (an interrupt). After an interrupt the scheduler runs a swap schedule; after an interrupt
or a CAL, its exit path decides whether the user goes on.
"""

from dataclasses import dataclass

from .futureevents import FutureEvents
from .filesystem import FileError, FileSystem, GranuleShortage, Organization
from .glossary import cpv, modelOnly
from .memory import Memory
from .program import (Close, Compute, DoIo, Open, OpenClose, OpenCloseDone, ReadRecord,
                      ReadTerminal, Release, Sleep, WaitFor, WriteRecord, WriteTerminal, Yield)
from .scheduler import Event, Resource, Scheduler
from .terminals import TerminalController, echoSession
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

    def __init__(self, userSlots=8, settings=None, memoryPages=64, terminalLines=4,
                 terminalSettings=None, session=echoSession, fileSettings=None):
        self.clock = 0
        self.users = [User(number) for number in range(1, userSlots + 1)]
        self.freeSlots = list(self.users)
        self.memory = Memory(memoryPages)
        self.runUntil = None
        self.scheduler = Scheduler(self, settings)
        self.terminals = TerminalController(self, terminalLines, terminalSettings, session)
        self.files = FileSystem(self, fileSettings)
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
        "terminals": cpv("COC", "T:RCE", source="SCHED.txt:1846-1868"),
        "files": cpv("OPNFIL", "CLSFIL", source="OPNF.txt:115, CLS.txt:1443"),
        "futureEvents": modelOnly("What the clock and devices will do later"),
        "runUntil": modelOnly("The tick limit of the current run; a compute stops there"),
        "trace": modelOnly("What happened, for tests and for reading"),
    }

    @cpv("LOGON", "ADD1", source="SCHED.txt:1869-1980",
         note="LOGON (on-line), MBS (batch) and T:GJOBSTRT (ghosts) take a slot from the "
              "SNULL queue and call ADD1")
    def startUser(self, name, program, priority, pages=4, account="GUEST"):
        """Start a user at base ``priority`` (CP-V numbering: lower is more urgent), who
        needs ``pages`` pages in core."""
        if not self.freeSlots:
            raise NoFreeSlot(name)
        user = self.freeSlots.pop(0)
        user.name = name
        user.program = program
        user.pages = pages
        user.account = account
        self.scheduler.addUser(user, priority)
        self.log(user, "started")
        return user

    @cpv("STEP70", source="STEP.txt:117-150", note="Removal of a user from the system")
    def endUser(self, user, reason=None):
        self.futureEvents.cancelFor(user)
        self.scheduler.removeUser(user)
        self.terminals.userEnded(user)
        self.files.closeAll(user)
        if user.inCore:
            self.memory.give(user.pages)
            user.inCore = False
        user.program = None
        user.computeLeft = 0
        user.pendingRequest = None
        user.stepResult = None
        user.stepError = None
        user.inputArrivedEarly = False
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
            if user.stepError is not None:
                error, user.stepError = user.stepError, None
                return user.program.throw(error)
            if user.stepResult is not None:
                (value,), user.stepResult = user.stepResult, None
                return user.program.send(value)
            return next(user.program)
        except StopIteration:
            self.endUser(user)
            return None
        except FileError as error:
            self.endUser(user, f"file error {error}")
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
        a resource, opening and closing a file, or the terminal."""
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
        elif isinstance(request, ReadTerminal):
            text = self.terminals.read(user)
            if text is None:
                user.pendingRequest = request       # read again after the wait (COCRD)
            else:
                user.stepResult = (text,)
        elif isinstance(request, WriteTerminal):
            if not self.terminals.write(user, request.text):
                user.pendingRequest = request       # write after the output drains
        elif isinstance(request, (Open, Close)):
            self.openOrClose(user, request)
        elif isinstance(request, ReadRecord):
            self.fileStep(user, request,
                          lambda: self.files.readRecord(request.handle, request.key))
        elif isinstance(request, WriteRecord):
            self.fileStep(user, request,
                          lambda: self.files.writeRecord(request.handle, request.text,
                                                         request.key))
        elif isinstance(request, OpenCloseDone):
            self.log(user, "open/close done")
            self.scheduler.endOpenClose(user)
        else:
            raise TypeError(f"{user.name}: unknown request {request!r}")
        if user is self.scheduler.currentUser:
            self.scheduler.exitToUser(user)

    @cpv("OPNCLSUS", "E:OCR", source="OPNF.txt:1479-1487",
         note="OPEN and CLOSE run as the open/close user, one user at a time")
    def openOrClose(self, user, request):
        """Open or close a file under the open/close lock: wait for the lock, do it, wait
        for the disc, give up the lock."""
        if not self.scheduler.claimOpenClose(user):
            user.pendingRequest = request           # try again when released
            return
        try:
            if isinstance(request, Open):
                accesses = self.fileWork(
                    user, lambda: self.files.openFile(user, request.name, request.mode,
                                                      request.account,
                                                      request.organization
                                                      or Organization.CONSECUTIVE))
                handle = user.stepResult[0] if user.stepResult is not None else None
            else:
                accesses = self.fileWork(user, lambda: self.files.closeFile(request.handle))
                handle = request.handle
        except GranuleShortage:
            self.scheduler.endOpenClose(user)
            self.waitForGranules(user, request)
            return
        if handle is not None:
            accesses += handle.takeDiscAccesses()
            verb = "opens" if isinstance(request, Open) else "closes"
            self.log(user, f"{verb} {handle.file.header.name} {handle.mode.name}")
        user.pendingRequest = OpenCloseDone()
        self.waitForDisc(user, accesses)

    @modelOnly("A file read or write: do it, then wait for the disc")
    def fileStep(self, user, request, work):
        try:
            accesses = self.fileWork(user, work)
        except GranuleShortage:
            self.waitForGranules(user, request)
            return
        self.waitForDisc(user, accesses + request.handle.takeDiscAccesses())

    @cpv("E:QFAC", "REGUSER", source="GRAN.txt:301-308",
         note="Blocked on ALLOCATOR until ALLOCAT's fill is committed; then the step again")
    def waitForGranules(self, user, request):
        user.pendingRequest = request
        self.log(user, "waits for granules")
        self.scheduler.report(user, Event.RESOURCE_BLOCK, Resource.ALLOCATOR)

    @modelOnly("Runs a file operation: its result goes back to the program, or its error is "
               "thrown in. A failed lookup still read two directories")
    def fileWork(self, user, work):
        try:
            user.stepResult = (work(),)
            return 0
        except FileError as error:
            user.stepError = error
            return 2

    @cpv("E:IIP", "UB:MF", source="SCHED.txt:513, SCHED.txt:1553-1572",
         note="The file code queues its disc I/O and the user waits (T:IOREG, E:IIP)")
    def waitForDisc(self, user, accesses):
        ticks = accesses * self.files.settings.discTime
        if ticks == 0:
            return
        user.ioInFlight += 1
        self.reportAt(self.clock + ticks, user, Event.IO_COMPLETE)
        self.scheduler.report(user, Event.IO_STARTED)

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
