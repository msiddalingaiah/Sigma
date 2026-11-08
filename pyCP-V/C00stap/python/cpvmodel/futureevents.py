"""Events that will be reported later: a sleep ending, an I/O finishing."""

import heapq
import itertools

from .glossary import modelOnly


@modelOnly("Stands in for the interrupts that report events in CP-V: clock 4 for wake-ups, "
           "the I/O interrupt for completions")
class FutureEvents:
    """A calendar of (time, user, event) reports, kept in time order. Two reports at the
    same time come out in the order they were added."""

    def __init__(self):
        self.pending = []
        self.sequence = itertools.count()

    cpvNames = {
        "pending": modelOnly("A heap of (time, sequence, user, event)"),
        "sequence": modelOnly("Keeps reports at the same time in order"),
    }

    @modelOnly("Adds a report to the calendar")
    def schedule(self, time, user, event):
        heapq.heappush(self.pending, (time, next(self.sequence), user, event))

    @modelOnly("When the next report is due, or None")
    def nextTime(self):
        return self.pending[0][0] if self.pending else None

    @modelOnly("Removes and returns the next report due by ``time``, or None")
    def popDue(self, time):
        if self.pending and self.pending[0][0] <= time:
            dueTime, _, user, event = heapq.heappop(self.pending)
            return dueTime, user, event
        return None
