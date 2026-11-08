"""The scheduler: which user runs, and what events do to users."""

from ..glossary import cpv, modelOnly
from ..user import UserState
from .eventrouter import EventRouter
from .events import Event, PriorityBoost
from .exitpath import ExitPath
from .resources import Resource, ResourceManager
from .settings import SchedulerSettings
from .statequeues import StateQueues
from .swapscheduler import SwapScheduler


@cpv("SCHED", source="SCHED.txt:1-20",
     note="SCHED - EXECUTION AND SWAP SCHEDULER; its data is in SSDAT")
class Scheduler:
    """Decides which user runs, and moves users between states as events are reported.
    The rest of the system talks to it through its methods, never to its parts.

    Its parts:

    - ``stateQueues``, the queues users wait in;
    - ``router``, which turns event reports into state changes using the transition table;
    - ``exitPath``, which checks signals, quantum end and preemption on the way back to a
      user;
    - ``swapScheduler``, which decides who is in core;
    - ``resources``, the users blocked on resources.
    In CP-V this is really the module SCHED, with its data cells in SSDAT.
    """

    def __init__(self, system, settings=None):
        self.system = system
        self.settings = settings or SchedulerSettings()
        self.stateQueues = StateQueues()
        self.router = EventRouter(self)
        self.exitPath = ExitPath(self)
        self.swapScheduler = SwapScheduler(self)
        self.resources = ResourceManager(self)
        self.currentUser = None
        self.usersInSystem = 0
        self.ghostsKeptAtShutdown = 0

    cpvNames = {
        "system": modelOnly("The system the scheduler belongs to; used for the trace"),
        "settings": cpv("SL:QUAN", "SL:QMIN", source="CONMAIN.txt:1037-1047"),
        "stateQueues": cpv("SB:HQ", "SB:TQ", source="SSDAT.txt:390-394"),
        "router": cpv("RCE0", source="SCHED.txt:1371-1404"),
        "exitPath": cpv("SSE0", source="SCHED.txt:889"),
        "swapScheduler": cpv("T:SS", source="SCHED.txt:2109"),
        "resources": cpv("T:RES", "T:REL", source="SCHED.txt:1755-1771"),
        "currentUser": cpv("S:CUN", source="TCATCH.txt:173"),
        "usersInSystem": cpv("S:CUIS", source="SSDAT.txt:51"),
        "ghostsKeptAtShutdown": cpv("GOODNGT", source="SCHED.txt:1065-1084",
                                    note="CP-V stores the negative: ZAP sets GOODNGT to -2"),
    }

    @cpv("T:RUE", "T:RE", "RCE0", source="SCHED.txt:1360-1404",
         note="T:RUE reports for any user, T:RE for the current one")
    def report(self, user, event, detail=None):
        """Report ``event`` for ``user``."""
        self.router.report(user, event, detail)

    @cpv("ADD1", "S:CUIS", "UB:PRIOB", source="SCHED.txt:1922-1980",
         note="The JIT granule, flags and page count aren't modelled yet")
    def addUser(self, user, priority):
        """Take a user into the system at base ``priority``. Like every new user, they start
        with the interactive boost, so they run soon. They start out of core: the swap
        scheduler brings them in."""
        user.basePriority = priority
        user.inCore = False
        user.justSwappedIn = False
        user.swapQuantumPending = False
        user.ioInFlight = 0
        user.quantumLeft = self.settings.quantum
        user.pendingSignals = set()
        self.usersInSystem += 1
        self.router.makeReady(user, PriorityBoost.INTERACTIVE)

    @cpv("STEP70", "S:CUIS", "SNULL", source="STEP.txt:117-150",
         note="In CP-V this is in STEP, which also frees the JIT page and processor counts")
    def removeUser(self, user):
        self.router.changeState(user, UserState.FREE_SLOT)
        self.usersInSystem -= 1

    @cpv("T:SE", "SE1", "S:CUN", "S:PRIODEC", source="SCHED.txt:1021-1209",
         note="Also does a swap schedule first, and loads the map and access locks")
    def dispatch(self):
        """Pick the most urgent ready user and make them the current user, or return None.
        A user with signals pending goes through the exit path at once, so they may not
        be the current user afterwards."""
        self.swapSchedule()
        user = self.stateQueues.firstReady()
        if user is None:
            return None
        self.router.changeState(user, UserState.RUNNING)
        if user.priority < user.basePriority:
            user.priority += 1
        if user.justSwappedIn:
            user.justSwappedIn = False
            user.quantumLeft = self.settings.quantum
        user.dispatchedAt = self.system.clock
        self.log(user, f"dispatched at {user.priority:#04x}")
        if user.pendingSignals:
            self.exitPath.check(user)
        return user

    @cpv("T:SS", source="SCHED.txt:2109-2116",
         note="T:SE calls it first; interrupts call it on the way out (T:SSE)")
    def swapSchedule(self):
        """Start a swap if one is needed and none is going."""
        self.swapScheduler.schedule()

    @cpv("SSE0", "TRAPEXIT", "T:SSE", source="SCHED.txt:862-892",
         note="Interrupts go in at T:SSE, CALs at TRAPEXIT")
    def exitToUser(self, user):
        """On the way back to the current user after an interrupt or a CAL: the exit path
        decides whether they go on running."""
        self.exitPath.check(user)

    @cpv("S:HIR", "S:CUP", source="SCHED.txt:1452-1466, SSDAT.txt:45",
         note="CP-V keeps a count, S:HIR, raised when a user more urgent than S:CUP becomes "
              "ready and lowered at each dispatch; the model just looks")
    def moreUrgentUserWaiting(self, user):
        waiting = self.stateQueues.firstReady()
        return waiting is not None and waiting.isMoreUrgentThan(user)

    @cpv("CHSE0", source="SCHED.txt:1459-1466")
    def requeue(self, user):
        """Back in the queue at the current priority (a preempted user)."""
        self.router.requeue(user)

    @cpv("T:ACCTEX", "T:CHSE0", source="SCHED.txt:980-1012",
         note="CP-V ends the quantum when the time in J:DELTAT runs out")
    def endQuantum(self, user):
        """A new quantum, back to the base priority, and to the tail of the band's queue."""
        user.quantumLeft = self.settings.quantum
        self.router.makeReady(user, PriorityBoost.COMPUTE)

    @cpv("OPNCLSUS", "E:OCR", source="CLS.txt:1068-1085",
         note="In CP-V this is in CLS, OPNF and FIX1, not SCHED: wait with E:OCR until "
              "nobody else is the open/close user")
    def claimOpenClose(self, user):
        """Become the open/close user, or block until released. Returns True if claimed."""
        holder = self.resources.openCloseUser
        if holder is None or holder is user:
            self.resources.openCloseUser = user
            return True
        self.report(user, Event.RESOURCE_BLOCK, Resource.OPEN_CLOSE)
        return False

    @cpv("OPNCLSUS", "E:NOCR", "R:OCR", source="IORT.txt:1050-1062",
         note="Clear OPNCLSUS and, if anyone waits, report E:NOCR (OPNUNBLOCK picks one)")
    def endOpenClose(self, user):
        self.resources.openCloseUser = None
        if self.resources.queues[Resource.OPEN_CLOSE]:
            self.report(user, Event.RESOURCE_RELEASE, Resource.OPEN_CLOSE)

    @cpv("S:CUIS", "GOODNGT", "X'404'", source="SCHED.txt:1065-1084",
         note="Checked when nobody is ready; ends with SCREECH X'404'")
    def isShutDown(self):
        return self.usersInSystem - self.ghostsKeptAtShutdown <= 0

    @modelOnly("Adds a line to the system's trace")
    def log(self, user, what):
        self.system.log(user, what)
