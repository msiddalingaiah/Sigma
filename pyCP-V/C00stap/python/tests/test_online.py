"""On-line users: COC (uts/coc.py), the LOGON and TEL stand-ins (uts/online.py) and
the telnet terminals (uts/terminals.py)."""

import os
import socket
import time

import pytest

from tests.test_interp import HELLO as HELLO_S
from tests.test_pyprog import HELLO, system
from uts.asm import assemble
from uts.coc import Coc
from uts.fetch import write_load_module
from uts.online import Online
from uts.terminals import BRK, DO, ECHO, IAC, SGA, WILL, TerminalServer

ASK = '''
def main(cpv):
    cpv.prompt("?")
    name = cpv.readline()
    cpv.type("HELLO, " + name)
'''

QUESTION = '''
def main(cpv):
    cpv.type("THEN " + cpv.keyin("COLOUR?"))
'''

MAKE = '''
def main(cpv):
    f = cpv.open("NOTES", fun="OUT")
    f.write("K1", "A NOTE")
    f.close()
    cpv.type("MADE")
'''

LOOP = '''
def main(cpv):
    while True:
        cpv.compute(5)
'''


class Terminal:
    """One line, driven in-process: the characters in, the output collected."""

    def __init__(self, line=0, **programs):
        self.m, self.con, self.s = system(**programs)
        self.coc = Coc(self.s)
        self.online = Online(self.s)
        self.line, self.out = line, bytearray()

    def run(self, units=500):
        self.s.run(until=self.s.now + units)

    def connect(self):
        self.coc.ready(self.line, self.out.extend)
        self.run()
        return self

    def type(self, text):
        for c in text.encode("latin-1"):
            self.coc.input(self.line, c)
        self.run()

    def text(self):
        t = self.out.decode("latin-1")
        self.out.clear()
        return t

    def user(self):
        return self.coc.user(self.line)


def logged_on(**programs):
    t = Terminal(**programs).connect()
    t.type("BOB,ROBERT\r")
    t.text()
    return t


# --- LOGON -----------------------------------------------------------------------------

def test_a_connection_logs_on_and_gets_tel():
    t = Terminal().connect()
    assert t.user() and t.online.acp[t.user()] == "LOGON"
    greeting = t.text()
    assert greeting.startswith("XEROX CP-V AT YOUR SERVICE\r\nON AT 13:45 JUN 15,'76\r\n")
    assert greeting.endswith("LOGON PLEASE: ")      # the reply on the same line
    t.type("bob,robert\r")
    assert t.text() == "bob,robert\r\n!"            # echoed, then TEL's prompt
    u = t.user()
    assert t.online.acp[u] == "TEL" and t.s.cal.account[u] == "BOB"
    assert any("STEP041" in line for line in t.s.log)


def test_bad_ids_and_three_tries():
    t = Terminal().connect()
    t.text()
    t.type("NOCOMMA\r")
    assert t.text() == "NOCOMMA\r\nID?\r\nLOGON PLEASE: "
    t.type("TOO LONG ACCOUNT,X\r")
    assert t.text().endswith("ACCOUNT?\r\nLOGON PLEASE: ")
    u = t.user()
    t.type(",X\r")
    assert t.text().endswith("SORRY, UNABLE TO LOG YOU ON")
    assert t.user() == 0 and u not in t.s.LB_UN
    assert any("STEP10" in line for line in t.s.log)


# --- TEL -------------------------------------------------------------------------------

def test_tel_runs_programs_and_comes_back():
    t = logged_on(HELLO=HELLO)
    t.type("HELLO\r")
    assert t.text() == "HELLO\r\nHELLO 13:45 JUN 15,'76\r\n!"
    t.type("RUN HELLO\r")
    assert "HELLO 13:45" in t.text()
    t.type("RUN NOPE\r")
    assert t.text() == "RUN NOPE\r\nNOPE NOT FOUND\r\n!"
    t.type("WHAT IS THIS\r")
    assert t.text() == "WHAT IS THIS\r\nEH?\r\n!"


def test_tel_runs_machine_code():
    t = logged_on()
    dcbs = {}
    words, start = assemble(HELLO_S, dcbs)
    write_load_module(t.s.cal.fs, "HELLOS", ":SYS", words, start, dcbs)
    t.type("HELLOS\r")
    assert t.text().count("HELLO FROM SIGMA CODE") == 3


