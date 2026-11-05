"""Python programs as ghost jobs: GJOB, the loader stand-in, the bridge and cpv."""

import threading

import pytest

from tests.test_keyin import started
from uts import pyprog
from uts.devices import ConsoleExhausted
from uts.sched import SNULL, SW

HELLO = '''
def main(cpv):
    cpv.type("HELLO " + cpv.time())
'''

FILES = '''
def main(cpv):
    f = cpv.open("PARTS", fun="OUT")
    for i in range(4):
        f.write(f"P{i}", f"PART {i}")
    try:
        f.write("P1", "AGAIN", new=True)
    except cpv.CpvError as e:
        cpv.type(f"NEWKEY {e.code:02X}")
    f.delete("P2")
    f.close()
    g = cpv.open("PARTS")
    for key, data in g:                     # from the start: no KBUF yet
        cpv.type(key + "=" + data.decode())
    cpv.type(g.read("P3").decode())         # by key; KBUF = P3
    cpv.type(str(g.next()))                 # the next after P3: the end (None)
    try:
        g.read("P2")
    except cpv.CpvError as e:
        cpv.type(f"MISSING {e.code:02X}")
    g.close()
'''

SLEEPER = '''
def main(cpv):
    while True:
        cpv.wait(5)
'''

BROKEN = '''
def main(cpv):
    cpv.type("ABOUT TO FAIL")
    1 / 0
'''


def system(**programs):
    m, mon, con, s = started()
    for name, text in programs.items():
        account = ":SYS"
        if "." in name:
            name, account = name.split(".")
        pyprog.store_source(s.cal.fs, name, account, text)
    m.console.transcript.clear()
    return m, con, s


def keyins(m, con, *lines):
    m.console.replies.extend(lines)                     # the whole script, as --keyins gives it
    while not m.console.at_end():
        try:
            con.interrupt()                             # a key-in; a ghost's read takes its reply
        except ConsoleExhausted:
            break                                       # EH? asks again: no more replies
    return m.console.text()


def log_of(con):
    return dict(con.state.log)


# --- the program file -------------------------------------------------------------------

def test_source_is_an_edit_style_keyed_file():
    m, con, s = system(HELLO=HELLO)
    cfu = s.cal.fs.open("HELLO", ":SYS", "IN")
    kf = cfu.file
    assert kf.KEYM == 3 and kf.check() == []
    first = kf.read_next()
    assert first[0] == pyprog.line_key(1) == bytes([0, 3, 0xE8])   # 1 * 1000
    assert first[1] == b""                              # line 1 is the blank line
    assert pyprog.read_source(s.cal.fs, "HELLO", ":SYS") == HELLO


# --- GJOB -----------------------------------------------------------------------------------

def test_gjob_runs_a_python_program_to_its_end():
    m, con, s = system(HELLO=HELLO)
    text = keyins(m, con, "GJOB HELLO")
    assert "HELLO 13:45 JUN 15,'76" in text
    u = next(int(l.split("user ")[1].split(",")[0]) for l in s.log
             if "T:GJOBSTRT HELLO" in l)
    assert u in s.ended and s.UB_US[u] == SNULL
    assert s.S_CUIS == 2


def test_a_key_in_before_gjob_reuses_keyins_slot_safely():
    m, con, s = system(HELLO=HELLO)
    text = keyins(m, con, "T 14:30", "GJOB HELLO")
    assert "HELLO 14:30" in text                        # regression: KEYIN's user 1 reused


def test_gjob_with_an_account():
    m, con, s = system(**{"HELLO.ALPHA": HELLO})
    text = keyins(m, con, "GJOB HELLO.ALPHA")
    assert "HELLO 13:45" in text
    assert log_of(con)["GJOB HELLO.ALPHA"] == "GJOB HELLO.ALPHA"


@pytest.mark.parametrize("bad", ["GJOB TOOLONGNAME", "GJOB KEYIN", "GJOB HELLO,LP",
                                 "GJOB HELLO/X", "GJOB"])
def test_bad_gjob_key_ins(bad):
    m, con, s = system(HELLO=HELLO)
    keyins(m, con, bad)
    assert log_of(con)[bad] == "EH?"


def test_a_sleeping_task_is_awakened_and_a_full_table_says_so():
    programs = {f"S{i}": SLEEPER for i in range(6)}
    m, con, s = system(**programs)
    text = keyins(m, con, "GJOB S0")
    u = next(int(l.split("user ")[1].split(",")[0]) for l in s.log if "T:GJOBSTRT S0" in l)
    assert s.UB_US[u] == SW
    text = keyins(m, con, "GJOB S0")
    assert "**TASK AWAKENED" in text
    text = keyins(m, con, *[f"GJOB S{i}" for i in range(1, 6)])
    assert "**TASK TABLES FULL" in text


# --- the bridge -------------------------------------------------------------------------------

def test_an_exception_types_a_message_and_aborts():
    m, con, s = system(BROKEN=BROKEN)
    text = keyins(m, con, "GJOB BROKEN")
    assert "ABOUT TO FAIL" in text and "BROKEN ABORTED: ZeroDivisionError" in text
    assert any("T:ABORT user" in l for l in s.log)


def test_a_missing_or_bad_program_fails_to_load():
    m, con, s = system(BAD="def main(cpv)\n    pass\n")
    text = keyins(m, con, "GJOB NOSUCH", "GJOB BAD")
    assert "LOAD NOSUCH: FileError: error X'03'" in text
    assert "LOAD BAD: SyntaxError" in text


