"""Resources: users block when something they need is short, and are released when it comes."""

import enum
from dataclasses import dataclass

from ..glossary import cpv, modelOnly
from ..user import UserState
from .events import PriorityBoost
from .exitpath import Signal


class Resource(enum.Enum):
    """Something users can block on."""
    SYMBIONT_FILE_SLOT = enum.auto()
    SYMBIONT_DISC_SPACE = enum.auto()
    OPEN_CLOSE = enum.auto()
    TERMINAL_BUFFER = enum.auto()
    DISC_PAGE = enum.auto()
    ALLOCATOR = enum.auto()
    ENQUEUE = enum.auto()


cpv("RESOURCE", "SH:RFLG", source="SCHED.txt:454-466",
    note="Each RESOURCE call defines a block and a release event; the index is "
         "(event - E:REL)/2")(Resource)

Resource.cpvNames = {
    "SYMBIONT_FILE_SLOT": cpv("R:SYMF", "E:NSYMF", source="SCHED.txt:670, COOP.txt:1309",
                              note="No symbiont file slot (COOP); released by COOP, RBBAT"),
    "SYMBIONT_DISC_SPACE": cpv("R:SYMD", "E:NSYMD", source="SCHED.txt:671, COOP.txt:933",
                               note="No granule to open a COOP file; released by CLOCK4"),
    "OPEN_CLOSE": cpv("R:OCR", "E:OCR", source="SCHED.txt:672, CLS.txt:1068-1078",
                      note="Only one user at a time opens or closes files (OPNCLSUS)"),
    "TERMINAL_BUFFER": cpv("R:CBA", "E:CFB", source="SCHED.txt:673, COC.txt:3127-3129",
                           note="No COC buffer; released when buffers are free"),
    "DISC_PAGE": cpv("E:ND", "E:DPA", source="SCHED.txt:674, MM.txt:718",
                     note="No disc page (MM); also log-on with no JIT granule"),
    "ALLOCATOR": cpv("E:QFAC", "UQFAC", source="SCHED.txt:675, GRAN.txt:308",
                     note="Queued for ALLOCAT (GRAN); released by the swapper"),
    "ENQUEUE": cpv("R:NQW", "E:NQW", source="SCHED.txt:676, ENQUE.txt:352",
                   note="Waiting in ENQ; a specific user is resumed (ENQO)"),
}


@cpv("SH:RFLG", "FLUSH", "SPECIFIC", source="SCHED.txt:472-482",
     note="A halfword per resource: the release routine's index and the flags")
@dataclass(frozen=True)
class ResourceKind:
    """How a resource is released."""
    flush: bool = False
    specific: bool = False
    actOnEmpty: bool = False
    wakingSignals: frozenset = frozenset()
    releaseRoutine: str = None

    cpvNames = {
        "flush": cpv("FLUSH", source="SCHED.txt:481", note="Release everyone waiting"),
        "specific": cpv("SPECIFIC", source="SCHED.txt:480",
                        note="Release only the user the release is reported for"),
        "actOnEmpty": cpv("NULL", source="SCHED.txt:482",
                          note="Run the release routine even when nobody waits"),
        "wakingSignals": cpv("ERR", "ABRT", "EC", "BRK", source="SCHED.txt:476-479",
                             note="Signals that take a user out of the queue (SETDL)"),
        "releaseRoutine": cpv("T:RELV", source="SCHED.txt:1835-1844"),
    }


RESOURCE_KINDS = {
    Resource.SYMBIONT_FILE_SLOT: ResourceKind(flush=True),
    Resource.SYMBIONT_DISC_SPACE: ResourceKind(flush=True),
    Resource.OPEN_CLOSE: ResourceKind(releaseRoutine="chooseOpenCloseUser"),
    Resource.TERMINAL_BUFFER: ResourceKind(flush=True),
    Resource.DISC_PAGE: ResourceKind(flush=True),
    Resource.ALLOCATOR: ResourceKind(flush=True, actOnEmpty=True, releaseRoutine="updateAllocator"),
    Resource.ENQUEUE: ResourceKind(specific=True, wakingSignals=frozenset(Signal)),
}


