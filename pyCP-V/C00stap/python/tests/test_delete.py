"""Deleting files (docs/files.md section 9): M:CLOSE with REL, DELF/DEL1, and REL."""

from tests.test_pyprog import keyins, system
from uts.files import MIDIS, Disc, FileSystem, Position, nav, word


def fs_with(*names, granules=400):
    d = Disc(granules)
    fs = FileSystem(d)
    fs.add_account(":SYS")
    for n in names:
        fs.close(fs.open(n, ":SYS", "OUT"))
    return d, fs


def assert_all_back(d, base):
    assert len(d.free) == base and len(set(d.free)) == len(d.free)   # none lost, none twice


# --- the directory entry (DELF / DEL1) ------------------------------------------------------

def test_removing_an_entry_slides_the_rest_up():
    d, fs = fs_with("AAA", "BBB", "CCC")
    fd = fs.file_directory(":SYS")
    b = d.g[fd.FDA]
    before = nav(b)
    assert fd.remove("BBB")
    assert nav(b) == before - fd.IMT                    # one entry fewer, nothing left null
    assert [b[off] for off in fd.offsets(b)] == [3, 3]  # no zero key counts
    assert fs.files(":SYS") == ["AAA", "CCC"] and fd.find("CCC")


def test_an_emptied_directory_block_stays_with_its_first_word_cleared():
    d, fs = fs_with("ONLY")
    fd = fs.file_directory(":SYS")
    fd.remove("ONLY")
    b = d.g[fd.FDA]
    assert nav(b) == MIDIS and word(b, 3) == MIDIS      # BLITZ 1ST ENTRY
    assert fs.files(":SYS") == [] and fd.FDA in d.g


# --- releasing the granules (REL) -------------------------------------------------------------

def test_a_keyed_file_gives_back_every_granule():
    d, fs = fs_with()
    base = len(d.free)
    c = fs.open("K", ":SYS", "OUT")
    for i in range(150):                                # enough for a pyramid
        c.file.write(f"K{i:03d}".encode(), bytes(i * 53 % 2500 + 1))
    for i in range(0, 150, 7):
        c.file.write(f"K{i:03d}".encode(), b"again")    # rewrites leave null entries
    for i in range(3, 150, 11):
        c.file.delete(f"K{i:03d}".encode())
    fs.close(c)
    assert c.file.TDA                                   # the pyramid was built
    fs.close(fs.open("K", ":SYS", "UPDATE"), release=True)
    assert fs.files(":SYS") == []
    assert_all_back(d, base)


def test_a_consecutive_file_gives_back_every_granule():
    d, fs = fs_with()
    base = len(d.free)
    c = fs.open("C", ":SYS", "OUT", org=1)
    p = Position()
    for i in range(60):
        c.file.write(p, bytes(i * 91 % 5000 + 1))       # unblocked ones too
    fs.close(c)
    fs.close(fs.open("C", ":SYS", "IN"), release=True)
    assert fs.files(":SYS") == []
    assert_all_back(d, base)


# --- CLOSE with REL ---------------------------------------------------------------------------

def test_a_new_file_released_at_close_is_never_entered():
    d, fs = fs_with()
    base = len(d.free)
    c = fs.open("TEMP", ":SYS", "OUT")
    c.file.write(b"KEY", b"data")
    fs.close(c, release=True)                           # OUT: only the granules (CLSFIL2)
    assert fs.files(":SYS") == []
    assert_all_back(d, base)


def test_no_release_while_another_user_has_it_open():
    d, fs = fs_with("SHARED")
    first, second = fs.open("SHARED", ":SYS"), fs.open("SHARED", ":SYS")
    assert first is second and first.nou == 2
    fs.close(first, release=True)                       # MORE THAN 1 USER
    assert fs.files(":SYS") == ["SHARED"]
    fs.close(second, release=True)
    assert fs.files(":SYS") == []


DELETER = '''
def main(cpv):
    f = cpv.open("SCRATCH", fun="OUT", org="consec")
    f.write("SOMETHING")
    f.close()
    g = cpv.open("SCRATCH")
    cpv.type("BEFORE " + g.read().decode())
    g.close()
    cpv.open("SCRATCH", fun="UPDATE").close(release=True)
    try:
        cpv.open("SCRATCH")
    except cpv.CpvError as e:
        cpv.type(f"GONE {e.code:02X}")
'''


def test_a_ghost_deletes_a_file_with_close_rel():
    m, con, s = system(DELETER=DELETER)
    text = keyins(m, con, "GJOB DELETER")
    assert "BEFORE SOMETHING" in text and "GONE 03" in text
    assert "SCRATCH" not in s.cal.fs.files(":SYS")


# --- deleting keyed records (DEL), and what the pyramid keeps (MOVEAKEY) ------------------------

def test_keyed_delete_keeps_control_keys_and_slides_the_rest():
    d, fs = fs_with()
    kf = fs.open("K", ":SYS", "OUT").file
    kf.write(b"A", b"a" * 2048)                         # a full granule, first in the block
    kf.write(b"B", b"bbbbb")                            # a new data granule: displacement 0
    kf.write(b"C", b"ccccc")                            # displacement 8 in the same granule
    b = d.g[kf.FDA]
    n = nav(b)
    assert kf.delete(b"C")                              # slid out (DEL1)
    assert nav(b) == n - kf.IMT
    assert kf.delete(b"B")                              # a control key: kept, null (DEL11)
    assert nav(b) == n - kf.IMT
    ctl = kf.decode(b, MIDIS + kf.IMT)
    assert b[MIDIS + kf.IMT] == 0 and ctl.disp == 0 and ctl.da
    full = kf.decode(b, MIDIS).da
    free = len(d.free)
    assert kf.delete(b"A")                              # full granule: released now (DEL13)
    assert len(d.free) == free + 1 and full in d.free
    assert kf.decode(b, MIDIS).disp == 3                # MTB,3: PREVENT DOUBLE RELEASE
    assert kf.keys() == [] and kf.check() == []


def test_releasing_after_deletes_never_frees_a_granule_twice():
    d, fs = fs_with()
    base = len(d.free)
    c = fs.open("K", ":SYS", "OUT")
    for k in ("A", "B", "C"):
        c.file.write(k.encode(), k.encode() * 2048)
    c.file.delete(b"A")
    c.file.delete(b"B")
    fs.close(c)
    fs.close(fs.open("K", ":SYS", "UPDATE"), release=True)
    assert_all_back(d, base)


def test_the_search_backs_up_from_a_continuation_key():
    """MLSET00  RDF.txt:1794: a record whose first entry ends one block and whose
    continuations start the next. The next block's upper key is the record's key
    with X'80'; the search must start level 0 one block earlier."""
    import random
    r = random.Random(0)
    d, fs = fs_with(granules=1500)
    kf = fs.open("K", ":SYS", "OUT").file
    model = {}
    for _ in range(250):                                # the workload that first showed it
        k = "K%03d" % r.randrange(200)
        if r.random() < 0.3 and k in model:
            kf.delete(k)
            del model[k]
        else:
            v = bytes([r.randrange(256)]) * r.choice([1, 5, 40, 300, 1900, 2040, 2048, 2100,
                                                       4096, 5000])
            kf.write(k, v)
            model[k] = v
    kf.build_pyramid()
    assert kf.TDA
    assert all(kf.read(k) == v for k, v in model.items())
