"""Events, and the table that says what each event does to a user in each state.

Something in the system reports an event for a user: a terminal read finished, a sleep
ended, an I/O completed. The transition table looks up the user's state and the event and
gives an *action*, which is one of:

- a ``UserState``: just move the user there;
- a ``PriorityBoost``: make the user ready, with that much boost;
- the name of an ``EventRouter`` method, for anything more involved.

An event the table has no entry for is a bug in the reporter: CP-V stops with SCREECH X'02'.
"""

import enum
from dataclasses import dataclass

from ..glossary import cpv, modelOnly
from ..user import UserState

READY = UserState.READY
RUNNING = UserState.RUNNING
OUTPUT_BLOCKED = UserState.OUTPUT_BLOCKED
IO_WAIT = UserState.IO_WAIT
TOO_MUCH_IO = UserState.TOO_MUCH_IO
ASLEEP = UserState.ASLEEP
AWAITING_ACCESS = UserState.AWAITING_ACCESS
AWAITING_RESOURCE = UserState.AWAITING_RESOURCE
AWAITING_TERMINAL_INPUT = UserState.AWAITING_TERMINAL_INPUT
AWAITING_INTERRUPT = UserState.AWAITING_INTERRUPT
FREE_SLOT = UserState.FREE_SLOT
ALL_STATES = tuple(UserState)


class Event(enum.Enum):
    """Something that happened to a user.

    In CP-V an event is a number, the index of its entry in ``S:SET``, and the reporter
    passes it in R6. The resource events (``E:NSYMF`` onwards) come with resources.
    """
    IO_STARTED = enum.auto()
    TOO_MUCH_IO = enum.auto()
    TERMINAL_READ = enum.auto()
    TERMINAL_INPUT_DONE = enum.auto()
    OUTPUT_BLOCKED = enum.auto()
    OUTPUT_UNBLOCKED = enum.auto()
    BREAK = enum.auto()
    CONTROL_Y = enum.auto()
    ERROR = enum.auto()
    ABORT = enum.auto()
    WAKE_UP = enum.auto()
    SLEEP = enum.auto()
    WAIT_FOR_ACCESS = enum.auto()
    REAL_TIME_TASK_ADDED = enum.auto()
    ACCESS_GRANTED = enum.auto()
    KICK_OUT = enum.auto()
    ASSOCIATE_PROCESSOR = enum.auto()
    YIELD = enum.auto()
    IO_COMPLETE = enum.auto()
    WAIT_FOR_INTERRUPT = enum.auto()


cpv("ESTS", "ESTS1", source="SCHED.txt:398-431",
    note="Each ESTS builds a word in S:SET and a byte in SB:SET; the event is the word's index")(Event)

Event.cpvNames = {
    "IO_STARTED": cpv("E:IIP", source="SCHED.txt:513", note="I/O in progress; from T:IOREG"),
    "TOO_MUCH_IO": cpv("E:QMF", "E:IP", source="SCHED.txt:514",
                       note="Too many I/O requests going (master function count)"),
    "TERMINAL_READ": cpv("E:CRD", source="SCHED.txt:520", note="From COC"),
    "TERMINAL_INPUT_DONE": cpv("E:CIC", source="SCHED.txt:527-528", note="From COC"),
    "OUTPUT_BLOCKED": cpv("E:CBL", source="SCHED.txt:538", note="From COC"),
    "OUTPUT_UNBLOCKED": cpv("E:CUB", source="SCHED.txt:545-547", note="From COC"),
    "BREAK": cpv("E:CBK", source="SCHED.txt:566-567", note="From COC"),
    "CONTROL_Y": cpv("E:CEC", source="SCHED.txt:577-578", note="From COC"),
    "ERROR": cpv("E:ERR", source="SCHED.txt:585-587", note="From KEYIN"),
    "ABORT": cpv("E:OFF", "E:ABRT", source="SCHED.txt:594-596", note="From COC and KEYIN"),
    "WAKE_UP": cpv("E:WU", source="SCHED.txt:607-611", note="From CLOCK4"),
    "SLEEP": cpv("E:SL", source="SCHED.txt:615", note="From UCAL, RBBAT, TYPR"),
    "WAIT_FOR_ACCESS": cpv("E:QA", source="SCHED.txt:622", note="Queue for access; from COOP"),
    "REAL_TIME_TASK_ADDED": cpv("E:ART", source="SCHED.txt:629-631, RTROOT.txt:1224",
                                note="From RTROOT"),
    "ACCESS_GRANTED": cpv("E:UQA", source="SCHED.txt:638-639",
                          note="Unqueue from access; from RBBAT, TPQ, TQROOT"),
    "KICK_OUT": cpv("E:KO", source="SCHED.txt:646-647", note="From the swap scheduler"),
    "ASSOCIATE_PROCESSOR": cpv("E:AP", "E:NC", source="SCHED.txt:654",
                               note="From MM, STEP, SCHED, UCAL"),
    "YIELD": cpv("E:QE", source="SCHED.txt:662, RDL.txt:799-811",
                 note="The user's time is up and they give up the processor (RDL TIMSUP)"),
    "IO_COMPLETE": cpv("E:IC", source="SCHED.txt:667", note="From IOQ REQCOM"),
    "WAIT_FOR_INTERRUPT": cpv("E:QFI", source="SCHED.txt:668", note="From RTROOT"),
}


