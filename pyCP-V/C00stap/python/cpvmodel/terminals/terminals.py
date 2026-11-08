"""Terminals: the lines users type on, reads and writes, and log-on."""

from collections import deque
from dataclasses import dataclass, field

from ..glossary import cpv, modelOnly
from ..program import Compute, ReadTerminal, WriteTerminal
from ..scheduler import Event
from ..user import UserState


@cpv("SL:TB", "SL:UB", "S:OUAIS", "SL:OPRIO", source="CONMAIN.txt:1041-1087",
     note="Operator settings (CONMAIN); none is set in the source")
@dataclass(frozen=True)
class TerminalSettings:
    """The terminal and log-on limits. The defaults are illustrative; a terminal of 10
    characters a second (a Teletype) sends one character every 50 ticks."""
    outputBlockLimit: int = 32
    outputUnblockLimit: int = 8
    ticksPerCharacter: int = 50
    onlineUsersAllowed: int = 8
    onlinePriority: int = 0xF8
    onlinePages: int = 4

    cpvNames = {
        "outputBlockLimit": cpv("SL:TB", source="COC.txt:2871-2879",
                                note="A write with this much output pending blocks the user"),
        "outputUnblockLimit": cpv("SL:UB", source="COC.txt:2028",
                                  note="The output interrupt releases the user at this count"),
        "ticksPerCharacter": modelOnly("The line's speed; CP-V's comes from the line's hardware"),
        "onlineUsersAllowed": cpv("S:OUAIS", source="CONMAIN.txt:1041",
                                  note="The OUM key-in"),
        "onlinePriority": cpv("SL:OPRIO", source="CONMAIN.txt:1087", note="192-255"),
        "onlinePages": modelOnly("Pages a logged-on user needs; CP-V's come from TEL and the JIT"),
    }


@cpv("LB:UN", "MODE", source="SCHED.txt:1859, COC.txt:2590-2593",
     note="COC keeps a line's tables indexed by line number")
@dataclass(eq=False)
class Line:
    """One terminal line."""
    number: int
    user: object = None
    typedLines: deque = field(default_factory=deque)
    readPending: bool = False
    outputCount: int = 0
    outputCountAt: int = 0
    transcript: list = field(default_factory=list)

    cpvNames = {
        "number": cpv("LB:UN", source="SCHED.txt:1859", note="The line number indexes LB:UN"),
        "user": cpv("LB:UN", source="SCHED.txt:1859-1860", note="0 when nobody is logged on"),
        "typedLines": cpv("COCIP", source="COC.txt:412", note="The line's input buffers"),
        "readPending": cpv("MODE", source="COC.txt:2590-2591", note="The read-pending bit, X'10'"),
        "outputCount": cpv("COCOC", source="COC.txt:2870-2872",
                           note="Characters waiting to go out"),
        "outputCountAt": modelOnly("When outputCount was last brought up to date"),
        "transcript": modelOnly("What the terminal printed, for tests and for reading"),
    }

    @modelOnly("What the terminal printed, as text")
    def printed(self):
        return "".join(self.transcript)


@modelOnly("A stand-in for TEL: a prompt, a command, an echo; OFF logs off")
def echoSession(line):
    while True:
        yield WriteTerminal("!")
        command = yield ReadTerminal()
        if command.strip().upper() == "OFF":
            return
        yield Compute(10)
        yield WriteTerminal(command + "\n")


@cpv("COC", "T:RCE", source="SCHED.txt:1846-1868",
     note="COC is CP-V's character-oriented communications handler")
