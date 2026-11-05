"""OPEN of a device DCB (uts/devopen.py): the label or name in word 1, the FPT's device
option, and the assignment tables by kind of user; and an interpreted program's
device DCBs on a terminal."""

import pytest

from tests.test_online import logged_on
from uts import devopen
from uts.asm import assemble
from uts.interp import store_image
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


def test_a_program_writes_on_device_dcbs():
    t = logged_on()
    dcbs = {}
    words, start = assemble(DEVICE, dcbs)
    store_image(t.s.cal.fs, "DEVS", ":SYS", words, start, dcbs)
    t.type("DEVS\r")
    assert t.text() == "DEVS\r\nLISTING OUTPUT\r\nDIAGOUT\r\n!"
    opens = [line for line in t.s.log if ": device ME" in line]
    assert len(opens) == 2                               # M:LO by M:OPEN, M:DO by its write
