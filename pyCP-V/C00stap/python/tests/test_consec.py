"""Consecutive files (docs/files.md section 4): granules, segments, read, write, delete."""

from tests.test_pyprog import keyins, system
from uts.files import (FITSEG, G_FULL, G_UNBLK, UNBLOCKED, WBUFS, X_BKSP, X_CONT, X_FAK,
                       X_UNBLK, ConsecutiveFile, Disc, FileSystem, Position, flags_of,
                       gnav, open_file, word)


def new(granules=64):
    d = Disc(granules)
    return d, ConsecutiveFile(d, "CF")


def write_all(f, records):
    p = Position()
    for r in records:
        f.write(p, r)
    return p


# --- the layout ---------------------------------------------------------------------------

def test_the_first_granule_holds_the_fit_as_a_deleted_looking_segment():
    d, f = new()
    b = d.g[f.FDA]
    assert word(b, 0) == word(b, 1) == 0
    assert word(b, 3) == FITSEG == 0x01400000          # 320 bytes, no flags
    assert gnav(b) == 84 and word(b, 84) == 3          # NAV past the FIT, its back pointer
    assert b[16] == 2 and b[17:19] == "CF".encode("cp037")   # the FIT's name at word 4
    assert f.TDA == 0 and f.records() == [] and f.check() == []


def test_blocked_records_chain_by_back_pointers():
    d, f = new()
    write_all(f, [b"ABCDE", b"XYZ"])
    b = d.g[f.FDA]
    first, second = word(b, 84), word(b, 87)           # 84 + 1 + ceil(5/4)
    assert flags_of(first) == X_FAK and (first >> 16) & 0xFFF == 5 and first & 0xFFFF == 3
    assert flags_of(second) == X_FAK and (second >> 16) & 0xFFF == 3 and second & 0xFFFF == 84
    assert bytes(b[85 * 4:85 * 4 + 5]) == b"ABCDE"
    assert gnav(b) == 89 and word(b, 89) == 87         # the next back pointer, already there
    assert f.TDA == 2 and f.check() == []


def test_a_long_record_is_unblocked_after_a_backspace_word():
    d, f = new()
    write_all(f, [b"A" * 10, b"B" * UNBLOCKED])        # 2033 bytes: unblocked
    b = d.g[f.FDA]
    assert word(b, 88) == 84                           # backspace control: flags 0, count 0
    cw = word(b, 89)
    assert flags_of(cw) == X_UNBLK | X_FAK | X_BKSP and (cw >> 24) & 0xF == 0
    assert bytes(d.g[cw & 0xFFFFFF][:UNBLOCKED]) == b"B" * UNBLOCKED
    assert word(b, 2) & G_UNBLK and gnav(b) == 90
    assert f.records() == [b"A" * 10, b"B" * UNBLOCKED] and f.check() == []


def test_a_record_longer_than_a_granule_is_continued():
    d, f = new()
    rec = bytes(range(256)) * 20                       # 5120 bytes
    write_all(f, [rec])
    b = d.g[f.FDA]
    one, two = word(b, 85), word(b, 86)                # after the backspace word at 84
    assert flags_of(one) == X_UNBLK | X_FAK | X_BKSP | X_CONT and (one >> 24) & 0xF == 15
    assert flags_of(two) == X_UNBLK | X_CONT           # 2048 more
    rest = word(b, 87)                                 # 1024 left: blocked
    assert flags_of(rest) == 0 and (rest >> 16) & 0xFFF == 1024
    assert f.records() == [rec] and f.check() == []


def test_a_blocked_record_split_across_granules():
    d, f = new()
    write_all(f, [b"x" * 1700, b"y" * 400])            # the second doesn't fit in 512 words
    first = d.g[f.FDA]
    assert word(first, 2) & G_FULL and word(first, 1) == f.LDA != f.FDA
    cw = word(first, 510)                              # 84 + 1 + 425: 4 bytes fit
    assert flags_of(cw) == X_FAK | X_CONT and (cw >> 16) & 0xFFF == 4
    rest = word(d.g[f.LDA], 3)                         # 396 more, no back pointer
    assert flags_of(rest) == 0 and rest == 396 << 16
    assert f.records() == [b"x" * 1700, b"y" * 400] and f.check() == []


def test_many_records_round_trip_and_reopen():
    d, f = new(400)
    recs = [bytes([65 + i % 26]) * (i * 137 % 3000 + 1) for i in range(80)]
    write_all(f, recs)
    f.close()
    assert f.records() == recs and f.check() == []
    g = open_file(d, f.FDA)
    assert isinstance(g, ConsecutiveFile) and g.TDA == 80 and g.records() == recs


# --- writing in the middle, deleting -------------------------------------------------------

def test_writing_before_the_end_cuts_the_file_there():
    d, f = new(200)
    write_all(f, [b"1" * 10, b"2" * 3000, b"3" * 1500, b"4" * 2040, b"5" * 9])
    used = len(d.g)
    p = Position()
    f.read(p), f.read(p)
    f.write(p, b"NEW")
    assert f.records() == [b"1" * 10, b"2" * 3000, b"NEW"] and f.TDA == 3
    assert len(d.g) < used and f.check() == []         # later granules released