def test_zap_aborts_a_running_program_and_its_thread_stops():
    m, mon, con, s = started()
    con.screech = lambda c, sub: ("shut", c)
    pyprog.store_source(s.cal.fs, "S0", ":SYS", SLEEPER)
    before = set(threading.enumerate())
    keyins(m, con, "GJOB S0")
    threads = [t for t in set(threading.enumerate()) - before if t.name == "cpv-S0"]
    assert threads and threads[0].is_alive()
    keyins(m, con, "ZAP")
    threads[0].join(timeout=2)
    assert not threads[0].is_alive() and con.shutdown == ("shut", 0x404)


# --- cpv ----------------------------------------------------------------------------------------

def test_cpv_files_and_errors():
    m, con, s = system(FILES=FILES)
    text = keyins(m, con, "GJOB FILES")
    lines = [l.split(": ", 1)[1] for l in text.splitlines() if ": " in l]
    assert lines == ["NEWKEY 16", "P0=PART 0", "P1=PART 1", "P3=PART 3", "PART 3", "None",
                     "MISSING 43"]
    kf = s.cal.fs.open("PARTS", ":SYS", "IN").file
    assert kf.keys() == ["P0", "P1", "P3"] and kf.check() == []


def test_compute_and_wait_take_clock_time():
    prog = '''
def main(cpv):
    cpv.compute(40)
    cpv.wait(1)
    cpv.type("DONE")
'''
    m, con, s = system(TIMED=prog)
    before = s.now
    text = keyins(m, con, "GJOB TIMED")
    assert "DONE" in text and s.now - before >= 40 + 2 * 600   # WAIT 1: (1 + 1) units


# --- M:KEYIN: asking the operator -----------------------------------------------------------

ASK = '''
def main(cpv):
    answer = cpv.keyin("NAME?")
    cpv.type("GOT " + (answer or "NOTHING"))
'''


def test_keyin_reads_the_operators_reply():
    m, con, s = system(ASK=ASK)
    text = keyins(m, con, "GJOB ASK", "MADHU")
    assert "NAME?MADHU" in text and "GOT MADHU" in text
    assert log_of(con) == {"GJOB ASK": "GJOB ASK.:SYS"}   # the reply wasn't a key-in


def test_the_reply_buffer_holds_a_textc():
    m, con, s = system(ASK=ASK)
    keyins(m, con, "GJOB ASK", "ABC")
    u = next(int(l.split("user ")[1].split(",")[0]) for l in s.log if "T:GJOBSTRT ASK" in l)
    buf = s.cal.read_text(u, pyprog.Cpv.BUF, 0, 4)
    assert buf == "\x03ABC"                                # length in byte 0 (ARS), BTD 1


def test_two_ghosts_are_answered_in_the_order_they_asked():
    m, con, s = system(A=ASK.replace("GOT", "A GOT"), B=ASK.replace("GOT", "B GOT"))
    s.t_gjobstrt("A")
    s.t_gjobstrt("B")
    m.console.replies.extend(["FIRST", "SECOND"])
    con.run_sched()
    lines = [l for l in m.console.text().splitlines() if ": " in l]
    first = next(l for l in lines if l.endswith("NAME?FIRST"))
    second = next(l for l in lines if l.endswith("NAME?SECOND"))
    assert lines.index(first) < lines.index(second)    # one question at a time, in turn
    who = {first.split(":")[0]: "FIRST", second.split(":")[0]: "SECOND"}
    assert len(who) == 2                                # two different ghosts
    for ident, answer in who.items():                   # each got the answer to its own question
        assert any(l.startswith(ident + ": ") and l.endswith("GOT " + answer) for l in lines)


def test_no_more_console_input_gives_an_empty_reply():
    m, con, s = system(ASK=ASK)
    text = keyins(m, con, "GJOB ASK")
    assert "GOT NOTHING" in text


def test_the_reply_is_cut_to_the_size():
    prog = '''
def main(cpv):
    cpv.type("GOT " + cpv.keyin("LONG?", size=5))
'''
    m, con, s = system(SHORT=prog)
    text = keyins(m, con, "GJOB SHORT", "ABCDEFGH")
    assert "GOT ABCD" in text and "GOT ABCDE" not in text


# --- binary keys ---------------------------------------------------------------------------

BINKEYS = '''
def main(cpv):
    f = cpv.open("LINES", fun="OUT", keym=3)
    for n in (20, 3, 100, 1):                       # EDIT keys, out of order
        f.write(cpv.line_key(n), f"LINE {n}")
    f.write(bytes([0, 0xFF, 0x15]), "ODD BYTES")    # any byte values
    f.close()
    g = cpv.open("LINES", binary_keys=True)
    for key, data in g:
        cpv.type(key.hex() + " " + data.decode())
    cpv.type(g.read(cpv.line_key(3)).decode())
    cpv.type(g.read(bytes([0, 0xFF, 0x15])).decode())
    g.close()
    h = cpv.open("BINKEYS", binary_keys=True)       # this program's own source, by EDIT key
    cpv.type(h.read(cpv.line_key(2)).decode(cpv.EBCDIC).strip())
'''


def test_binary_keys():
    m, con, s = system(BINKEYS=BINKEYS)
    text = keyins(m, con, "GJOB BINKEYS")
    lines = [l.split(": ", 1)[1] for l in text.splitlines() if ": " in l]
    assert lines == ["0003e8 LINE 1", "000bb8 LINE 3", "004e20 LINE 20",
                     "00ff15 ODD BYTES", "0186a0 LINE 100",     # in byte order
                     "LINE 3", "ODD BYTES", "def main(cpv):"]   # line 1 is blank
    kf = s.cal.fs.open("LINES", ":SYS", "IN").file
    assert kf.read(bytes([0, 0xFF, 0x15])) == "ODD BYTES".encode("cp037") and kf.check() == []