@cpv("T:RES", "T:REL", "SB:RQ", source="SCHED.txt:1745-1844",
     note="BLOCK AND RELEASE FOR RESOURCES")
class ResourceManager:
    """The users blocked on each resource, and their release.

    - **Block:** the user goes on the *head* of the resource's queue and waits in
      ``AWAITING_RESOURCE``.
    - **Release:** the head of the queue is made ready with the special-compute boost. A
      FLUSH resource releases everyone. A SPECIFIC one releases only the user the release is
      reported for, if they're blocked. Before that, a resource's release routine may run:
      the open/close resource lets someone through only if nobody is the open/close user.
    - **Signals:** a user blocked on a resource that lists the signal (only ENQ) is released
      at once to act on it. Others keep the signal until they run.

    CP-V quirk: blocking pushes on the head and release takes the head, so a resource's
    users are released last in, first out. CP-V also doesn't set the old head's back link,
    which ``T:UQR`` of a user other than the head would trip over (see the open questions in
    ``docs/scheduler.md``); the model's queues are plain lists. In CP-V a blocked user's
    ``UB:PRIO`` holds the back link, which is harmless because a release recomputes the
    priority.
    """

    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.queues = {resource: [] for resource in Resource}
        self.openCloseUser = None

    cpvNames = {
        "scheduler": modelOnly("The scheduler this resource manager belongs to"),
        "queues": cpv("SB:RQ", "U:MISC", source="SSDAT.txt:396-397, SCHED.txt:1808-1812",
                      note="Head per resource; U:MISC holds the forward link and resource index"),
        "openCloseUser": cpv("OPNCLSUS", source="SCHED.txt:1837-1844"),
    }

    @cpv("T:RES", "SQR", source="SCHED.txt:1755-1768")
    def block(self, user, resource):
        user.blockedOn = resource
        self.queues[resource].insert(0, user)
        self.scheduler.router.changeState(user, UserState.AWAITING_RESOURCE)

    @cpv("T:REL", "T:REL1", "SPECIFIC", "FLUSH", source="SCHED.txt:1771-1802")
    def release(self, resource, reportedFor=None):
        """Release users waiting for ``resource``. ``reportedFor`` is the user the release
        was reported for; it matters only for a SPECIFIC resource."""
        kind = RESOURCE_KINDS[resource]
        while True:
            if kind.specific:
                user = reportedFor if (reportedFor is not None and reportedFor.state
                                       is UserState.AWAITING_RESOURCE) else None
            else:
                user = self.queues[resource][0] if self.queues[resource] else None
                if user is None and not kind.actOnEmpty:
                    return
            if kind.releaseRoutine and not getattr(self, kind.releaseRoutine)(user):
                return
            if user is None:
                return
            self.unqueue(user)
            self.scheduler.log(user, f"released from {resource.name}")
            self.scheduler.router.makeReady(user, PriorityBoost.SPECIAL_COMPUTE)
            if not kind.flush:
                return

    @cpv("T:UQR", source="SCHED.txt:1814-1821",
         note="Unqueues from the user's own resource, whatever resource was released")
    def unqueue(self, user):
        self.queues[user.blockedOn].remove(user)
        user.blockedOn = None

    @cpv("OPNUNBLOCK", "OPNCLSUS", "OPNCLSUSR", source="SCHED.txt:1837-1844",
         note="Returns False to release nobody")
    def chooseOpenCloseUser(self, user):
        """Only one open/close user at a time: the released user becomes it, unless there
        already is one."""
        if self.openCloseUser is not None:
            return False
        self.openCloseUser = user
        return True

    @cpv("UQFAC", "STUQFAC", source="SCHED.txt:1707-1745, SCHED.txt:1836",
         note="Commits ALLOCAT's work on the granule stack, then releases the waiting users")
    def updateAllocator(self, user):
        self.scheduler.system.files.commitAllocation()
        return True

    @cpv("SETDL", "SH:RFLG", "T:UQR", source="SCHED.txt:1630-1647")
    def releaseForSignal(self, user, signal):
        """A signal arrived for a blocked user. Returns True if it released them."""
        if user.blockedOn is None or signal not in RESOURCE_KINDS[user.blockedOn].wakingSignals:
            return False
        self.unqueue(user)
        return True