def test_list_shows_the_accounts_files():
    t = logged_on(**{"HELLO.BOB": HELLO})
    t.type("LIST\r")
    assert t.text() == "LIST\r\nHELLO\r\n!"
    t.type("HELLO\r")                                   # from the user's own account
    assert "HELLO 13:45" in t.text()


def test_a_program_works_in_the_users_account():
    t = logged_on(MAKE=MAKE)                            # MAKE is in :SYS
    t.type("MAKE\r")
    assert "MADE" in t.text()
    t.type("LIST\r")
    assert t.text() == "LIST\r\nNOTES\r\n!"             # the file went into BOB's account
    assert t.s.cal.fs.files("BOB") == ["NOTES"] and "NOTES" not in t.s.cal.fs.files(":SYS")


def test_off_removes_the_user():
    t = logged_on()
    u = t.user()
    t.type("OFF\r")
    assert t.user() == 0 and u not in t.s.LB_UN
    assert any(f"T:DELUS user {u}" in line for line in t.s.log)


def test_a_program_reads_the_terminal():
    t = logged_on(ASK=ASK)
    t.type("ASK\r")
    assert t.text() == "ASK\r\n?"                       # the program's prompt
    t.type("ADA\r")
    assert t.text() == "ADA\r\nHELLO, ADA\r\n!"


def test_keyin_on_line_asks_the_terminal():
    t = logged_on(COLOUR=QUESTION)
    t.type("COLOUR\r")
    assert t.text() == "COLOUR\r\nCOLOUR?"
    t.type("BLUE\r")
    assert t.text() == "BLUE\r\nTHEN BLUE\r\n!"
    t.type("LIST\r")                                    # M:UC's BTD was put back
    assert t.text() == "LIST\r\nNO FILES IN DIRECTORY\r\n!"
    t.type("OFF\r")
    assert t.user() == 0


# --- COC: editing, type-ahead, BREAK, hang-up -------------------------------------------

def test_backspace_rubout_and_ctrl_x():
    t = logged_on()
    t.type("LIZ\bST\r")
    assert t.text() == "LIZ\b \bST\r\nNO FILES IN DIRECTORY\r\n!"
    t.type("JUNK\x7f\x7f\x7f\x7f\x7f")                  # rubout past the start: nothing
    assert t.text() == "JUNK" + "\b \b" * 4
    t.type("MORE\x18")                                  # Ctrl-X: the line is gone
    assert t.text() == "MORE_\r\n"
    t.type("LIST\r")
    assert "NO FILES" in t.text()


def test_type_ahead_is_echoed_when_the_read_starts():
    t = logged_on(LOOP=LOOP)
    t.type("LOOP\r")
    t.text()
    t.type("LIST\r")                                    # nobody reads: not echoed yet
    assert t.text() == ""
    t.coc.brk(t.line)                                   # BREAK: back to TEL, input dropped
    t.run()
    assert t.text() == "!"
    assert any("BREAK user" in line for line in t.s.log)


def test_break_on_a_running_program_returns_to_tel():
    t = logged_on(LOOP=LOOP)
    u = t.user()
    t.type("LOOP\r")
    t.text()
    t.type("\x19")                                      # Ctrl-Y, as a BREAK
    assert t.text() == "!" and t.online.acp[u] == "TEL"
    t.type("LIST\r")
    assert "NO FILES" in t.text()


def test_hang_up_removes_the_user():
    t = logged_on(LOOP=LOOP)
    u = t.user()
    t.type("LOOP\r")
    t.coc.drop(t.line)
    t.run()
    assert t.user() == 0 and u not in t.s.LB_UN


def test_input_on_a_line_without_a_user_is_dropped():
    t = Terminal()
    t.coc.input(0, ord("X"))
    assert t.coc.lines[0].typed == [] and t.out == b""


# --- telnet ----------------------------------------------------------------------------

def pump(t, server, client, until, timeout=5.0):
    """Run the server and the scheduler until the client has received ``until``."""
    got, end = b"", time.monotonic() + timeout
    while until not in got and time.monotonic() < end:
        server.poll(0.01)
        t.run(50)
        server.flush()
        try:
            got += client.recv(4096)
        except BlockingIOError:
            pass
    return got