class TerminalController:
    """The terminal lines, and what they report to the scheduler.

    - **Reading:** a read with a typed line ready completes at once. Otherwise the user
      waits for input (``TERMINAL_READ``, state ``AWAITING_TERMINAL_INPUT``) until a line is
      typed (``TERMINAL_INPUT_DONE``, with the interactive boost).
    - **Writing:** output drains at the line's speed. A write while ``outputBlockLimit``
      characters are waiting blocks the user (``OUTPUT_BLOCKED``) until the count is down to
      ``outputUnblockLimit`` (``OUTPUT_UNBLOCKED``).
    - **Break** on a line goes to its user. On a line with nobody logged on, it logs a new
      user on: a free slot, under the on-line limit, running the line's session.
    - **Hang-up** aborts the line's user.

    In CP-V this is really COC: character interrupts, echo, the line's buffers, editing and
    the many line modes, none of which the model has. The model's ``session`` stands for
    TEL, the command processor a logged-on user starts in.
    """

    def __init__(self, system, lineCount=4, settings=None, session=echoSession):
        self.system = system
        self.settings = settings or TerminalSettings()
        self.lines = [Line(number) for number in range(lineCount)]
        self.session = session
        self.onlineUsers = 0

    cpvNames = {
        "system": modelOnly("The system the terminals belong to"),
        "settings": cpv("SL:TB", "SL:UB", source="COC.txt:2028, COC.txt:2872"),
        "lines": cpv("LB:UN", source="SCHED.txt:1859"),
        "session": modelOnly("The program a logged-on user runs; stands for TEL"),
        "onlineUsers": cpv("S:OUIS", source="SSDAT.txt:53, STEP.txt:159",
                           note="Counted up at log-on, down when the user is removed"),
    }

    # --- What happens on the line -------------------------------------------------------

    @cpv("COCIPBRK", "E:CBK", "T:RCE", source="COC.txt:857-900, SCHED.txt:1859-1868")
    def pressBreak(self, lineNumber):
        line = self.lines[lineNumber]
        if line.user is None:
            self.logOn(line)
        else:
            self.system.scheduler.report(line.user, Event.BREAK)

    @cpv("COCIP", "E:CIC", source="COC.txt:412-593",
         note="CP-V gets a character at a time and completes the read at an activation "
              "character; the model gets a whole line")
    def type(self, lineNumber, text):
        """A line typed on the terminal, ended by RETURN."""
        line = self.lines[lineNumber]
        if line.user is None:
            return                              # a line with no user buffers nothing
        line.typedLines.append(text)
        if line.readPending:
            line.readPending = False
            self.system.scheduler.report(line.user, Event.TERMINAL_INPUT_DONE)

    @cpv("E:OFF", "UH:FLG2", source="SCHED.txt:1859-1866",
         note="The line drops (found by T:COCHC): T:RCE sets the hang-up bit and reports E:OFF")
    def hangUp(self, lineNumber):
        line = self.lines[lineNumber]
        if line.user is not None:
            self.system.scheduler.report(line.user, Event.ABORT)

    @modelOnly("Schedules a line to be typed at ``time``")
    def typeAt(self, time, lineNumber, text):
        self.system.futureEvents.schedule(time, lambda: self.type(lineNumber, text))

    @modelOnly("Schedules a break key at ``time``")
    def breakAt(self, time, lineNumber):
        self.system.futureEvents.schedule(time, lambda: self.pressBreak(lineNumber))

    @modelOnly("Schedules a hang-up at ``time``")
    def hangUpAt(self, time, lineNumber):
        self.system.futureEvents.schedule(time, lambda: self.hangUp(lineNumber))

    # --- Log-on and log-off -------------------------------------------------------------

    @cpv("LOGON", "S:OUIS", "S:OUAIS", "SL:OPRIO", source="SCHED.txt:1869-1893",
         note="CP-V also checks the swap devices' free granules against S:OUAIS")
    def logOn(self, line):
        if self.onlineUsers >= self.settings.onlineUsersAllowed or not self.system.freeSlots:
            self.system.log(None, f"line {line.number}: log-on refused")
            return None
        self.onlineUsers += 1
        user = self.system.startUser(f"line{line.number}", self.session(line),
                                     priority=self.settings.onlinePriority,
                                     pages=self.settings.onlinePages)
        line.user = user
        user.line = line
        self.system.log(user, f"logged on, line {line.number}")
        return user

    @cpv("S:OUIS", source="STEP.txt:155-160",
         note="CP-V marks the line off (COCOFF) on a hang-up")
    def userEnded(self, user):
        line = user.line
        if line is None:
            return
        line.user = None
        line.readPending = False
        line.typedLines.clear()
        user.line = None
        self.onlineUsers -= 1
        self.system.log(user, f"logged off, line {line.number}")

    # --- What the user's program asks for -----------------------------------------------

    @cpv("COCRD", "E:CRD", source="COC.txt:2287-2606",
         note="CP-V echoes type-ahead when the read starts, then waits for an activation")
    def read(self, user):
        """The typed line, or None when the user must wait for one (they are then
        waiting, or, if the input came early, still running)."""
        line = user.line
        if line.typedLines:
            text = line.typedLines.popleft()
            line.transcript.append(text + "\n")
            return text
        line.readPending = True
        self.system.scheduler.report(user, Event.TERMINAL_READ)
        return None

    @cpv("COCWR", "SL:TB", "E:CBL", source="COC.txt:2864-2890",
         note="The limit is checked before the record goes into the buffers")
    def write(self, user, text):
        """Send ``text`` to the user's terminal. Returns False if the user was blocked
        instead, to write once the output has drained."""
        line = user.line
        self.drain(line)
        if line.outputCount >= self.settings.outputBlockLimit:
            self.system.scheduler.report(user, Event.OUTPUT_BLOCKED)
            waitFor = (line.outputCount - self.settings.outputUnblockLimit) \
                * self.settings.ticksPerCharacter
            self.system.futureEvents.schedule(self.system.clock + waitFor,
                                              lambda: self.outputDrained(line), user)
            return False
        line.outputCount += len(text)
        line.transcript.append(text)
        return True

    @cpv("SL:UB", "E:CUB", source="COC.txt:2020-2044",
         note="The output interrupt sends a character; at SL:UB a blocked user is released")
    def outputDrained(self, line):
        self.drain(line)
        if line.user is not None and line.user.state is UserState.OUTPUT_BLOCKED:
            self.system.scheduler.report(line.user, Event.OUTPUT_UNBLOCKED)

    @modelOnly("Brings the output count up to date: a character goes out every "
               "ticksPerCharacter. CP-V counts down at each output interrupt")
    def drain(self, line):
        sent = (self.system.clock - line.outputCountAt) // self.settings.ticksPerCharacter
        line.outputCount = max(0, line.outputCount - sent)
        line.outputCountAt = self.system.clock if line.outputCount == 0 \
            else line.outputCountAt + sent * self.settings.ticksPerCharacter
