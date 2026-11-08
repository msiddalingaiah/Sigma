"""The swap scheduler: who comes into core, and who goes out to make room."""

from ..glossary import cpv, modelOnly
from ..user import UserState
from .events import Event

MAXIMUM_OUT = 20                # SMAXOUT: at most SMAXOUT - 1 users go out in one swap


@cpv("X'62'", source="SCHED.txt:2617-2625", note="IMPOSSIBLE SWAP CONDITION")
class ImpossibleSwap(Exception):
    """A ready user needs more pages than there are."""


@cpv("T:SS", "S:SIP", source="SCHED.txt:2102-2143",
     note="Called before every execution schedule and on interrupt exits; not re-entrant")
class SwapScheduler:
    """Decides who to swap in and who to swap out, and starts the swap.

    1. **Who comes in:** the most urgent ready user who isn't in core.
    2. **Room:** if the free pages are enough, they just come in.
    3. **Who goes out:** otherwise, walk the queues in the swap-out order (``SB:SWP``),
       each from its tail, and take in-core users until there is room. The walk skips users
       with I/O going, and ready users who haven't had their swap quantum yet. It gives up
       when it reaches the user coming in, so only waiting users and less urgent users are
       candidates.
    4. **Nobody to bring in:** the in-core sleepers and terminal waiters are swapped out
       anyway, to have the room ready.

    Kicked-out users lose ``inCore`` at once. The swap then takes the swap device's time,
    and when it finishes the pages move and the user coming in is in core.

    In CP-V this is really ``T:SS`` and the swapper (``SWAPOUT``, ``SWAPIN``). The model
    counts pages only: it leaves out shared processors and their use counts, the page
    stealer, partitions, and locks in core. CP-V also doesn't retry a failed swap-in until
    the swap set changes (``S:FSEVF``); the model just tries again.
    """

    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.swapInProgress = False
        self.lastFailure = None

    cpvNames = {
        "scheduler": modelOnly("The scheduler this swap scheduler belongs to"),
        "swapInProgress": cpv("S:SIP", source="SSDAT.txt:56"),
        "lastFailure": cpv("S:ISUNF", source="SCHED.txt:2607-2611",
                           note="Here only so that a failure is logged once"),
    }

    @cpv("T:SS", "PIKUS1", "SSIN", "GOTNUF", "DOSWAP", source="SCHED.txt:2109-2400")
    def schedule(self):
        """Look for a swap to do, and start it."""
        if self.swapInProgress:
            return
        queues = self.scheduler.stateQueues
        memory = self.scheduler.system.memory
        incoming = queues.firstReadyOutOfCore()
        if incoming is None:
            outgoing = self.chooseUsersToSwapOut(None, 0)
            if outgoing:
                self.startSwap(outgoing, None)
            return
        if incoming.pages > memory.totalPages:
            raise ImpossibleSwap(f"{incoming.name} needs {incoming.pages} pages, "
                                 f"there are {memory.totalPages}")
        shortfall = incoming.pages - memory.freePages
        outgoing = [] if shortfall <= 0 else self.chooseUsersToSwapOut(incoming, shortfall)
        if outgoing is None:
            self.giveUp(incoming)
            return
        self.lastFailure = None
        self.startSwap(outgoing, incoming)

    @cpv("USERSOUT", "SB:OSUL", "SMAXOUT", source="SCHED.txt:2445-2520",
         note="Users locked in core (RTHOLD, RMAHOLD), interrupted in a CAL, or in a held "
              "batch partition are skipped too; the model has none")
    def chooseUsersToSwapOut(self, incoming, shortfall):
        """Users to swap out to free ``shortfall`` pages for ``incoming``, or None if there
        aren't enough. With nobody coming in, the in-core sleepers and terminal waiters."""
        chosen, freed = [], 0
        for queue, isReadyQueue in self.scheduler.stateQueues.swapOutOrder():
            if isReadyQueue and incoming is None:
                return chosen
            for user in reversed(queue):
                if user is incoming:
                    return None
                if not self.canSwapOut(user, isReadyQueue) or len(chosen) >= MAXIMUM_OUT - 1:
                    continue
                chosen.append(user)
                freed += user.pages
                if incoming is not None and freed >= shortfall:
                    return chosen
        return chosen if incoming is None else None

    @cpv("USOUT5", "UB:MF", "SQUAN", source="SCHED.txt:2479-2492")
    def canSwapOut(self, user, isReady):
        """In core, no I/O going, and, for a ready user, has had their swap quantum."""
        if not user.inCore or user.ioInFlight > 0:
            return False
        return not (isReady and user.swapQuantumPending)

    @cpv("PROUT4", "E:KO", "SWAPOUT", "SWAPIN", source="SCHED.txt:2567-2579, SCHED.txt:2388-2392",
         note="Each user going out is reported E:KO; then the swapper does the I/O")
    def startSwap(self, outgoing, incoming):
        for user in outgoing:
            self.scheduler.report(user, Event.KICK_OUT)
        system = self.scheduler.system
        duration = self.scheduler.settings.swapTime * (len(outgoing) + (incoming is not None))
        if duration == 0:
            self.finishSwap(outgoing, incoming)
            return
        what = "swap starts:"
        if outgoing:
            what += " out " + ", ".join(user.name for user in outgoing)
        if incoming is not None:
            what += f"{';' if outgoing else ''} in {incoming.name}"
        self.scheduler.log(None, what)
        self.swapInProgress = True
        system.futureEvents.schedule(system.clock + duration,
                                     lambda: self.finishSwap(outgoing, incoming))

    @cpv("SIU13", "JIC", "RTR", "X'18'", source="SWAPPER.txt:1427-1510",
         note="The swap-in sets X'18' in UH:FLG2 (just swapped in, swap quantum pending)")
    def finishSwap(self, outgoing, incoming):
        """The swap device is done: pages move, and the user coming in is in core."""
        memory = self.scheduler.system.memory
        for user in outgoing:
            memory.give(user.pages)
            self.scheduler.log(user, "swapped out")
        if incoming is not None and incoming.state is not UserState.FREE_SLOT:
            memory.take(incoming.pages)
            incoming.inCore = True
            incoming.justSwappedIn = True
            incoming.swapQuantumPending = True
            self.scheduler.log(incoming, "swapped in")
        self.swapInProgress = False

    @cpv("GIVEUP", "C:NSP", source="SCHED.txt:2580-2625",
         note="CP-V also sets BYPASS and asks the page stealer for the shortfall")
    def giveUp(self, incoming):
        if self.lastFailure is not incoming:
            self.scheduler.log(incoming, "no room to swap in")
        self.lastFailure = incoming