def test_telnet_session():
    t = Terminal(HELLO=HELLO)
    server = TerminalServer(t.coc, port=0)
    try:
        client = socket.create_connection(server.address)
        client.setblocking(False)
        got = pump(t, server, client, b"LOGON PLEASE: ")
        assert got.startswith(bytes([IAC, WILL, ECHO, IAC, WILL, SGA, IAC, DO, SGA]))
        assert b"XEROX CP-V AT YOUR SERVICE" in got
        client.sendall(bytes([IAC, DO, 31]) + b"BOB,ROBERT\r\0")   # NAWS refused; CR NUL
        got = pump(t, server, client, b"!")
        assert bytes([IAC, 252, 31]) in got and b"BOB,ROBERT\r\n!" in got
        client.sendall(b"HELLO\r\n")
        assert b"HELLO 13:45" in pump(t, server, client, b"\r\n!")
        client.sendall(b"LOOP" + bytes([IAC, BRK]))                 # BREAK on a half line
        assert pump(t, server, client, b"!").endswith(b"!")
        client.sendall(b"OFF\r")
        got = pump(t, server, client, b"\r\n", timeout=1.0)
        for _ in range(20):
            server.poll(0.01)
            t.run(50)
            server.flush()
        assert not server.conns
        client.close()
    finally:
        server.close()


def test_telnet_disconnect_and_busy_lines():
    t = Terminal()
    server = TerminalServer(t.coc, port=0)
    try:
        clients = []
        for _ in range(len(t.coc.lines)):
            c = socket.create_connection(server.address)
            c.setblocking(False)
            clients.append(c)
            pump(t, server, c, b"LOGON PLEASE: ")
        extra = socket.create_connection(server.address)
        server.poll(0.05)
        extra.settimeout(2.0)
        assert b"ALL LINES BUSY" in extra.recv(100)
        extra.close()
        users = [t.coc.user(n) for n in range(len(t.coc.lines))]
        assert all(users)
        clients[0].close()                              # a hang-up: E:OFF
        for _ in range(20):
            server.poll(0.01)
            t.run(50)
        assert t.coc.user(0) == 0 and users[0] not in t.s.LB_UN
        for c in clients[1:]:
            c.close()
    finally:
        server.close()


# --- COPY (PCL) ------------------------------------------------------------------------

def test_copy_types_a_file_on_the_terminal():
    t = logged_on(MAKE=MAKE)
    t.type("MAKE\r")
    t.text()
    t.type("COPY NOTES\r")                              # on-line, the output is ME
    assert t.text() == "COPY NOTES\r\nA NOTE\r\n!"
    t.type("COPY NOTES TO ME\r")
    assert t.text() == "COPY NOTES TO ME\r\nA NOTE\r\n!"
    t.type("C NOTES OVER ME\r")
    assert t.text() == "C NOTES OVER ME\r\nA NOTE\r\n!"
    t.type("L\r")
    assert t.text() == "L\r\nNOTES\r\n!"


def test_copy_an_edit_file_from_another_account():
    t = logged_on(MAKE=MAKE)
    t.type("COPY MAKE.:SYS\r")                          # EBCDIC lines, shown as text
    out = t.text()
    assert "def main(cpv):" in out and 'cpv.type("MADE")' in out


def test_copy_errors():
    t = logged_on()
    t.type("COPY NOPE\r")
    assert "COPY: CAN'T OPEN NOPE: CODE" in t.text()
    t.type("COPY NOPE TO LP\r")
    assert "COPY: ONLY TO ME, NOT LP" in t.text()
    t.type("COPY A B C\r")
    assert "COPY: SYNTAX ERROR" in t.text()
    t.type("L\r")
    assert t.text() == "L\r\nNO FILES IN DIRECTORY\r\n!"


def test_copy_with_k_numbers_edit_lines():
    t = logged_on(MKEDIT=open("examples/mkedit.py").read())
    t.type("MKEDIT\r")
    out = t.text()
    assert "   1.000 THE SIGMA HUMS IN THE MACHINE ROOM" in out
    assert "   2.500 (INSERTED AT 2.5)" in out and "WROTE POEM: 5 LINES" in out
    t.type("COPY POEM TO ME(K)\r")                       # PCL's K option: WRITE3
    assert t.text().splitlines()[1:] == [
        "     1 -    1.000 THE SIGMA HUMS IN THE MACHINE ROOM",
        "     2 -    2.000 ITS DISCS SPIN AND ITS LIGHTS BLINK",
        "     3 -    2.500 (INSERTED AT 2.5)",
        "     4 -    3.000 A USER LOGS ON AT A TELETYPE",
        "     5 -    5.000 AND TYPES A LINE TO SEE WHAT IT WILL THINK",
        "!"]
    t.type("COPY POEM\r")                                # no K: the records only
    assert t.text().splitlines()[1] == "THE SIGMA HUMS IN THE MACHINE ROOM"


