"""Terminals: log-on, reads and type-ahead, output blocking, break and hang-up."""

from cpvmodel import Event, Program, System, TerminalSettings, UserState

from .scripts import Script, compute, readTerminal, writeTerminal



def happened(system, name, what):
    return [entry.time for entry in system.trace if entry.user == name and entry.what == what]


def testABreakOnAnEmptyLineLogsAUserOn():
    system = System()
    system.terminals.breakAt(10, 0)
    system.terminals.typeAt(100, 0, "HELLO")
    system.terminals.typeAt(200, 0, "OFF")
    assert system.run() == "shutdown"
    line = system.terminals.lines[0]
    assert line.printed() == "!HELLO\nHELLO\n!OFF\n"
    assert happened(system, "line0", "logged on, line 0") == [10]
    assert happened(system, "line0", "logged off, line 0") == [200]
    assert line.user is None and system.terminals.onlineUsers == 0


def testALoggedOnUserStartsAtTheOnlinePriority():
    system = System(terminalSettings=TerminalSettings(onlinePriority=0xF4))
    user = system.terminals.logOn(system.terminals.lines[1])
    assert user.basePriority == 0xF4
    assert user.line is system.terminals.lines[1]


def testLogOnIsRefusedPastTheOnlineLimit():
    system = System(terminalSettings=TerminalSettings(onlineUsersAllowed=1))
    assert system.terminals.logOn(system.terminals.lines[0]) is not None
    assert system.terminals.logOn(system.terminals.lines[1]) is None
    assert system.terminals.onlineUsers == 1


def testLogOnIsRefusedWithNoFreeSlot():
    system = System(userSlots=1)
    system.startUser("batch", Script(compute(1000)), priority=0xF8)
    assert system.terminals.logOn(system.terminals.lines[0]) is None


def testAReadWaitsAndInputReleasesWithTheInteractiveBoost():
    system = System(session=lambda line: Script(readTerminal(), compute(1000)))
    user = system.terminals.logOn(system.terminals.lines[0])
    system.run(tickLimit=50)
    assert user.state is UserState.AWAITING_TERMINAL_INPUT
    system.terminals.type(0, "X")
    assert user.state is UserState.READY
    assert user.priority == 0xF8 - 6


def testTypeAheadIsReadWithoutWaiting():
    received = []

    class Session(Program):
        def __init__(self, line):
            pass

        def run(self, m):
            self.compute(100)
            received.append(m.read(m.uc))

    system = System(session=Session)
    system.terminals.logOn(system.terminals.lines[0])
    system.terminals.typeAt(50, 0, "EARLY")
    system.run()
    assert received == ["EARLY"]
    assert not any("TERMINAL_READ" in entry.what for entry in system.trace)


def testInputOnALineWithNoUserIsLost():
    system = System()
    system.terminals.type(2, "NOBODY")
    assert not system.terminals.lines[2].typedLines


def testTooMuchOutputBlocksTheUserUntilItDrains():
    """With a block limit of 32, the fifth 8-character write finds 32 waiting and blocks.
    At 50 ticks a character the count is down to 8 after 24 characters, 1200 ticks."""
    settings = TerminalSettings(outputBlockLimit=32, outputUnblockLimit=8, ticksPerCharacter=50)
    system = System(terminalSettings=settings,
                    session=lambda line: Script(*[writeTerminal("12345678")] * 6))
    system.terminals.logOn(system.terminals.lines[0])
    system.run()
    assert happened(system, "line0", "OUTPUT_BLOCKED: RUNNING -> OUTPUT_BLOCKED") == [0]
    assert happened(system, "line0", "OUTPUT_UNBLOCKED: OUTPUT_BLOCKED -> READY") == [1200]
    assert system.terminals.lines[0].printed() == "12345678" * 6


def testABreakWithNoBreakRoutineGoesBackToTheCommandProcessor():
    system = System(session=lambda line: Script(compute(1000)))
    system.terminals.logOn(system.terminals.lines[0])
    system.terminals.breakAt(100, 0)
    system.run()
    assert happened(system, "line0",
                    "ended: break with no break routine: back to the command processor") == [100]


def testAHangUpAbortsAUserWaitingForInput():
    system = System()
    system.terminals.breakAt(0, 0)
    system.terminals.hangUpAt(100, 0)
    assert system.run() == "shutdown"
    assert happened(system, "line0", "ABORT: AWAITING_TERMINAL_INPUT -> READY") == [100]
    assert happened(system, "line0", "ended: aborted") == [100]
    assert system.terminals.onlineUsers == 0


def testInputThatComesBeforeTheUserBlocksIsntWaitedFor():
    """STIRCU then STCRD: the completion is reported while the user is still running, so
    the read event that follows doesn't block them."""
    system = System(session=lambda line: Script(compute(100)))
    user = system.terminals.logOn(system.terminals.lines[0])
    system.run(tickLimit=10)
    system.scheduler.report(user, Event.TERMINAL_INPUT_DONE)
    assert user.inputArrivedEarly
    system.scheduler.report(user, Event.TERMINAL_READ)
    assert user.state is UserState.RUNNING and not user.inputArrivedEarly


def testTheAccessQueueUsesTheSameEarlyFlag():
    system = System(session=lambda line: Script(compute(100)))
    user = system.terminals.logOn(system.terminals.lines[0])
    system.run(tickLimit=10)
    system.scheduler.report(user, Event.WAIT_FOR_ACCESS)
    assert user.state is UserState.AWAITING_ACCESS
    system.scheduler.report(user, Event.ACCESS_GRANTED)
    assert user.state is UserState.READY and user.priority == 0xF8 - 3
