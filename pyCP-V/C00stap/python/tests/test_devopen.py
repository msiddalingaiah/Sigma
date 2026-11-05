"""OPEN of a device DCB (uts/devopen.py): the label or name in word 1, the FPT's device
option, and the assignment tables by kind of user; and an interpreted program's
device DCBs on a terminal."""

import pytest

from tests.test_online import logged_on
from uts import devopen
from uts.asm import assemble
from uts.fetch import write_load_module
from uts.monitor import NotTranslated


class Users:
    """Just what devopen.kind_of_user reads."""

    def __init__(self, online=(), ghosts=()):
        self.LB_UN, self.SB_GJOBUN = list(online), list(ghosts)


ONLINE, GHOST, BATCH = Users(online=[5]), Users(ghosts=[5]), Users()
ME_TEXT = 0x0001D4C5                    # word 1: X'10000', X'8000', X'4000' and 'ME'


@pytest.mark.parametrize("users, label, device", [
    (ONLINE, 9, "ME"),                  # SI: the terminal (P2OPL.txt:72-:78)
    (ONLINE, 2, "ME"),                  # OC too, on-line
    (ONLINE, 6, "NO"),                  # PO: no entry, the null device
    (GHOST, 9, "TY"),                   # SI for a ghost: the console (:81-:87)
    (GHOST, 2, "TY"),
    (BATCH, 2, "TY"),                   # OC for batch (:63-:69)
])
def test_labels_resolve_by_kind_of_user(users, label, device):
    assert devopen.resolve(users, 5, 0x00020000 | label) == device


def test_names_and_device_options():
    assert devopen.resolve(ONLINE, 5, ME_TEXT) == "ME"
    assert devopen.resolve(GHOST, 5, ME_TEXT) == "TY"    # ME's ghost entry is TY
    with pytest.raises(devopen.OpenError) as e:          # CR: no device can be had
        devopen.resolve(ONLINE, 5, 0x00020009, option=0xC3D9)
    assert (e.value.code, e.value.sub) == (0x49, 0x02)
    assert devopen.resolve(ONLINE, 5, 0x00020009, option=0xD3D6) == "ME"   # 'LO'


def test_errors_and_what_is_not_translated():
    with pytest.raises(devopen.OpenError) as e:
        devopen.resolve(ONLINE, 5, 0x00020013)            # label 19: out of range
    assert e.value.code == 0x14
    with pytest.raises(devopen.OpenError):
        devopen.resolve(ONLINE, 5, 0x0001E7E7)            # 'XX': no such name
    with pytest.raises(NotTranslated, match="symbiont"):
        devopen.resolve(GHOST, 5, 0x00020003)             # LO for a ghost: L1
    with pytest.raises(NotTranslated, match="DCT index"):
        devopen.resolve(ONLINE, 5, 0x00028103)            # type and DCT already


DEVICE = """
* Open M:LO (op label 3) and write a line on it; then a write on M:DO, which isn't
* opened first: the write opens it (a default OPEN)
         ORG      X'D000'
START    CAL1,1   OPEN
         CAL1,1   WRITE
         CAL1,1   WRITE2
         CAL1,9   1
OPEN     DATA     X'14000000'+M:LO,0
WRITE    DATA     X'11000000'+M:LO,X'30000000',MSG,14
WRITE2   DATA     X'11000000'+M:DO,X'30000000',MSG2,7
MSG      TEXT     'LISTING OUTPUT '
MSG2     TEXT     'DIAGOUT '
M:LO     DATA     X'33000003',X'00040003',0,0,0,0,0,0,0,0,0,0,0,0,0,0
M:DO     DATA     X'33000003',X'00040005',0,0,0,0,0,0,0,0,0,0,0,0,0,0
         END      START
"""


ECHO = """
* Read a line from M:SI (the terminal, on-line) and write it back on M:LO, with a prefix
         ORG      X'D000'
START    CAL1,1   READ
         CAL1,1   WRITE
         CAL1,9   1
READ     DATA     X'10000000'+M:SI,X'30000000',BUF,20
WRITE    DATA     X'11000000'+M:LO,X'30000000',OUT,24
OUT      TEXT     'GOT '
BUF      TEXT     '                    '
M:SI     DATA     X'33000003',X'00020009',0,0,0,0,0,0,0,0,0,0,0,0,0,0
M:LO     DATA     X'33000003',X'00040003',0,0,0,0,0,0,0,0,0,0,0,0,0,0
         END      START
"""


def test_text_in_memory_is_ebcdic():
    t = logged_on()
    dcbs = {}
    words, start = assemble(ECHO, dcbs)
    write_load_module(t.s.cal.fs, "ECHO", ":SYS", words, start, dcbs)
    t.type("ECHO\r")
    t.type("Hello, 42!\r")                               # typed in ASCII
    assert t.text() == "ECHO\r\nHello, 42!\r\nGOT Hello, 42!          \r\n!"
    out = next(a for a, w in words.items() if w == int.from_bytes("GOT ".encode("cp037"), "big"))
    buf = t.s.cal.read_bytes(t.s.LB_UN[0], out + 1, 0, 10)   # BUF follows OUT's one word
    assert buf == "Hello, 42!".encode("cp037")           # in memory: EBCDIC (TTYIN's role)


def test_a_program_writes_on_device_dcbs():
    t = logged_on()
    dcbs = {}
    words, start = assemble(DEVICE, dcbs)
    write_load_module(t.s.cal.fs, "DEVS", ":SYS", words, start, dcbs)
    t.type("DEVS\r")
    assert t.text() == "DEVS\r\nLISTING OUTPUT\r\nDIAGOUT\r\n!"
    opens = [line for line in t.s.log if ": device ME" in line]
    assert len(opens) == 2                               # M:LO by M:OPEN, M:DO by its write


SERVICES = """
* M:DEVICE VFC on M:LO, then two records with format controls (X'C2': two new lines;
* '1', X'F1': top of form); M:CORRES of M:LO and M:DO (both ME) into R8 -> R9; M:INT;
* T:CHTBL set mode (X'20')
         ORG      X'D000'
START    CAL1,1   VFC
         CAL1,1   W1
         CAL1,1   W2
         CAL1,1   CORRES
         LW,9     8
         CAL1,8   INT
         CAL1,8   CHTBL
         CAL1,9   1
VFC      DATA     X'05000000'+M:LO,X'00000010'
W1       DATA     X'11000000'+M:LO,X'30000000',T1,4
W2       DATA     X'11000000'+M:LO,X'30000000',T2,4
CORRES   DATA     X'2B000000'+M:LO,M:DO
INT      DATA     X'0E000000'+START
CHTBL    DATA     X'06200000',0
T1       DATA     X'C2C1C2C3'
T2       TEXT     '1XYZ'
M:LO     DATA     X'33000003',X'00040003',0,0,0,0,0,0,0,0,0,0,0,0,0,0
M:DO     DATA     X'33000003',X'00040005',0,0,0,0,0,0,0,0,0,0,0,0,0,0
         END      START
"""


def test_vfc_corres_int_and_chtbl():
    t = logged_on()
    dcbs = {}
    words, start = assemble(SERVICES, dcbs)
    write_load_module(t.s.cal.fs, "SERVS", ":SYS", words, start, dcbs)
    t.type("SERVS\r")
    assert t.text() == "SERVS\r\n\r\nABC\r\nXYZ\r\n!"     # X'C2': a blank line; '1': a new one
    u = t.s.LB_UN[0]
    assert t.s.uregs[u][9] == 1                           # M:LO and M:DO: the same, ME
    assert t.s.cal.intent[u] == 0x08000000 | start        # J:INTENT
