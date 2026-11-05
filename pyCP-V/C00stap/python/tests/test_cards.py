"""The card reader and punch (uts/cards.py) under device OPEN, M:SETDCB, and OPEN's
merge of an FPT's parameters and VLPs into a file DCB in memory."""

import os

import pytest

from tests.test_online import UTIL_TAPE, logged_on
from uts import labtape
from uts.asm import assemble
from uts.cards import CardPunch, CardReader, UnitRecord, card
from uts.files import EBCDIC
from uts.fetch import write_load_module


def test_cards_and_allocation():
    assert card("HELLO") == "HELLO".ljust(80).encode(EBCDIC)
    units = UnitRecord(CardReader([card("A")]), None)
    assert units.allocate("CR", 5) and units.allocate("CR", 5)    # the holder again: fine
    assert not units.allocate("CR", 6)                            # one user at a time
    assert not units.allocate("CP", 5)                            # no medium
    units.release(5)
    assert units.allocate("CR", 6)


CARDS = """
* Copy the reader to the punch: M:SI opened with the device option CR, M:BO with CP;
* end of the deck is the read's abnormal (X'06'); M:SETDCB sets the DCB's own
         ORG      X'D000'
START    CAL1,1   OPENSI
         CAL1,1   OPENBO
         CAL1,1   SETSI
LOOP     CAL1,1   READ
         CAL1,1   PUNCH
         BCR,0    LOOP
DONE     CAL1,1   WRITE
         CAL1,9   1
OPENSI   DATA     X'14000000'+M:SI,X'00040003',X'C3D9'
OPENBO   DATA     X'14000000'+M:BO,X'00040003',X'C3D7'
SETSI    DATA     X'06000000'+M:SI,X'40000000',DONE
READ     DATA     X'10000000'+M:SI,X'70000000',DONE,BUF,80
PUNCH    DATA     X'11000000'+M:BO,X'30000000',BUF,80
WRITE    DATA     X'11000000'+M:LO,X'30000000',MSG,11
MSG      TEXT     'END OF DECK '
BUF      RES      20
M:SI     DATA     X'33000003',X'00020009',0,0,0,0,0,0,0,0,0,0,0,0,0,0
M:BO     DATA     X'33000003',X'00040007',0,0,0,0,0,0,0,0,0,0,0,0,0,0
M:LO     DATA     X'33000003',X'00040003',0,0,0,0,0,0,0,0,0,0,0,0,0,0
         END      START
"""


def test_a_program_copies_the_reader_to_the_punch():
    t = logged_on()
    punch = CardPunch()
    t.s.cal.unit_record = UnitRecord(CardReader([card("FIRST CARD"), card("SECOND")]), punch)
    dcbs = {}
    words, start = assemble(CARDS, dcbs)
    write_load_module(t.s.cal.fs, "CARDS", ":SYS", words, start, dcbs)
    t.type("CARDS\r")
    assert t.text() == "CARDS\r\nEND OF DECK\r\n!"
    assert [CardPunch.text(c) for c in punch.cards] == ["FIRST CARD", "SECOND"]
    assert t.s.cal.unit_record.holder == {"CR": 7, "CP": 7}   # the job holds them ...
    t.type("OFF\r")
    assert t.s.cal.unit_record.holder == {}               # ... until it ends (T:DELUS)
    assert t.s.cal.dcb_at(t.s.LB_UN[0] or 7, dcbs["M:SI"]).aba == start + 6   # SETDCB: DONE


def test_without_a_medium_the_device_cant_be_had():
    t = logged_on()
    t.s.cal.unit_record = UnitRecord(None, None)
    dcbs = {}
    words, start = assemble(CARDS, dcbs)
    write_load_module(t.s.cal.fs, "CARDS", ":SYS", words, start, dcbs)
    t.type("CARDS\r")
    assert any("device error X'49'-02" in line for line in t.s.log)


MERGE = """
* OPEN a file DCB whose FPT gives the assignment (ASN 1), the function UPDATE, the
* organization (keyed) and the file name as a VLP; the file isn't there, so the
* abnormal routine opens it OUT, which creates it
         ORG      X'D000'
START    CAL1,1   OPENUP
         CAL1,9   3
NEW      CAL1,1   OPENOUT
         CAL1,1   CLOSE
         CAL1,9   1
OPENUP   DATA     X'14000000'+F:W,X'C7000009',X'D009',NEW,2,2,4
         DATA     X'01000303',X'09D4E3D9',X'D5D4C6C9',X'D3C54040',X'02010002',0,0
OPENOUT  DATA     X'14000000'+F:W,X'C7000009',X'D009',X'D009',2,2,2
         DATA     X'01000303',X'09D4E3D9',X'D5D4C6C9',X'D3C54040',X'02010002',0,0
CLOSE    DATA     X'15000000'+F:W,0
F:W      DATA     X'1A000003',X'0007D4C5',0,0,0,0,VLPS,0,0,0,0,0,0,0,0,0
VLPS     DATA     X'01000003',0,0,0,X'02010002',0,0
         END      START
"""


def test_open_merges_the_fpts_parameters_and_vlps():
    t = logged_on()
    dcbs = {}
    words, start = assemble(MERGE, dcbs)
    write_load_module(t.s.cal.fs, "MERGE", ":SYS", words, start, dcbs)
    t.type("MERGE\r")
    log = "\n".join(t.s.log)
    assert "ASN 3 -> 1 (the FPT's)" in log
    assert "abnormal X'03'" in log                        # UPDATE of a missing file
    assert "MTRNMFILE" in t.s.cal.fs.files("BOB")          # OUT created it, in BOB's account


@pytest.mark.skipif(not os.path.exists(UTIL_TAPE), reason="the UTIL tape image isn't here")
def test_slip_reads_its_control_card_from_the_reader():
    t = logged_on()
    with open(UTIL_TAPE, "rb") as f:
        labtape.restore(t.s.cal.fs, labtape.read_tape(f.read()))
    reader = CardReader([card("CARD TO DISK"), card("NOT A CATALOG CARD")])
    t.s.cal.unit_record = UnitRecord(reader, CardPunch())
    t.type("SLIP.:UTIL\r")
    out = t.text()
    assert "THE FOLLOWING FILES WERE COPIED TO DISK:" in out      # the command matched
    assert "!BIN OR FIRST CATALOG CARD MISSING" in out           # SLIP's check of card 2
    assert reader.read == 2 and any("OPEN MTRNMFILE.BOB OUT" in line for line in t.s.log)