class PriorityBoost(enum.Enum):
    """How far below the base priority a user goes when made ready by an event. The value
    is subtracted from the priority number, so a bigger boost is more urgent.

    In CP-V the four entries are consecutive ``BAL,1 T:CHSE`` instructions in
    ``S:TRNSVEC``, and ``T:CHSE`` turns the return address into an index into ``SH:PINC``.
    """
    COMPUTE = 0
    SPECIAL_COMPUTE = 3
    IO_DONE = 2
    INTERACTIVE = 6


cpv("SH:PINC", "S:TRNSVEC", source="SCHED.txt:1540-1549, SSDAT.txt:421-424")(PriorityBoost)

PriorityBoost.cpvNames = {
    "COMPUTE": cpv("STSCOM", source="SCHED.txt:1541", note="Back to compute: no boost"),
    "SPECIAL_COMPUTE": cpv("STSC", source="SCHED.txt:1542", note="Woken up"),
    "IO_DONE": cpv("STIOCC", "STOC", source="SCHED.txt:1543-1545",
                   note="I/O complete, or terminal output can continue"),
    "INTERACTIVE": cpv("STIRC", source="SCHED.txt:1544-1549",
                       note="Terminal input complete; also marks the user interactive (X'20')"),
}


@modelOnly("A transition-table entry; CP-V's is an S:SET word and an SB:SET byte")
@dataclass(frozen=True)
class Rule:
    event: Event
    states: tuple
    action: object      # a UserState, a PriorityBoost, or an EventRouter method name


@cpv("X'02'", source="SCHED.txt:1380", note="USER'S STATE AND EVENT ARE INCONSISTENT")
class InconsistentEvent(Exception):
    """An event was reported for a user in a state that the event doesn't apply to."""


def _rule(event, states, action):
    return Rule(event, tuple(states), action)