def test_copy_with_x_dumps_records_in_hex():
    t = logged_on()
    dcbs = {}
    words, start = assemble(HELLO_S, dcbs)
    write_load_module(t.s.cal.fs, "HELLOS", "BOB", words, start, dcbs)
    t.type("COPY HELLOS TO ME(X)\r")                     # HEXDUMP.txt
    lines = t.text().splitlines()
    assert lines[1:4] == [" ", "KEY= HEAD     -       48 BYTES", " "]      # a load module
    assert lines[4] == "00000    8000FF30   8000D000   68076800   01006800"
    i = lines.index("KEY= X'C8C5D3D3D6E203'    -      120 BYTES")      # HELLOS + 03: data
    assert lines[i + 2] == "00000    22500003   0420D004   6450D001   04900001"
    assert "KEY= TREE     -       48 BYTES" in lines
    t.type("COPY HELLOS TO ME(X,K)\r")                   # X before K (READ20)
    assert "KEY= HEAD     -       48 BYTES" in t.text()
    t.type("COPY HELLOS TO ME(Q)\r")
    assert "COPY: SYNTAX ERROR" in t.text()


UTIL_TAPE = os.path.join(os.path.dirname(__file__), "..", "..", "c00si", "sw-lib-utility-pgm-util.tap")


@pytest.mark.skipif(not os.path.exists(UTIL_TAPE), reason="the UTIL tape image isn't here")
def test_copy_shows_a_restored_load_module():
    from uts import labtape
    t = logged_on()
    with open(UTIL_TAPE, "rb") as f:
        labtape.restore(t.s.cal.fs, labtape.read_tape(f.read()))
    t.type("COPY SLIP.:UTIL TO ME(X)\r")
    lines = t.text().splitlines()
    assert lines[2:5] == ["KEY= HEAD     -       48 BYTES", " ",
                          "00000    8000FF30   8000A064   50005000   04005000"]
    assert "KEY= TREE     -       48 BYTES" in lines
    t.type("COPY JCL:LOAD:SLIP.:UTIL TO ME(K)\r")
    assert "     3 -    3.000 !LOAD (LMN,SLIP),(EF,(CDTBO),(VFYBO),(CPYBO)),(MAP),(SL,F),(PERM)" \
        in t.text().splitlines()


@pytest.mark.skipif(not os.path.exists(UTIL_TAPE), reason="the UTIL tape image isn't here")
def test_list_another_account_with_attributes():
    from uts import labtape
    t = logged_on()
    with open(UTIL_TAPE, "rb") as f:
        labtape.restore(t.s.cal.fs, labtape.read_tape(f.read()))
    t.type("L .:UTIL\r")                                 # COPYTRAN's file id form A
    assert "SLIP" in t.text().splitlines()
    t.type("L .:UTIL(A)\r")                              # PCLLIST: the attributes
    lines = t.text().splitlines()
    assert lines[1] == "ORG    GRAN     REC     DATE    NAME"
    assert "K               6               SLIP" in lines       # a load module: keyed
    assert "C               36              CDTBO" in lines      # a ROM: consecutive
    t.type("L SLIP.:UTIL(A)\r")
    assert t.text().splitlines()[1:] == ["ORG    GRAN     REC     DATE    NAME",
                                         "K               6               SLIP", "!"]


@pytest.mark.skipif(not os.path.exists(UTIL_TAPE), reason="the UTIL tape image isn't here")
def test_tel_runs_slip_to_its_error_routine():
    from uts import labtape
    t = logged_on()
    with open(UTIL_TAPE, "rb") as f:
        labtape.restore(t.s.cal.fs, labtape.read_tape(f.read()))
    t.type("SLIP.:UTIL\r")                               # FETCH; M:OPEN M:SI on CR fails
    assert t.text() == "SLIP.:UTIL\r\n!"
    log = "\n".join(t.s.log)
    assert "OPEN DCB X'A922' user 7: device error X'49'-02" in log   # no deck in the reader
    assert "routine X'A0F0'" in log                       # SLIP's I/O error routine
    assert "OPEN DCB X'A9E4' user 7: ASN 3 -> 1" in log   # F:3: ERRMSG.:SYS, the FPT's file
    assert "abnormal X'03' on DCB X'A9E4'" in log         # ... which isn't here
    assert "OPEN DCB X'A8BA' user 7: device ME" in log    # M:LL, a default open: M:PRINT
