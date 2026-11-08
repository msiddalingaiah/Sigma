"""The queues that users wait in, one per state, with the ready users in priority bands."""

from ..glossary import cpv
from ..user import UserState

BAND_COUNT = 12
REAL_TIME_BAND = 0              # SRT: priority below X'C0'
BACKGROUND_BAND = 1             # SC0: X'C0'-X'F5'
FIRST_LEVEL_BAND = 2            # SC1: X'F6'; then one band per priority up to SC10, X'FF'
LAST_BAND = BAND_COUNT - 1      # SC10
BACKGROUND_PRIORITY = 0xC0
FIRST_LEVEL_PRIORITY = 0xF6

# States without a queue here: the running user, and free slots (System.freeSlots).
UNQUEUED_STATES = (UserState.READY, UserState.RUNNING, UserState.FREE_SLOT)


@cpv("SB:HQ", "SB:TQ", "UB:FL", "UB:BL", source="SSDAT.txt:337-394",
     note="CP-V links users through per-user forward and back link bytes, "
          "with a head and tail byte per state")
class StateQueues:
    """A queue per state.

    - **Ready users** are in twelve bands, most urgent first. There is real time (priority below
      X'C0'), background (X'C0'-X'F5'), and ten bands that hold one priority each
      (X'F6'-X'FF'). Within a band, users are ordered by priority and then first come, first
      served.
    - **Waiting users** are in a queue per state, in the order they arrived.

    In CP-V each band is a separate state (``SRT``, ``SC0``-``SC10``) with its own queue,
    and which band a user is in *is* their state. The swap scheduler walks the queues in a
    fixed order (``SB:SWP``) to choose who to swap out.
    """

    def __init__(self):
        self.bands = [[] for _ in range(BAND_COUNT)]
        self.waiting = {state: [] for state in UserState if state not in UNQUEUED_STATES}

    cpvNames = {
        "bands": cpv("SRT", "SC0", "SC1", "SC10", source="SCHED.txt:277-288"),
        "waiting": cpv("SB:HQ", "SB:TQ", source="SSDAT.txt:390-394",
                       note="The queues of the waiting states, STOB to SQFI"),
    }

    @staticmethod
    @cpv("CHSE1", source="SCHED.txt:1468-1480",
         note="Maps the priority to a state; X'F6' is SC1")
    def bandFor(priority):
        if priority < BACKGROUND_PRIORITY:
            return REAL_TIME_BAND
        if priority < FIRST_LEVEL_PRIORITY:
            return BACKGROUND_BAND
        return FIRST_LEVEL_BAND + priority - FIRST_LEVEL_PRIORITY

    @cpv("T:CHSE", "CHSE1", "RCE4", source="SCHED.txt:1408-1535",
         note="A ready user goes behind equal priorities (T:CHSE); a waiting user goes to "
              "the tail of their state's queue (RCE4). Queuing to the head (STASP) isn't "
              "modelled yet")
    def add(self, user):
        """Queue the user for their current state."""
        if user.state is UserState.READY:
            band = self.bands[self.bandFor(user.priority)]
            position = len(band)
            while position > 0 and band[position - 1].priority > user.priority:
                position -= 1
            band.insert(position, user)
        elif user.state in self.waiting:
            self.waiting[user.state].append(user)

    @cpv("RCE4", source="SCHED.txt:1408-1433", note="Unlinks the user from the old state's queue")
    def remove(self, user):
        """Take the user out of the queue for their current state."""
        if user.state is UserState.READY:
            self.bands[self.bandFor(user.priority)].remove(user)
        elif user.state in self.waiting:
            self.waiting[user.state].remove(user)

    @cpv("SIC1", "SB:HQ", source="SCHED.txt:1036-1060",
         note="T:SE finds the first non-empty queue with a floating-point normalize")
    def firstReady(self):
        """The first ready user in core, most urgent band first; or None."""
        return next((user for band in self.bands for user in band if user.inCore), None)

    @cpv("PIKUS1", "RTR", source="SCHED.txt:2117-2143",
         note="The same scan as T:SE, for a user without RTR")
    def firstReadyOutOfCore(self):
        """The first ready user who isn't in core, most urgent band first; or None."""
        return next((user for band in self.bands for user in band if not user.inCore), None)

    @cpv("SB:SWP", source="SCHED.txt:763-764",
         note="SW, STI, SC10, STOB, SQR, SQFI, SQA, SC9, ..., SC0, SRT")
    def swapOutOrder(self):
        """The queues in the order the swap scheduler looks for users to swap out, as
        (queue, isReadyQueue) pairs. Sleepers and terminal waiters come first; then the least
        urgent ready users; then other waiting users; then the rest of the ready users, most
        urgent last."""
        order = [(self.waiting[UserState.ASLEEP], False),
                 (self.waiting[UserState.AWAITING_TERMINAL_INPUT], False),
                 (self.bands[LAST_BAND], True),
                 (self.waiting[UserState.OUTPUT_BLOCKED], False),
                 (self.waiting[UserState.AWAITING_RESOURCE], False),
                 (self.waiting[UserState.AWAITING_INTERRUPT], False),
                 (self.waiting[UserState.AWAITING_ACCESS], False)]
        order += [(self.bands[band], True) for band in range(LAST_BAND - 1, -1, -1)]
        return order

    @cpv("SB:HQ", source="SSDAT.txt:390-394")
    def isEmpty(self):
        return not any(self.bands) and not any(self.waiting.values())