# The rules in CP-V's order (SCHED.txt:513-668). For one event, the first rule that lists the
# user's state wins, as in RCE0. The tests check this table against the ESTS lines themselves.
RULES = [
    _rule(Event.IO_STARTED, [RUNNING], "waitForIo"),
    _rule(Event.TOO_MUCH_IO, [RUNNING], "waitForIoToDrain"),
    _rule(Event.TERMINAL_READ, [RUNNING], "waitForTerminalInput"),
    _rule(Event.TERMINAL_INPUT_DONE, [AWAITING_TERMINAL_INPUT], PriorityBoost.INTERACTIVE),
    _rule(Event.TERMINAL_INPUT_DONE, [RUNNING], "noteEarlyCompletion"),
    _rule(Event.OUTPUT_BLOCKED, [RUNNING], OUTPUT_BLOCKED),
    _rule(Event.OUTPUT_UNBLOCKED, [OUTPUT_BLOCKED], PriorityBoost.IO_DONE),
    _rule(Event.OUTPUT_UNBLOCKED, [READY, RUNNING, AWAITING_TERMINAL_INPUT, ASLEEP, IO_WAIT,
                                   TOO_MUCH_IO, AWAITING_ACCESS, AWAITING_RESOURCE,
                                   AWAITING_INTERRUPT], "ignore"),
    _rule(Event.BREAK, [RUNNING, IO_WAIT, TOO_MUCH_IO, AWAITING_ACCESS, AWAITING_RESOURCE,
                        FREE_SLOT], "signal"),
    _rule(Event.BREAK, [READY, ASLEEP, AWAITING_TERMINAL_INPUT, OUTPUT_BLOCKED,
                        AWAITING_INTERRUPT], "signalAndWake"),
    _rule(Event.CONTROL_Y, [RUNNING, IO_WAIT, TOO_MUCH_IO, AWAITING_ACCESS, AWAITING_RESOURCE,
                            FREE_SLOT], "signal"),
    _rule(Event.CONTROL_Y, [READY, ASLEEP, AWAITING_TERMINAL_INPUT, OUTPUT_BLOCKED,
                            AWAITING_INTERRUPT], "signalAndWake"),
    _rule(Event.ERROR, [READY, ASLEEP, AWAITING_INTERRUPT], "signalAndWake"),
    _rule(Event.ERROR, [RUNNING, IO_WAIT, OUTPUT_BLOCKED, TOO_MUCH_IO, AWAITING_ACCESS,
                        AWAITING_RESOURCE, FREE_SLOT, AWAITING_TERMINAL_INPUT], "signal"),
    _rule(Event.ABORT, [READY, ASLEEP, AWAITING_TERMINAL_INPUT, AWAITING_INTERRUPT,
                        AWAITING_ACCESS], "signalAndWake"),
    _rule(Event.ABORT, [RUNNING, TOO_MUCH_IO, IO_WAIT, OUTPUT_BLOCKED, AWAITING_RESOURCE,
                        FREE_SLOT], "signal"),
    _rule(Event.WAKE_UP, [ASLEEP, AWAITING_INTERRUPT], PriorityBoost.SPECIAL_COMPUTE),
    _rule(Event.WAKE_UP, ALL_STATES, "ignore"),
    _rule(Event.SLEEP, [RUNNING], ASLEEP),
    _rule(Event.WAIT_FOR_ACCESS, [RUNNING], "waitForAccess"),
    _rule(Event.REAL_TIME_TASK_ADDED, [RUNNING, IO_WAIT, TOO_MUCH_IO, AWAITING_RESOURCE,
                                       AWAITING_ACCESS, AWAITING_TERMINAL_INPUT, OUTPUT_BLOCKED,
                                       FREE_SLOT], "ignore"),
    _rule(Event.REAL_TIME_TASK_ADDED, [AWAITING_INTERRUPT, ASLEEP, READY], PriorityBoost.COMPUTE),
    _rule(Event.ACCESS_GRANTED, [AWAITING_ACCESS, IO_WAIT, RUNNING, READY], "grantAccess"),
    _rule(Event.ACCESS_GRANTED, ALL_STATES, "ignore"),
    _rule(Event.KICK_OUT, [ASLEEP, AWAITING_INTERRUPT, READY, AWAITING_ACCESS, TOO_MUCH_IO,
                           IO_WAIT], "kickOut"),
    _rule(Event.KICK_OUT, [OUTPUT_BLOCKED, AWAITING_TERMINAL_INPUT, AWAITING_RESOURCE],
          "kickOutWaiting"),
    _rule(Event.ASSOCIATE_PROCESSOR, [RUNNING], "associateProcessor"),
    _rule(Event.YIELD, [RUNNING], PriorityBoost.COMPUTE),
    _rule(Event.IO_COMPLETE, ALL_STATES, "completeIo"),
    _rule(Event.WAIT_FOR_INTERRUPT, [RUNNING], AWAITING_INTERRUPT),
]


@cpv("S:SET", "SB:SET", source="SCHED.txt:1371-1404",
     note="RCE0 walks the S:SET words from the event's index until one has the state's bit")
class TransitionTable:
    """In CP-V this is really two tables built by the ``ESTS`` procs: ``S:SET`` has a word
    per entry with a bit per state, and ``SB:SET`` has the action, a state number or an
    offset into ``S:TRNSVEC``. In the model, states that CP-V keeps in two versions (in
    core and out) are one state, so their entries are merged."""

    def __init__(self, rules=RULES):
        self.rules = list(rules)

    cpvNames = {"rules": cpv("S:SET", "SB:SET", source="SCHED.txt:419-428")}

    @cpv("RCE0", "X'02'", source="SCHED.txt:1371-1404")
    def lookup(self, event, state):
        for rule in self.rules:
            if rule.event is event and state in rule.states:
                return rule.action
        raise InconsistentEvent(f"{event.name} for a user in {state.name}")

    @modelOnly("For the state diagram and the tests")
    def rulesFor(self, event):
        return [rule for rule in self.rules if rule.event is event]