def test_seek_record_positions_before_a_record():
    d, f = new(200)
    write_all(f, [b"1" * 10, b"2" * 3000, b"3" * 9])
    p = f.seek_record(1)                               # M:PRECORD: before record 1
    assert p.rec == 1 and p.start is None and f.read(p) == b"2" * 3000
    p = f.seek_record(3)
    assert f.read(p) is None                           # at the end
    p = f.seek_record(0)
    f.write(p, b"NEW")                                 # back to the start: a rewrite
    assert f.records() == [b"NEW"]


def test_a_zero_length_write_writes_nothing():
    d, f = new()
    write_all(f, [b"A", b"", b"B"])
    assert f.records() == [b"A", b"B"] and f.TDA == 2


def test_delete_record_clears_its_flag_and_keeps_the_data():
    d, f = new()
    write_all(f, [b"ONE", b"TWO", b"THREE"])
    p = Position()
    f.read(p), f.read(p)
    assert f.delete_record(p)
    assert f.TDA == 2 and f.records() == [b"ONE", b"THREE"]
    cw = word(d.g[f.FDA], 86)                          # TWO's control word
    assert flags_of(cw) == 0 and (cw >> 16) & 0xFFF == 3   # a "deleted blocked segment"
    assert f.read(p) == b"THREE" and f.read(p) is None
    assert not f.delete_record(Position())             # nothing just read
    assert f.check() == []


# --- FIX1's check ---------------------------------------------------------------------------

def test_chkcon_finds_a_bad_back_pointer():
    d, f = new()
    write_all(f, [b"ABCDE", b"XYZ"])
    b = d.g[f.FDA]
    b[87 * 4 + 3] ^= 1                                 # 84 -> 85
    assert f.check() == [(f.FDA, 87, 41)]


def test_chkcon_as_read_rejects_an_unblocked_segment_at_a_granule_start():
    """The open question in docs/files.md: the writer puts an unblocked segment at word
    3 of a new granule without the X'1' flag, and CHKCON, as read, wants it."""
    d, f = new()
    p = write_all(f, [b"x" * ((WBUFS - 85) * 4)])      # fills the first granule exactly
    assert word(d.g[f.FDA], 2) & G_FULL
    f.write(p, b"y" * 2040)
    assert f.records()[1] == b"y" * 2040               # reads back fine
    assert f.check() == [(f.LDA, 3, 42)]               # but FIX1 would report it


# --- OPEN, the CALs, and Python programs -----------------------------------------------------

def test_open_tells_the_organizations_apart():
    fs = FileSystem(Disc(64))
    fs.add_account(":SYS")
    c = fs.open("SEQ", ":SYS", "OUT", org=1)
    write_all(c.file, [b"R1"])
    fs.close(c)
    k = fs.open("KEY", ":SYS", "OUT")
    fs.close(k)
    assert isinstance(fs.open("SEQ", ":SYS").file, ConsecutiveFile)
    assert not isinstance(fs.open("KEY", ":SYS").file, ConsecutiveFile)


WRITER = '''
def main(cpv):
    f = cpv.open("LOG", fun="OUT", org="consec")
    for i in range(4):
        f.write(f"LINE {i}")
    f.write("L" * 2500)
    f.close()
    g = cpv.open("LOG")
    while (data := g.read(size=4096)) is not None:
        cpv.type(data.decode()[:10] + " " + str(len(data)))
    g.close()
'''

EDITOR = '''
def main(cpv):
    f = cpv.open("LOG", fun="UPDATE")
    f.read(); f.read()
    f.delete()                                  # LINE 1
    f.read()
    f.write("TAIL")                             # cuts after LINE 2
    f.close()
    for data in cpv.open("LOG"):
        cpv.type(data.decode())
    try:
        cpv.open("LOG").read(size=2)
    except cpv.CpvError as e:
        cpv.type(f"LOST DATA {e.code:02X}")
'''


def test_a_ghost_writes_and_reads_a_consecutive_file():
    m, con, s = system(WRITER=WRITER, EDITOR=EDITOR)
    text = keyins(m, con, "GJOB WRITER")
    assert all(f"LINE {i} 6" in text for i in range(4))
    assert "LLLLLLLLLL 2500" in text
    assert isinstance(s.cal.fs.open("LOG", ":SYS").file, ConsecutiveFile)
    text = keyins(m, con, "GJOB EDITOR")
    lines = [t.split(": ", 1)[1] for t in text.splitlines() if ": " in t]
    assert lines[-4:] == ["LINE 0", "LINE 2", "TAIL", "LOST DATA 07"]


def test_chkcon_as_read_rejects_what_follows_a_cut_at_an_unblocked_segment():
    """The cut turns an unblocked control word into a pointer to the word before it
    (DLT.txt:582-584). After a backspace word, the next segment's back pointer names
    that backspace word: CHKCON, as read, reports ERR#41 (blocked) or ERR#42."""
    d, f = new()
    write_all(f, [b"A" * 10, b"B" * 2040, b"C" * 10])   # B: backspace word, then unblocked
    p = Position()
    f.read(p)
    f.write(p, b"D" * 10)                               # cuts at B, then a blocked record
    assert f.records() == [b"A" * 10, b"D" * 10]
    assert f.check() == [(f.FDA, 89, 41)]               # its back pointer is 88, the backspace
