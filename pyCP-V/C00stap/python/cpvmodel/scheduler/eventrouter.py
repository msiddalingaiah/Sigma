"""Reporting events: look the event up in the transition table, then act on it."""

from .events import (AWAITING_ACCESS, AWAITING_TERMINAL_INPUT, IO_WAIT, READY, RUNNING,
                     TOO_MUCH_IO, Event, PriorityBoost, TransitionTable)
from .exitpath import Signal

SIGNAL_FOR = {
    Event.BREAK: Signal.BREAK,
    Event.CONTROL_Y: Signal.CONTROL_Y,
    Event.ERROR: Signal.ERROR,
    Event.ABORT: Signal.ABORT,
}
from ..glossary import cpv, modelOnly
from ..user import UserState


@modelOnly("Raised by the transitions that a later iteration will model")
class NotModelledYet(Exception):
    """The transition exists in CP-V's table but isn't modelled yet."""


def leadsTo(target, fromStates=None):
    """Record, for the state diagram, which state a handler moves a user to. Without
    ``fromStates`` it can be any state the table sends to the handler."""
    def mark(function):
        function.leadsTo = (target, fromStates)
        return function
    return mark


@cpv("T:RE", "T:RUE", "RCE0", "RCE4", source="SCHED.txt:1360-1433",
     note="CP-V reports with the event in R6 and the user in R4 or R5, disabled")
