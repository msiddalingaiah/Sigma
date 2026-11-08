"""The queues that users wait in. For now, only the ready users' priority bands."""

from .glossary import cpv

BAND_COUNT = 12
REAL_TIME_BAND = 0              # SRT: priority below X'C0'
BACKGROUND_BAND = 1             # SC0: X'C0'-X'F5'
FIRST_LEVEL_BAND = 2            # SC1: X'F6'; then one band per priority up to SC10, X'FF'
BACKGROUND_PRIORITY = 0xC0
FIRST_LEVEL_PRIORITY = 0xF6


@cpv("SB:HQ", "SB:TQ", "UB:FL", "UB:BL", source="SSDAT.txt:337-394",
     note="CP-V links users through per-user forward and back link bytes, "
          "with a head and tail byte per state")
class StateQueues:
    """A queue per state. So far only the ready users are queued, in twelve bands, most
    urgent first: real time (priority below X'C0'), background (X'C0'-X'F5'), and ten bands
    that hold one priority each (X'F6'-X'FF'). Within a band, users are ordered by priority
    and then first come, first served. The waiting states get their queues when users can
    wait.

    In CP-V each band is a separate state (``SRT``, ``SC0``-``SC10``) with its own queue,
    and which band a user is in *is* their state.
    """

    def __init__(self):
        self.bands = [[] for _ in range(BAND_COUNT)]

    cpvNames = {"bands": cpv("SRT", "SC0", "SC1", "SC10", source="SCHED.txt:277-288")}

    @staticmethod
    @cpv("CHSE1", source="SCHED.txt:1468-1480",
         note="Maps the priority to a state; X'F6' is SC1")
    def bandFor(priority):
        if priority < BACKGROUND_PRIORITY:
            return REAL_TIME_BAND
        if priority < FIRST_LEVEL_PRIORITY:
            return BACKGROUND_BAND
        return FIRST_LEVEL_BAND + priority - FIRST_LEVEL_PRIORITY

    @cpv("T:CHSE", "CHSE1", source="SCHED.txt:1452-1535",
         note="Inserts behind equal priorities. Queuing to the head (STASP) isn't modelled yet")
    def add(self, user):
        band = self.bands[self.bandFor(user.priority)]
        position = len(band)
        while position > 0 and band[position - 1].priority > user.priority:
            position -= 1
        band.insert(position, user)

    @cpv("RCE4", source="SCHED.txt:1408-1433", note="Unlinks the user from the old state's queue")
    def remove(self, user):
        self.bands[self.bandFor(user.priority)].remove(user)

    @cpv("SIC1", "SB:HQ", source="SCHED.txt:1036-1060",
         note="T:SE finds the first non-empty queue with a floating-point normalize")
    def firstReady(self):
        """The first user, most urgent band first, who is in core; or None."""
        for band in self.bands:
            for user in band:
                if user.inCore:
                    return user
        return None

    @cpv("SB:HQ", source="SSDAT.txt:390-394")
    def isEmpty(self):
        return not any(self.bands)
