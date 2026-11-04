from uts.__main__ import boot
from uts.config import Sysgen
from uts.io import (ConsoleHandler, IOSystem, PrinterUnit, TYC_ERROR, TYC_NORMAL,
                    TY_READ, TY_WRITE)
from uts.keyin import OperatorConsole

STD = ["06/15/76", "13:45", "N"]


def console(lp_faults=None):
    m, mon, outcome = boot(replies=STD)
    assert outcome == "up"
    m.console.transcript.clear()
    return OperatorConsole(m, mon, Sysgen(), lp_faults=lp_faults)


def test_print_goes_through_the_queue_and_completes():
    con = console()
    req = con.print_line("HELLO")
    assert req.done and req.tyc == TYC_NORMAL
    assert con.m.printer.lines == ["HELLO"]
    assert len(con.io.qfree) == 20                        # the entry went back to QFREE


def test_console_write_and_read_with_editing():
    con = console()
    io = con.io
    io.newq(con.oc, TY_WRITE, "\nHI")
    con.m.console.replies.append("abc")
    got = []
    io.newq(con.oc, TY_READ, count=72, end_action=lambda r, tyc: got.append((r.buffer, tyc)))
    assert got == [("ABC\n", TYC_NORMAL)]
    assert con.m.console.text().startswith("\nHI")


def test_long_line_gets_a_follow_on_newline():
    con = console()
    con.m.console.replies.append("X" * 80)
    got = []
    con.io.newq(con.oc, TY_READ, count=72, end_action=lambda r, tyc: got.append(r))
    assert got[0].step == 5                               # follow-on: write NL (KBTCU X'6000')
    assert got[0].buffer == "X" * 72


def test_eod_line():
    con = console()
    con.m.console.replies.append("!EOD")
    got = []
    con.io.newq(con.oc, TY_READ, count=72, end_action=lambda r, tyc: got.append(tyc))
    assert got == [6]


def test_errors_are_retried_silently():
    con = console({"error": 2})
    req = con.print_line("LINE")
    assert req.tyc == TYC_NORMAL and con.m.printer.lines == ["LINE"]
    assert "ERROR" not in con.m.console.text()


def test_too_many_errors_complete_in_error_with_a_message():
    con = console({"error": 9})
    req = con.print_line("LINE")                          # 3 tries: 1 + 3 retries
    assert req.tyc == TYC_ERROR and con.m.printer.lines == []
    assert "LPA02 ERROR" in con.m.console.text()


def test_not_operational_waits_for_the_operator():
    con = console({"notop": 1})
    req = con.print_line("LINE")
    assert not req.done and con.waiting() == ["LPA02"]
    assert "LPA02 NOT OPERATIONAL" in con.m.console.text()
    assert con.io.device_keyin(con.io.devices[con.lp], "R") == "retry"
    assert req.done and con.m.printer.lines == ["LINE"]


def test_operator_error_answer_completes_in_error():
    con = console({"parity": 1})
    req = con.print_line("LINE")
    assert "CODE DISC ERR" in con.m.console.text()
    con.io.device_keyin(con.io.devices[con.lp], "E")
    assert req.done and req.tyc == TYC_ERROR


def test_timeout_and_please_respond():
    con = console({"hang": 1})
    req = con.print_line("LINE")
    io = con.io
    io.tick(2)                                            # 5-second timeout passed
    assert "LPA02 TIMED OUT" in con.m.console.text() and con.waiting() == ["LPA02"]
    io.tick(7)                                            # 30 s with no answer
    assert "LPA02 PLEASE RESPOND" in con.m.console.text()
    io.device_keyin(io.devices[con.lp], "R")
    assert req.done and con.m.printer.lines == ["LINE"]


def test_manual_device_is_reminded_then_runs_when_made_automatic():
    con = console({"manual": 2})
    req = con.print_line("LINE")
    text = con.m.console.text
    assert text().count("LPA02 MANUAL") == 1
    con.io.tick(4)                                        # 15 s: still manual, reminded
    assert text().count("LPA02 MANUAL") == 2 and not req.done
    con.io.tick(11)                                       # 50 s later: now automatic
    assert req.done and con.m.printer.lines == ["LINE"]


def test_requests_wait_their_turn_by_priority():
    con = console({"notop": 1})
    first = con.print_line("ONE")                         # gets stuck: not operational
    second = con.io.newq(con.lp, 1, "TWO", priority=0x10)
    third = con.io.newq(con.lp, 1, "THREE", priority=0xF0)
    assert [r.buffer for r in con.io.devices[con.lp].queue] == ["TWO", "ONE", "THREE"]
    con.io.device_keyin(con.io.devices[con.lp], "R")
    assert first.done and second.done and third.done
    assert con.m.printer.lines[0] == "TWO"                # higher priority went first