class EventRouter:
    """Takes event reports and moves users between states.

    In CP-V this is really the code from ``T:REG`` to ``CHS1`` in SCHED, and the special
    transition routines that ``S:TRNSVEC`` points into.
    """

    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.table = TransitionTable()
        self.eventCount = 0

    cpvNames = {
        "scheduler": modelOnly("The scheduler the router belongs to"),
        "table": cpv("S:SET", "SB:SET", source="SCHED.txt:419-428"),
        "eventCount": cpv("S:EVF", source="SSDAT.txt:403",
                          note="Bumped on every report and state change; the swap scheduler "
                               "uses it to notice that something happened while it worked"),
    }

    @cpv("RCE0", source="SCHED.txt:1371-1404", note="T:RUE reports for any user, T:RE for "
         "the current one, T:REG for the current one and then reschedules")
    def report(self, user, event, detail=None):
        """Report ``event`` for ``user``. ``detail`` is what the reporter passes with it."""
        self.eventCount += 1
        oldState = user.state
        action = self.table.lookup(event, oldState)
        if isinstance(action, UserState):
            self.changeState(user, action)
        elif isinstance(action, PriorityBoost):
            self.makeReady(user, action)
        else:
            getattr(self, action)(user, event, detail)
        if user.state is oldState:
            self.scheduler.log(user, f"{event.name} in {oldState.name}")
        else:
            self.scheduler.log(user, f"{event.name}: {oldState.name} -> {user.state.name}")

    @cpv("RCE4", "CHS1", "S:EVF", source="SCHED.txt:1408-1433, SCHED.txt:1606-1611",
         note="Unlinks the user from the old state's queue and appends them to the new one")
    def changeState(self, user, newState):
        self._leave(user)
        self._enter(user, newState)

    @cpv("T:CHSE", "CHSE1", "OPNBOOST", source="SCHED.txt:1452-1535",
         note="The OPNBOOST for the open/close user isn't modelled yet")
    def makeReady(self, user, boost=PriorityBoost.COMPUTE):
        """Make the user ready at their base priority less ``boost``. A real-time user
        always runs at their base: "DONT FLOAT RT"."""
        self._leave(user)
        user.priority = max(0, user.basePriority - boost.value)
        if user.basePriority < 0xC0:
            user.priority = user.basePriority
        self._enter(user, READY)

    @cpv("CHSE0", source="SCHED.txt:1459-1466",
         note="Entered with the priority already chosen; the exit path uses it to park "
              "a preempted user")
    def requeue(self, user):
        """Back in the queue at the user's current priority, behind equals."""
        self._leave(user)
        self._enter(user, READY)

    def _leave(self, user):
        if user.state is READY:
            self.scheduler.stateQueues.remove(user)
        if user is self.scheduler.currentUser:
            self.scheduler.currentUser = None

    def _enter(self, user, state):
        user.state = state
        if state is READY:
            self.scheduler.stateQueues.add(user)
        elif state is RUNNING:
            self.scheduler.currentUser = user
        self.eventCount += 1

    # --- The special transitions (S:TRNSVEC) --------------------------------------------

    @cpv("STNOP", source="SCHED.txt:1608", note="Not every event matters in every state")
    def ignore(self, user, event, detail):
        pass

    @leadsTo(IO_WAIT)
    @cpv("STIIP", "UB:MF", "GRANT", source="SCHED.txt:1553-1572",
         note="CP-V also marks the DCB as waited on, and later releases the user when that "
              "DCB's I/O is done; the model waits for all the user's I/O")
    def waitForIo(self, user, event, detail):
        """The user started I/O and waits for it, unless it has already finished."""
        if user.ioInFlight > 0:
            self.changeState(user, IO_WAIT)

    @leadsTo(READY, fromStates=[IO_WAIT, TOO_MUCH_IO])
    @cpv("STIOC", "UB:MF", "STIOCC", source="SCHED.txt:1574-1605")
    def completeIo(self, user, event, detail):
        """One of the user's I/O requests is done. A user waiting for I/O is released when
        none is left."""
        user.ioInFlight -= 1
        if user.state is TOO_MUCH_IO:
            raise NotModelledYet("release from TOO_MUCH_IO (SL:OIMF, SL:BIMF)")
        if user.state is IO_WAIT and user.ioInFlight == 0:
            self.makeReady(user, PriorityBoost.IO_DONE)

    @leadsTo(TOO_MUCH_IO)
    @cpv("STIOMF", source="SCHED.txt:1553")
    def waitForIoToDrain(self, user, event, detail):
        raise NotModelledYet("STIOMF")

    @leadsTo(AWAITING_TERMINAL_INPUT)
    @cpv("STCRD", source="SCHED.txt:1670-1673",
         note="Waits unless the input already came (UH:FLG X'4000')")
    def waitForTerminalInput(self, user, event, detail):
        raise NotModelledYet("STCRD: terminals come later")

    @cpv("STIRCU", source="SCHED.txt:1685-1688",
         note="Input finished before the user blocked: sets UH:FLG X'4000'")
    def noteEarlyCompletion(self, user, event, detail):
        raise NotModelledYet("STIRCU: terminals come later")

    @cpv("STBEEA", "SETDL", "UH:DL", source="SCHED.txt:1630-1660",
         note="Picks the flag by event number. For an on-line user, an abort also marks the "
              "terminal line off (COCOFF); a user blocked on R:NQW is released")
    def signal(self, user, event, detail):
        """Note the signal; the user acts on it the next time they run."""
        user.pendingSignals.add(SIGNAL_FOR[event])

    @leadsTo(READY)
    @cpv("STBEEAC", "STIRC", source="SCHED.txt:1630-1660",
         note="As STBEEA, and makes a waiting user interactive compute so they see it soon")
    def signalAndWake(self, user, event, detail):
        user.pendingSignals.add(SIGNAL_FOR[event])
        self.makeReady(user, PriorityBoost.INTERACTIVE)

    @leadsTo(AWAITING_ACCESS)
    @cpv("STQA", source="SCHED.txt:1674-1682")
    def waitForAccess(self, user, event, detail):
        raise NotModelledYet("STQA")

    @leadsTo(READY, fromStates=[AWAITING_ACCESS])
    @cpv("STUQA", source="SCHED.txt:1683-1688",
         note="Special compute if queued for access, otherwise remembered as early")
    def grantAccess(self, user, event, detail):
        raise NotModelledYet("STUQA")

    @cpv("STKO", "RTR", source="SCHED.txt:1697-1705", note="Swapped out: RTR and JIC cleared")
    def kickOut(self, user, event, detail):
        raise NotModelledYet("STKO: swapping comes later")

    @cpv("STKOT", source="SCHED.txt:1692-1696",
         note="Swapped out while waiting: CP-V moves to the out-of-core twin state")
    def kickOutWaiting(self, user, event, detail):
        raise NotModelledYet("STKOT: swapping comes later")

    @leadsTo(READY)
    @cpv("STASP", source="SCHED.txt:1668-1669",
         note="Special compute, queued at the head")
    def associateProcessor(self, user, event, detail):
        raise NotModelledYet("STASP")
