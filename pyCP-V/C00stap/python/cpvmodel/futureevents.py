"""Things that will happen later: a sleep ending, an I/O finishing, a swap completing."""

import heapq
import itertools

from .glossary import modelOnly


@modelOnly("Stands in for the interrupts that drive CP-V: clock 4 for wake-ups, the I/O "
           "interrupt for completions, the swap device for swaps")
class FutureEvents:
    """A calendar of actions, kept in time order. Two actions at the same time happen in the
    order they were added. An action may belong to a user, so it can be dropped when the
    user ends."""

    def __init__(self):
        self.pending = []
        self.sequence = itertools.count()

    cpvNames = {
        "pending": modelOnly("A heap of (time, sequence, user, action)"),
        "sequence": modelOnly("Keeps actions at the same time in order"),
    }

    @modelOnly("Adds an action to the calendar")
    def schedule(self, time, action, user=None):
        heapq.heappush(self.pending, (time, next(self.sequence), user, action))

    @modelOnly("When the next action is due, or None")
    def nextTime(self):
        return self.pending[0][0] if self.pending else None

    @modelOnly("Removes and returns the next (time, action) due by ``time``, or None")
    def popDue(self, time):
        if self.pending and self.pending[0][0] <= time:
            dueTime, _, _, action = heapq.heappop(self.pending)
            return dueTime, action
        return None

    @modelOnly("Drops a user's actions, when the user ends. CP-V's timers are in the JIT")
    def cancelFor(self, user):
        self.pending = [entry for entry in self.pending if entry[2] is not user]
        heapq.heapify(self.pending)
