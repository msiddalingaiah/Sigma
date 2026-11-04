"""Granule allocation and random files (docs/files.md sections 8 and 6): the HGP bit map,
the stack, ALLOCAT and STUQFAC, and RWRAND."""

import gzip
import json

from tests.test_pyprog import keyins, system
from uts import image
from uts.files import (F_EMPTIED, F_FILLED, F_HGPEMPTY, HILEVEL, LOLEVEL, LOTHRSH, Disc,
                       FileError, FileSystem, Hgp, RandomFile, open_file)


# --- the bit map (GRANSUB) ---------------------------------------------------------------------

def test_the_bit_map_continues_from_the_last_get_and_logs_dual_allocation():
    h = Hgp(0x100, 16)
    assert [h.get() for _ in range(3)] == [0x100, 0x101, 0x102]
    h.release(0x100)
    assert h.get() == 0x103                             # from where the last get stopped
    assert h.release(0x103) and h.dual == []
    assert h.release(0x103) and h.dual == [0x103]       # already free: LOGDUAL
    assert not h.release(0x200)                         # not in the map


def test_n_granules_come_from_the_end_of_the_map():
    h = Hgp(0x100, 16)
    assert h.get_n(4) == 0x10C                          # the last four
    h.get_n(4)
    for a in (0x101, 0x103):
        h._set(a - 0x100, False)                        # break up the low end
    assert h.get_n(5) == 0                              # the longest run left is 4
    assert h.get_n(4) == 0x104                          # 0x104-0x107


# --- the stack and ALLOCAT (GRAN, ADJBUFS, STUQFAC) --------------------------------------------

def test_an_empty_stack_is_filled_to_hilevel_in_map_order():
    d = Disc(300)
    assert d.get() == 0x100                             # ALLOCAT's turn, then the pop
    s = d.stack
    assert s.WORDCNT == HILEVEL - 1 and not s.BUFLAGS
    assert [d.get() for _ in range(3)] == [0x101, 0x102, 0x103]
    d.release(0x101)
    assert d.get() == 0x101                             # the stack is last in, first out


def test_allocats_fill_is_pending_until_stuqfac():
    d = Disc(300)
    s = d.stack
    d.allocat()                                         # ADJBUFS on the empty stack
    assert s.BUFLAGS & F_FILLED and s.ADJSTCNT == HILEVEL
    assert s.TOP == s.BOTTOM and s.WORDCNT == 0         # users still see it empty
    d.commit()                                          # STUQFAC: BOTTOM = TEMPBOT
    assert s.WORDCNT == HILEVEL and s.TOP != s.BOTTOM and not s.BUFLAGS


def test_an_overfull_stack_is_emptied_to_lolevel():
    d = Disc(300)
    held = [d.get() for _ in range(120)]
    for a in held:
        d.release(a)                                    # back onto the stack, past HILEVEL
    s = d.stack
    count = s.WORDCNT
    assert count > HILEVEL
    d.allocat()
    assert s.BUFLAGS & F_EMPTIED and s.ADJSTCNT == LOLEVEL - count
    d.commit()
    assert s.WORDCNT == LOLEVEL
    assert len(d.free) == 300 and len(set(d.free)) == 300 and d.hgp.dual == []


def test_thresholds_call_the_cat():
    d = Disc(300)
    calls = []
    d.cat = lambda: calls.append(d.stack.WORDCNT)
    d.get()
    while d.stack.WORDCNT > LOTHRSH:
        d.get()
    assert calls and calls[0] == LOTHRSH               # at LOTHRSH: T:GJOBSTRT 'ALLOCAT'


def test_a_full_disc_gives_0_and_a_release_clears_the_empty_flag():
    d = Disc(20)
    got = [d.get() for _ in range(20)]
    assert all(got) and d.get() == 0                    # SATDISK
    assert d.stack.BUFLAGS & F_HGPEMPTY
    d.release(got[0])
    d.allocat()
    d.commit()
    assert d.get() == got[0]


