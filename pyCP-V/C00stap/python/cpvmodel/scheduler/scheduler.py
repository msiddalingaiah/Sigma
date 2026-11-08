"""The scheduler: which user runs, and what events do to users."""

from ..glossary import cpv, modelOnly
from ..user import UserState
from .eventrouter import EventRouter
from .events import PriorityBoost
from .statequeues import StateQueues


@cpv("SCHED", source="SCHED.txt:1-20",
     note="SCHED - EXECUTION AND SWAP SCHEDULER; its data is in SSDAT")
class Scheduler:
    """Decides which user runs, and moves users between states as events are reported.
    The rest of the system talks to it through its methods, never to its parts.

    Its parts:

    - ``stateQueues``, the queues users wait in;
    - ``router``, which turns event reports into state changes using the transition table.

    Later iterations add the exit path (quanta and preemption) and the swap scheduler.
    In CP-V this is really the module SCHED, with its data cells in SSDAT.
    """

    def __init__(self, system):
        self.system = system
        self.stateQueues = StateQueues()
        self.router = EventRouter(self)
        self.currentUser = None
        self.usersInSystem = 0
        self.ghostsKeptAtShutdown = 0

    cpvNames = {
        "system": modelOnly("The system the scheduler belongs to; used for the trace"),
        "stateQueues": cpv("SB:HQ", "SB:TQ", source="SSDAT.txt:390-394"),
        "router": cpv("RCE0", source="SCHED.txt:1371-1404"),
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
        with the interactive boost, so they run soon."""
        user.basePriority = priority
        user.inCore = True
        user.ioInFlight = 0
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
        """Pick the most urgent ready user and make them the current user, or return None."""
        user = self.stateQueues.firstReady()
        if user is None:
            return None
        self.router.changeState(user, UserState.RUNNING)
        if user.priority < user.basePriority:
            user.priority += 1
        self.log(user, f"dispatched at {user.priority:#04x}")
        return user

    @cpv("T:ACCTEX", "T:CHSE0", source="SCHED.txt:980-1012",
         note="CP-V ends the quantum when the time in J:DELTAT runs out")
    def endQuantum(self, user):
        """Back to the base priority, and to the tail of the band's queue."""
        self.router.makeReady(user, PriorityBoost.COMPUTE)

    @cpv("S:CUIS", "GOODNGT", "X'404'", source="SCHED.txt:1065-1084",
         note="Checked when nobody is ready; ends with SCREECH X'404'")
    def isShutDown(self):
        return self.usersInSystem - self.ghostsKeptAtShutdown <= 0

    @modelOnly("Adds a line to the system's trace")
    def log(self, user, what):
        self.system.log(user, what)
