"""TEL's processor command and the assign/merge record (docs/assign.md)."""

import os

import pytest

from tests.test_online import C00_TAPE, logged_on
from uts import assign, pyprog
from uts.files import EBCDIC, Position


def sets(t, u):
    return {name: plist for name, plist in t.s.cal.amr.get(u, [])}


def plist_name(plist):
    """The name VLP of a file set: its TEXTC after the control word (word 5)."""
    data = b"".join(w.to_bytes(4, "big") for w in plist[6:9])
    return data[1:1 + data[0]].decode(EBCDIC)


def test_source_over_object_and_listing():
    t = logged_on()
    u, cal = t.user(), t.s.cal
    message, given = assign.parse(cal, u, "SRC OVER OBJ,LST", "BOB")
    assert message is None and given
    s = sets(t, u)
    assert s["M:SI"][:5] == [0x14000000, 0x0000E001, 0x01400000, 1, 2]   # IN, SAVE
    assert s["M:GO"][3] == s["M:LO"][3] == 2                              # OUT
    assert [plist_name(s[n]) for n in ("M:SI", "M:GO", "M:LO")] == ["SRC", "OBJ", "LST"]
    assert cal.stdopt[u] == assign.OPT_GO | assign.OPT_LO
    assign.step(cal, u, given, "BOB")
    assert cal.jopt[u] == assign.OPT_GO | assign.OPT_LO | assign.OPT_SI


def test_listing_to_the_terminal_is_a_device_set():
    t = logged_on()
    u = t.user()
    assign.parse(t.s.cal, u, "SRC OVER OBJ,ME", "BOB")
    assert sets(t, u)["M:LO"] == [0x14000000, 0x0000A000, 0x00040000, 0xE4C3]   # 'UC'


def test_without_an_object_the_default_go_file():
    t = logged_on()
    u, cal = t.user(), t.s.cal
    _, given = assign.parse(cal, u, "SRC", "BOB")
    assign.step(cal, u, given, "BOB")
    name = plist_name(sets(t, u)["M:GO"])
    assert name == assign.default_name(u) and name.encode(EBCDIC)[2:] == b"\xC7"   # 'G'


def test_sets_stay_but_the_source_is_released():
    t = logged_on()
    u, cal = t.user(), t.s.cal
    _, given = assign.parse(cal, u, "SRC OVER OBJ", "BOB")
    assign.step(cal, u, given, "BOB")
    assign.step(cal, u, False, "BOB")                  # the next command gave no source
    s = sets(t, u)
    assert "M:SI" not in s and plist_name(s["M:GO"]) == "OBJ"


def test_on_an_existing_file_drops_the_command():
    t = logged_on()
    u, cal = t.user(), t.s.cal
    pyprog.store_source(cal.fs, "OBJ", "BOB", "X")
    assign.parse(cal, u, "A OVER B", "BOB")
    before = list(cal.amr[u]), cal.stdopt[u]
    message, _ = assign.parse(cal, u, "SRC ON OBJ", "BOB")
    assert message == "ON FILE OBJ ILLEGAL"
    assert (cal.amr[u], cal.stdopt[u]) == before       # SYN1: as before the command


def test_a_syntax_error_keeps_what_was_parsed():
    t = logged_on()
    u = t.user()
    message, given = assign.parse(t.s.cal, u, "SRC OVER ME", "BOB")   # ERRME: ignored
    assert message is None and given and "M:GO" not in sets(t, u)
    message, _ = assign.parse(t.s.cal, u, "ONE TWO", "BOB")           # two sources
    assert message is None and plist_name(sets(t, u)["M:SI"]) == "ONE"


@pytest.mark.skipif(not os.path.exists(C00_TAPE), reason="the C00 boot tape image isn't here")
def test_ap_reads_a_file_and_writes_its_object_and_listing():
    from uts import labtape
    t = logged_on()
    with open(C00_TAPE, "rb") as f:
        tape = labtape.read_tape(f.read())
    labtape.restore(t.s.cal.fs, labtape.Tape(tape.reel, ":SYS",
                                             [f for f in tape.files if f.name in ("AP", "$:STDDEF")]))
    pyprog.store_source(t.s.cal.fs, "SRC", "BOB", "\n".join([
        "         DEF      START", "START    LI,1     10", "         END      START"]))
    for line in ("AP SRC OVER OBJ,LST", ""):           # no options at OPTIONS: TEL's
        t.type(line + "\r")
    t.run(20000)
    assert t.text().endswith("!")
    fs = t.s.cal.fs
    assert {"OBJ", "LST"} <= set(fs.files("BOB"))
    listing = fs.open("LST", "BOB", "IN", org=1)
    try:
        pos, lines = Position(), []
        while (rec := listing.file.read(pos)) is not None:
            lines.append(rec.decode(EBCDIC))
    finally:
        fs.close(listing)
    assert any("2210000A A   START    LI,1     10" in l for l in lines)
    obj = fs.open("OBJ", "BOB", "IN", org=1)
    try:
        record = obj.file.read(Position())
    finally:
        fs.close(obj)
    assert b"" + "START".encode(EBCDIC) in record   # the DEF's name, a TEXTC


def test_the_record_round_trips():
    t = logged_on()
    u, cal = t.user(), t.s.cal
    assign.parse(cal, u, "SRC OVER OBJ,ME", "BOB")
    words = assign.record(cal, u)
    assert words[1] == assign.HEADER and words[13] & 0xFFFF == u     # first set; SYSID
    first = words[assign.HEADER:]
    assert first[1] >> 24 == 4 and words[0] == len(words)             # 'M:SI', a TEXTC; free
    sets = list(cal.amr[u])
    words[3] = 0x12345678                                             # LOADR: the LM name
    assign.store(cal, u, words)
    assert cal.amr[u] == sets and assign.record(cal, u)[3] == 0x12345678


@pytest.mark.skipif(not os.path.exists(C00_TAPE), reason="the C00 boot tape image isn't here")
def test_lynx_links_aps_object_and_it_runs():
    from uts import labtape
    t = logged_on()
    with open(C00_TAPE, "rb") as f:
        tape = labtape.read_tape(f.read())
    pick = lambda *names: [f for f in tape.files if f.name in names]
    labtape.restore(t.s.cal.fs, labtape.Tape(tape.reel, ":SYS",
                                             pick("AP", "$:STDDEF", "LYNX", "LOADER", "ERRMSG", ":LIB")))
    with open(os.path.join(os.path.dirname(__file__), "..", "examples", "hello.asm")) as f:
        pyprog.store_source(t.s.cal.fs, "HELLO", "BOB", f.read())
    for line in ("AP HELLO OVER HELLOBO", "", "LYNX HELLOBO ON HELLOLM"):
        t.type(line + "\r")
        t.run(8000)
    assert "* * ALLOCATION SUMMARY * *" in t.text()
    log = "\n".join(t.s.log)
    assert "M:LDTRC user 7: LOADER.:SYS" in log                       # LYNX hands over
    assert "T:AMRDWT user 7: the assign/merge record read" in log
    t.type("HELLOLM\r")
    t.run(8000)
    assert t.text().splitlines()[1:] == ["HELLO FROM AP", "COUNT 3", "COUNT 2", "COUNT 1",
                                         "GOODBYE", "!"]