def test_allocat_runs_as_a_ghost_when_a_threshold_starts_it():
    big = '''
def main(cpv):
    f = cpv.open("DATA", fun="OUT", org="consec")
    for i in range(150):
        f.write("X" * 2040)
    f.close()
    cpv.open("DATA", fun="UPDATE").close(release=True)
    cpv.type("DONE")
'''
    m, con, s = system(BIG=big)
    d = s.cal.fs.disc
    assert s.buffers[1] is d.stack                      # the scheduler's STUQFAC buffer
    text = keyins(m, con, "GJOB BIG")
    assert "DONE" in text
    assert any("ALLOCAT: ADJBUFS; E:UQFAC" in line for line in s.log)
    assert len(d.free) + len(d.g) == d.hgp.n and d.hgp.dual == []


# --- random files (GRAND, RWRAND, RELRAND) -----------------------------------------------------

def test_a_random_file_is_a_run_from_the_end_of_the_map():
    d = Disc(300)
    fs = FileSystem(d)
    fs.add_account(":SYS")
    base = len(d.free)
    c = fs.open("R", ":SYS", "OUT", org=3, size=10)
    f = c.file
    assert isinstance(f, RandomFile) and f.TDA == 10
    assert f.FDA == 0x100 + 300 - 10                    # CMNGNG: the last ten
    assert f.write(2, b"x" * 3000) == 3000
    assert f.read(2, 4096)[:3000] == b"x" * 3000 and len(f.read(9, 4096)) == 2048
    try:
        f.read(10, 1)
        assert False
    except FileError as e:
        assert e.code == 0x42                           # ERR01
    fs.close(c)
    g = open_file(d, fs.file_directory(":SYS").find("R"))
    assert isinstance(g, RandomFile) and (g.FDA, g.TDA) == (f.FDA, 10) and g.check() == []
    fs.close(fs.open("R", ":SYS", "UPDATE"), release=True)
    assert len(d.free) == base and d.hgp.dual == []


RTEST = '''
def main(cpv):
    f = cpv.open("TABLE", fun="OUT", org="random", size=10)
    f.write("A" * 2048 + "B" * 100, gran=3)
    cpv.type("NEXT " + str(f.granule))
    f.close()
    g = cpv.open("TABLE", fun="UPDATE")
    d = g.read(gran=3, size=4096)
    cpv.type("READ " + str(len(d)) + " " + d[2046:2050].decode())
    try:
        g.read(gran=10)
    except cpv.CpvError as e:
        cpv.type(f"PAST END {e.code:02X}")
    try:
        g.read(gran=9, size=4096)
    except cpv.CpvError as e:
        cpv.type(f"SHORT {e.code:02X}")
    g.close(release=True)
'''


def test_a_ghost_uses_a_random_file_by_granule_number():
    m, con, s = system(RTEST=RTEST)
    d = s.cal.fs.disc
    base = len(d.free)
    text = keyins(m, con, "GJOB RTEST")
    lines = [t.split(": ", 1)[1] for t in text.splitlines() if ": " in t]
    assert lines == ["NEXT 5", "READ 4096 AABB", "PAST END 42", "SHORT 44"]
    assert len(d.free) == base


# --- the disc image ---------------------------------------------------------------------------

def test_the_image_keeps_the_bit_map_and_the_stack(tmp_path):
    d = Disc(300)
    held = [d.get() for _ in range(5)]
    d.release(held[1])
    path = tmp_path / "d.json.gz"
    from uts.devices import Disc as Swap
    image.save(path, Swap(), d)
    _, e = image.load(path)
    assert e.hgp.map == d.hgp.map and e.hgp.last == d.hgp.last
    assert e.stack.slots == d.stack.slots and e.stack.TOP == d.stack.TOP
    assert e.get() == d.get() == held[1]


def test_a_version_1_image_loads_as_a_bit_map(tmp_path):
    from uts.devices import Disc as Swap
    path = tmp_path / "v2.json.gz"
    d = Disc(16)
    image.save(path, Swap(), d)
    im = json.loads(gzip.decompress(path.read_bytes()))
    im["version"] = 1
    pub = im["public"]
    pub["free"] = list(range(0x100, 0x10E))             # two in use, by the free list
    pub["granules"] = {str(0x10E): "00" * 2048, str(0x10F): "00" * 2048}
    del pub["hgp"], pub["stack"]
    old = tmp_path / "v1.json"
    old.write_text(json.dumps(im))
    _, e = image.load(old)
    assert e.hgp.n == 16 and sorted(e.free) == list(range(0x100, 0x10E))
    assert e.hgp.dual == []
