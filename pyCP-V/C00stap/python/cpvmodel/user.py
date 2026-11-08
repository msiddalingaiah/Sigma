"""A user and the states a user can be in."""

import enum
from dataclasses import dataclass, field

from .glossary import cpv, modelOnly


class UserState(enum.Enum):
    """Where a user is. Every user is in exactly one state.

    In CP-V this is really a state number (1-31) in ``UB:US``, and each state has its own queue.
    The model simplifies two things:

    - The twelve executable states ``SRT``, ``SC0``-``SC10`` are one state, ``READY``. The
      priority bands they stand for are kept by ``StateQueues``.
    - CP-V has a second state for some waits when the user is swapped out (``STIO`` for
      ``STI``, and so on). The model keeps one state and the user's ``inCore`` flag.
    """
    READY = enum.auto()
    RUNNING = enum.auto()
    OUTPUT_BLOCKED = enum.auto()
    IO_WAIT = enum.auto()
    TOO_MUCH_IO = enum.auto()
    ASLEEP = enum.auto()
    AWAITING_ACCESS = enum.auto()
    AWAITING_RESOURCE = enum.auto()
    AWAITING_TERMINAL_INPUT = enum.auto()
    AWAITING_INTERRUPT = enum.auto()
    FREE_SLOT = enum.auto()


cpv("STATE", "SNSTS", source="SCHED.txt:255-318",
    note="States are numbered by the STATE proc; the order of the executable ones matters")(UserState)

_states = "SCHED.txt:277-318"
UserState.cpvNames = {
    "READY": cpv("SRT", "SC0", "SC10", source=_states,
                 note="Real-time, background (X'C0'-X'F5'), and one state per priority X'F6'-X'FF'"),
    "RUNNING": cpv("SCU", source=_states, note="The current user"),
    "OUTPUT_BLOCKED": cpv("STOB", "STOBO", source=_states, note="Terminal output blocked"),
    "IO_WAIT": cpv("SIOW", source=_states, note="Waiting for I/O"),
    "TOO_MUCH_IO": cpv("SIOMF", source=_states, note="Master function count too high"),
    "ASLEEP": cpv("SW", source=_states, note="Wait (asleep)"),
    "AWAITING_ACCESS": cpv("SQA", source=_states, note="Queued for access"),
    "AWAITING_RESOURCE": cpv("SQR", "SQRO", source=_states, note="Queued for a resource"),
    "AWAITING_TERMINAL_INPUT": cpv("STI", "STIO", source=_states, note="Terminal inputting"),
    "AWAITING_INTERRUPT": cpv("SQFI", source=_states, note="Queued for interrupt"),
    "FREE_SLOT": cpv("SNULL", source=_states, note="Empty user slot"),
}


@cpv("UB:US", "UH:FLG", "UB:PCT", source="SSDAT.txt:314-381",
     note="A user is a number that indexes the per-user tables (UB:*, UH:*, U:*)")
@dataclass(eq=False)
class User:
    """One user: an on-line user, a batch job or a ghost.

    Priority uses CP-V's numbers: X'00'-X'FF', and a *lower* value is *more* urgent.
    """
    number: int
    name: str = ""
    account: str = "GUEST"
    privilege: int = 0
    state: UserState = UserState.FREE_SLOT
    priority: int = 0xFF
    basePriority: int = 0xFF
    inCore: bool = False
    pages: int = 4
    swapQuantumPending: bool = False
    justSwappedIn: bool = False
    ioInFlight: int = 0
    blockedOn: object = None
    inputArrivedEarly: bool = False
    line: object = None
    quantumLeft: int = 0
    dispatchedAt: int = 0
    pendingSignals: set = field(default_factory=set)
    program: object = None
    computeLeft: int = 0
    pendingRequest: object = None
    stepResult: tuple = None
    stepError: Exception = None

    cpvNames = {
        "number": cpv("S:CUN", source="TCATCH.txt:173",
                      note="User numbers start at 1; 0 is the null link in the queues"),
        "name": modelOnly("For traces; CP-V knows the account and name from the JIT"),
        "account": cpv("J:ACCN", source="JIT.txt:308-310", note="The user's account"),
        "privilege": cpv("JB:PRIV", source="JIT.txt:470",
                         note="X'C0' or more opens any file and creates files anywhere"),
        "state": cpv("UB:US", source="SSDAT.txt:336"),
        "priority": cpv("UB:PRIO", source="SCHED.txt:1156-1160",
                        note="Current priority; events lower it below the base"),
        "basePriority": cpv("UB:PRIOB", source="SCHED.txt:1924"),
        "inCore": cpv("RTR", "JIC", source="SWAPPER.txt:1495-1500",
                      note="Ready to run (RTR) and JIT in core (JIC). Set when a swap-in "
                           "finishes, cleared by a kick-out"),
        "pages": cpv("UB:PCT", source="SSDAT.txt:377",
                     note="The pages the user needs in core. CP-V adds the user's shared "
                          "processors (T:TOTESZ)"),
        "swapQuantumPending": cpv("SQUAN", "UH:FLG2", source="SCHED.txt:986-997",
                                  note="Set at swap-in; while set, a ready user isn't swapped "
                                       "out"),
        "justSwappedIn": cpv("SWAPD", source="SCHED.txt:1182-1190",
                             note="Set at swap-in; the first dispatch gives a new quantum"),
        "ioInFlight": cpv("UB:MF", source="SCHED.txt:1574-1575",
                          note="The master function count: I/O requests the user has going"),
        "blockedOn": cpv("U:MISC", source="SCHED.txt:1808-1812",
                         note="The resource a user in SQR waits for (U:MISC byte 0)"),
        "inputArrivedEarly": cpv("UH:FLG", "X'4000'", source="SCHED.txt:1670-1690",
                                 note="The completion came before the user blocked (STIRCU)"),
        "line": cpv("LB:UN", source="SCHED.txt:1859",
                    note="CP-V maps the line to the user; the model links both ways"),
        "quantumLeft": cpv("J:DELTAT", source="ACCT.txt:27-43",
                           note="CP-V counts up from minus the quantum to zero"),
        "dispatchedAt": cpv("U:MISC", source="SCHED.txt:1194-1199",
                            note="The quantum mark saved at dispatch, for the minimum run"),
        "pendingSignals": cpv("UH:DL", source="SCHED.txt:905-912",
                              note="ABRT, ERR, EC and BRK flags, bits 0-3"),
        "program": modelOnly("A generator standing in for the user's code"),
        "computeLeft": modelOnly("Ticks left in the program's current Compute step"),
        "pendingRequest": modelOnly("The step a program yielded from its break routine, or "
                                    "a step to try again after a wait"),
        "stepResult": modelOnly("What the program's last step returns, as a 1-tuple, sent "
                                "back into the program: a terminal line, a file handle, a "
                                "record"),
        "stepError": modelOnly("An error the last step raises, thrown into the program"),
    }

    @cpv("UB:PRIO", "UB:PRIOB", source="SCHED.txt:1156-1160",
         note="Lower values are more urgent")
    def isMoreUrgentThan(self, other):
        return self.priority < other.priority

    def __repr__(self):
        return f"User({self.number}, {self.name!r}, {self.state.name}, prio={self.priority:#04x})"
