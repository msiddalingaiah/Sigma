"""The exit path: the checks made every time the monitor goes back to a user."""

import enum

from ..glossary import cpv, modelOnly
from ..program import Break


class Signal(enum.Enum):
    """Something the user must act on the next time they run. Several can be pending, but
    the exit path acts on only the most important and clears them all."""
    ABORT = enum.auto()
    ERROR = enum.auto()
    CONTROL_Y = enum.auto()
    BREAK = enum.auto()


cpv("ABRT", "BRK", source="SCHED.txt:472-481",
    note="Flags in the top four bits of UH:DL, beside the DO list's head")(Signal)

Signal.cpvNames = {
    "ABORT": cpv("ABRT", source="SCHED.txt:476", note="X'8000'"),
    "ERROR": cpv("ERR", source="SCHED.txt:477", note="X'4000'"),
    "CONTROL_Y": cpv("EC", source="SCHED.txt:478", note="X'2000'"),
    "BREAK": cpv("BRK", source="SCHED.txt:479", note="X'1000'"),
}


@cpv("SSE0", "SSE1", "TRAPEXIT", "T:SSE", source="SCHED.txt:862-1012",
     note="Every interrupt, trap and CAL goes back to the user this way")
class ExitPath:
    """Decides, on the way back to the current user, whether they really go on running.

    In order:

    1. **Signals.** Abort and error end the user's program. Control-Y goes back to the
       command processor. Break is thrown into the program as a ``Break`` exception (its
       break routine, ``M:INT``). A program that doesn't catch it goes back to the command
       processor, as with control-Y.
    2. **Quantum end.** The user gets a new quantum and goes back to their base priority, at
       the tail of their queue.
    3. **Preemption.** If a more urgent user is ready, and this one has run at least the
       minimum since being dispatched, this one goes back in the queue at their current
       priority.

    In CP-V this is really the code from ``SSE0`` to ``SSE6``. The model leaves out the DO
    list, the swap quantum (``SL:SQUAN``) and the real-time bypass of the minimum run
    (``S:RTIR`` = 0). There is no command processor yet, so going back to it ends the user.
    """

    def __init__(self, scheduler):
        self.scheduler = scheduler

    cpvNames = {"scheduler": modelOnly("The scheduler this exit path belongs to")}

    @cpv("SSE11", "T:DOLIST", source="SCHED.txt:893-1012")
    def check(self, user):
        """Run the checks for the current user. Afterwards the user is either still the
        current user, or back in a queue, or gone."""
        if user.pendingSignals:
            self.actOnSignals(user)
        elif user.quantumLeft <= 0:
            self.endQuantum(user)
        elif self.scheduler.system.clock - user.dispatchedAt < self.scheduler.settings.minimumRun:
            pass
        elif self.scheduler.moreUrgentUserWaiting(user):
            self.preempt(user)

    @cpv("T:DOLIST", "SEABRT", "SEERR", "SE7", "SE9", source="SCHED.txt:905-925",
         note="CP-V clears all four flags and acts on the first of ABRT, ERR, EC, BRK. "
              "CP-V quirk: a break and a control-Y together act as one control-Y")
    def actOnSignals(self, user):
        signals, user.pendingSignals = user.pendingSignals, set()
        system = self.scheduler.system
        if Signal.ABORT in signals:
            system.endUser(user, "aborted")
        elif Signal.ERROR in signals:
            system.endUser(user, "error")
        elif Signal.CONTROL_Y in signals:
            self.backToCommandProcessor(user, "control-Y")
        else:
            self.deliverBreak(user)

    @cpv("SE7", "SE6A", "J:INTENT", "ALTENT", source="SCHED.txt:1291-1324",
         note="CP-V enters the user's M:INT routine with the environment on the user's stack")
    def deliverBreak(self, user):
        user.computeLeft = 0            # the interrupted step is abandoned for the routine
        try:
            user.pendingRequest = user.program.throw(Break())
        except Break:
            self.backToCommandProcessor(user, "break with no break routine")
        except StopIteration:
            self.scheduler.system.endUser(user)

    @cpv("SE9", "T:ECCP", source="SCHED.txt:1306-1315",
         note="Ignored while the command processor is in control. The model has no command "
              "processor yet, so the user ends")
    def backToCommandProcessor(self, user, why):
        self.scheduler.system.endUser(user, f"{why}: back to the command processor")

    @cpv("SSE6", "T:ACCTEX", "T:CHSE0", source="SCHED.txt:1000-1012",
         note="J:DELTAT counts up from minus the quantum; at zero the quantum is over")
    def endQuantum(self, user):
        self.scheduler.log(user, "quantum ended")
        self.scheduler.endQuantum(user)

    @cpv("SSE41", "SSE43", "S:HIR", "CHSE0", source="SCHED.txt:794-846",
         note="CP-V quirk: near the swap quantum, SL:SQPB is added to the priority, which "
              "makes the user less urgent, not more")
    def preempt(self, user):
        self.scheduler.log(user, "preempted")
        self.scheduler.requeue(user)
