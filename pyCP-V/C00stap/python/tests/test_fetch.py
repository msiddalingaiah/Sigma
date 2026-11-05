"""FETCH (uts/fetch.py): a load module into memory. Small load modules built here
check the checks; the UTIL tape's SLIP, when the image is present, the real thing."""

import os

import pytest

from uts import fetch, labtape
from uts.files import EBCDIC, Disc, FileSystem
from uts.monitor import NotTranslated

UTIL = os.path.join(os.path.dirname(__file__), "..", "..", "c00si", "sw-lib-utility-pgm-util.tap")


def words(*ws):
    return b"".join((w & 0xFFFFFFFF).to_bytes(4, "big") for w in ws)


def load_module(fs, name="PROG", head0=0x8000FF30, tree_size=12, dcbs=True):
    """A one-segment load module: data at word X'A000' (the TCB, whose word 10 points
    at the DCB table at X'A800'), procedure at X'AC00', a DCB M:SI at X'A810'."""
    seg = name.encode(EBCDIC)
    data = words(*([0] * 10 + [0xA800] + [0] * 89), 0x0410A1DE)       # 101 words
    table = words(0xA806, 0x03D47A5C, 0xA828,                        # M:* (the CFU area)
                  0x04D47AE2, 0xC9000000, 0xA810, 0)                 # M:SI -> X'A810'
    dcb = table.ljust(16 * 4, bytes(1)) + words(0x33000003, 0x00020009)
    tree = words(tree_size, (len(seg) << 24) | int.from_bytes(seg[:3], "big"),
                 int.from_bytes(seg[3:7].ljust(4, b"\x40"), "big"), 0x40404040, 0, 0,
                 (len(data) // 8 + 1) << 16 | 0x5000, 0, 0x00015600, 0,
                 (len(dcb) // 8 << 16 | 0x5400) if dcbs else 0, 0)
    head = words(head0, 0x8000A064, 0x50005000, 0x04005000, 0x01005600, 0, 0x02005400,
                 0, 0, 0, 0, 0)
    fs.add_account(":T")
    cfu = fs.open(name, ":T", "OUT", keym=15)
    for key, rec in ((b"HEAD", head), (b"TREE", tree), (bytes([3]), data.ljust(len(data) + 4, bytes(1))),
                     (bytes([5]), words(0, 0)), (bytes([7]), dcb)):
        cfu.file.write(key.decode("latin-1").encode(EBCDIC) if key in (b"HEAD", b"TREE")
                       else seg + key, rec)
    fs.close(cfu)


def test_a_load_module_is_fetched():
    fs = FileSystem(Disc(512))
    load_module(fs)
    assert fetch.is_load_module(fs, "PROG", ":T")
    lm = fetch.read_load_module(fs, "PROG", ":T")
    assert (lm.start, lm.tcb, lm.dcblink) == (0xA064, 0xA000, 0xA800)
    assert lm.words[0xA064] == 0x0410A1DE and lm.words[0xA00A] == 0xA800
    assert lm.words[0xA811] == 0x00020009                # the DCB section, at its bias
    assert lm.dcbs == {"M:SI": 0xA810}                   # M:* isn't a DCB (CALPROC.txt:166)


@pytest.mark.parametrize("head0, code", [(0x8000FF20, fetch.SMALLHEAD), (0x0800FF30, fetch.BADHEAD)])
def test_a_bad_head_is_refused(head0, code):
    fs = FileSystem(Disc(512))
    load_module(fs, head0=head0)
    if head0 & 0xFF != 0x30:                             # the record is 48 bytes; fake a short one
        cfu = fs.open("PROG", ":T", "UPDATE")
        cfu.file.write("HEAD".encode(EBCDIC), words(head0, 0, 0))
        fs.close(cfu)
    with pytest.raises(fetch.LoadModuleError) as e:
        fetch.read_load_module(fs, "PROG", ":T")
    assert e.value.code == code


def test_overlays_and_other_files():
    fs = FileSystem(Disc(512))
    load_module(fs, tree_size=23)
    with pytest.raises(NotTranslated, match="M:SEGLD"):
        fetch.read_load_module(fs, "PROG", ":T")
    cfu = fs.open("TEXT", ":T", "OUT", keym=3)
    cfu.file.write((1000).to_bytes(3, "big"), b"LINE")
    fs.close(cfu)
    assert not fetch.is_load_module(fs, "TEXT", ":T")
    assert not fetch.is_load_module(fs, "NONE", ":T")


@pytest.mark.skipif(not os.path.exists(UTIL), reason="the UTIL tape image isn't here")
def test_slip_from_the_util_tape():
    fs = FileSystem(Disc(2048))
    with open(UTIL, "rb") as f:
        tape = labtape.read_tape(f.read())
    labtape.restore(fs, tape)
    lm = fetch.read_load_module(fs, "SLIP", ":UTIL")
    assert (lm.start, lm.tcb, lm.dcblink) == (0xA064, 0xA000, 0xA800)
    assert list(lm.dcbs)[:3] == ["M:DO", "F:1", "F:2"] and lm.dcbs["M:SI"] == 0xA922
    records = dict({f.name: f for f in tape.files}["SLIP"].records)
    data = records["SLIP".encode(EBCDIC) + bytes([3])]
    assert all(lm.words[0xA000 + i] == int.from_bytes(data[4 * i:4 * i + 4], "big")
               for i in range(len(data) // 4))
    assert lm.words[0xA064] >> 20 == 0x041               # it starts with a CAL1,1: M:OPEN M:SI
