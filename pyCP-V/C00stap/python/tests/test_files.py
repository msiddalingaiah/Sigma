import random

import pytest

from uts.files import (CONT, F_ADDED, F_FIT, FAK, GRAN, MIDIS, MORE, NWFITST, Disc,
                       FileError, KeyedFile, control, level, nav, word)


def keyed(n=0, shuffle=True, **kw):
    f = KeyedFile(Disc(kw.pop("granules", 600)), "TEST", **kw)
    keys = [f"K{i:05d}" for i in range(n)]
    if shuffle:
        random.Random(7).shuffle(keys)
    for k in keys:
        f.write(k, (k * 2).encode())
    return f, keys


# --- layout ---------------------------------------------------------------------------

def test_the_first_block_holds_the_fit():
    f, _ = keyed()
    b = f.disc.g[f.FDA]
    assert word(b, 0) == 0 and word(b, 1) == 0
    assert nav(b) == MIDIS and control(b) & F_FIT and control(b) & 0xFF == f.SCR
    assert b[NWFITST * 4] == 4 and b[NWFITST * 4 + 1:NWFITST * 4 + 5] == "TEST".encode("cp037")
    assert f.check() == []


def test_an_entry_is_scr_plus_13_bytes():
    f, _ = keyed(keym=11)
    f.write("ABC", b"hello")
    b = f.disc.g[f.FDA]
    assert f.IMT == 25 and nav(b) == MIDIS + 25
    e = f.decode(b, MIDIS)
    assert (e.key, e.size, e.orig, e.flags) == ("ABC".encode("cp037"), 5, 5, FAK)
    assert b[MIDIS] == 3 and b[MIDIS + 4:MIDIS + 12] == bytes(8)   # padding: no stale bytes
    assert f.disc.g[e.da][e.disp:e.disp + 5] == b"hello"


def test_the_room_check_keeps_the_spare_and_the_fit_free():
    f, _ = keyed()
    assert f.limit(f.disc.g[f.FDA]) == NWFITST * 4 - 1 - f.SPARE   # X'6BF' - 102
    other = bytearray(GRAN)
    f._init_block(other, blink=f.FDA, flink=0)
    assert f.limit(other) == GRAN - 1 - f.SPARE


# --- keys -------------------------------------------------------------------------------

def test_many_keys_split_into_blocks_and_stay_in_order():
    f, keys = keyed(400)
    assert len(f._level0_blocks()) > 4
    assert f.keys() == sorted(keys)
    assert all(f.read(k) == (k * 2).encode() for k in keys)
    assert f.check() == []


def test_key_compare_is_textc_shorter_is_lower():
    f, _ = keyed()
    for k in ("AB", "A", "ABC", "B", "AA"):
        f.write(k, k.encode())
    assert f.keys() == ["A", "AA", "AB", "ABC", "B"]


def test_rewrite_delete_and_newkey():
    f, keys = keyed(50)
    f.write("K00007", b"changed")
    assert f.read("K00007") == b"changed" and len(f.keys()) == 50
    assert f.delete("K00008") and f.read("K00008") is None and len(f.keys()) == 49
    with pytest.raises(FileError) as e:
        f.write("K00009", b"x", newkey=True, onewkey=False)
    assert e.value.code == 0x16                        # KEYER2
    with pytest.raises(FileError) as e:
        f.write("NEW", b"x", newkey=False, onewkey=False)
    assert e.value.code == 0x13                        # KEYER4: a rewrite of a missing key
    f.write("K00009", b"rewritten", newkey=False, onewkey=False)
    assert f.read("K00009") == b"rewritten"
    with pytest.raises(FileError):
        f.write("A_KEY_TOO_LONG_FOR_KEYM", b"x")
    assert f.check() == []


# --- records ------------------------------------------------------------------------------

def test_blocked_records_share_a_data_granule_word_aligned():
    f, _ = keyed()
    f.write("A", b"12345")
    f.write("B", b"678")
    a = f.decode(f.disc.g[f.FDA], MIDIS)
    b = f.decode(f.disc.g[f.FDA], MIDIS + f.IMT)
    assert a.da == b.da and (a.disp, b.disp) == (0, 8)


def test_a_record_crossing_the_granule_end_is_two_segments():
    f, _ = keyed()
    f.write("A", b"a" * 1500)
    f.write("B", b"b" * 1500)                          # 548 bytes left in the granule
    blk = f.disc.g[f.FDA]
    first, second = f.decode(blk, MIDIS + f.IMT), f.decode(blk, MIDIS + 2 * f.IMT)
    assert first.flags == FAK | MORE and second.flags == 0
    assert (first.size, second.size) == (GRAN - 1500, 1500 - (GRAN - 1500))
    assert f.read("B") == b"b" * 1500 and f.keys() == ["A", "B"]


def test_a_long_record_gets_whole_granules():
    f, _ = keyed()
    f.write("BIG", bytes(range(256)) * 20)              # 5120 bytes: unblocked
    assert f.read("BIG") == bytes(range(256)) * 20
    blk = f.disc.g[f.FDA]
    segs = [f.decode(blk, MIDIS + i * f.IMT) for i in range(3)]
    assert [s.size for s in segs] == [2048, 2048, 1024] and all(s.disp == 0 for s in segs)
    assert segs[0].flags & FAK and not segs[1].flags & FAK and not segs[2].flags & MORE


def test_a_zero_length_record_has_no_data_address():
    f, _ = keyed()
    f.write("EMPTY", b"")
    assert f.read("EMPTY") == b"" and f.decode(f.disc.g[f.FDA], MIDIS).da == 0
    assert f.check() == []


# --- slides and the pyramid ----------------------------------------------------------------

def test_slides_past_lslides_build_the_pyramid_at_close():
    f, keys = keyed(400, lslides=3)
    assert f.SLIDES == 0xFF and not f.TDA
    f.close()
    top = f.disc.g[f.TDA]
    assert level(top) == 1 and f.SLIDES == 1
    entries = [f._ukey(top, o) for o in f.offsets(top, f.SCR + 4)]
    firsts = [f.first_key(f.disc.g[da]) for da in f._level0_blocks()]
    assert entries == firsts                           # the first key of each block
    assert all(f.read(k) == (k * 2).encode() for k in keys)


def test_no_pyramid_without_enough_slides():
    f, _ = keyed(100, lslides=254)
    f.close()
    assert not f.TDA


def test_a_deep_pyramid_has_a_top_of_at_most_three_blocks():
    f = KeyedFile(Disc(2000), "DEEP", keym=11, lslides=1, spare=1400)
    keys = [f"K{i:05d}" for i in range(3200)]
    for i, k in enumerate(keys):
        f.write(k, b"v")
        if i % 300 == 299:
            f.close()                                  # rebuild as it grows: quick lookups
    f.close()
    top = f.disc.g[f.TDA]
    assert level(top) >= 2
    da, top_blocks = f.TDA, 1
    while word(f.disc.g[da], 0):
        da = word(f.disc.g[da], 0)
    while word(f.disc.g[da], 1):
        da, top_blocks = word(f.disc.g[da], 1), top_blocks + 1
    assert top_blocks <= 3
    sample = keys[::97] + [keys[-1]]
    before = f.disc.reads
    assert all(f.read(k) == b"v" for k in sample)
    assert (f.disc.reads - before) / len(sample) < 12   # down the pyramid, not along level 0
    assert f.check() == []


def test_a_block_named_by_the_pyramid_keeps_its_first_key():
    f, keys = keyed(400, shuffle=False, lslides=3)
    f.close()
    blocks = f._level0_blocks()
    second = f.disc.g[blocks[1]]
    first = f.first_key(second)
    before = first[:-1] + bytes([first[-1] - 1]) + b"X"    # sorts just before ``first``
    f.write(before, b"in between")
    assert f.first_key(f.disc.g[blocks[1]]) == first        # MULCHK
    assert f.read(before) == b"in between" and f.read(first) == (first.decode("cp037") * 2).encode()
    assert f.check() == []


def test_blocks_added_after_the_build_carry_the_added_flag():
    f, keys = keyed(400, lslides=3)
    f.close()
    for i in range(300):
        f.write(f"N{i:05d}", b"n")
    added = [da for da in f._level0_blocks() if control(f.disc.g[da]) & F_ADDED]
    assert added and all(f.read(f"N{i:05d}") == b"n" for i in range(300))
    f.close()
    assert not any(control(f.disc.g[da]) & F_ADDED for da in f._level0_blocks())


def test_a_wrong_upper_entry_falls_back_to_level_0():
    f, keys = keyed(400, lslides=3)
    f.close()
    top = f.disc.g[f.TDA]
    off = MIDIS + 2 * (f.SCR + 4)
    top[off + f.SCR:off + f.SCR + 4] = f.FDA.to_bytes(4, "big")   # point at the wrong block
    assert all(f.read(k) == (k * 2).encode() for k in keys)
    assert any("75-07" in l for l in f.log)


def test_congestion_without_a_pyramid_forces_a_build():
    f, keys = keyed(400, lslides=254, lrdl0=2)
    f.SLIDES = 0
    f.read(sorted(keys)[-1])                           # many level-0 reads
    assert f.SLIDES == 0xFF
    f.close()
    assert f.TDA


def test_continuation_first_keys_are_marked_in_the_upper_level():
    f, _ = keyed(lslides=0)
    for i in range(60):
        f.write(f"R{i:03d}", b"z" * 900)               # records split across granules
    f.close()
    top = f.disc.g[f.TDA]
    for o in f.offsets(top, f.SCR + 4):
        da = int.from_bytes(top[o + f.SCR:o + f.SCR + 4], "big")
        blk = f.disc.g[da]
        cont = not blk[MIDIS + f.IMT - 3] & FAK
        assert bool(top[o] & CONT) == cont


# --- FIX1's checks ----------------------------------------------------------------------------

def test_check_finds_out_of_order_keys_and_bad_flags():
    f, _ = keyed()
    for k in ("A", "B", "C"):
        f.write(k, b"x")
    blk = f.disc.g[f.FDA]
    a, c = MIDIS, MIDIS + 2 * f.IMT
    blk[a + 1], blk[c + 1] = blk[c + 1], blk[a + 1]    # swap A and C
    blk[MIDIS + f.IMT + f.IMT - 3] |= 0x40             # extraneous flag bit on B
    codes = {code for _, _, code in f.check()}
    assert 30 in codes and 26 in codes


def test_check_finds_a_broken_back_link():
    f, _ = keyed(400)
    da = f._level0_blocks()[2]
    f.disc.g[da][0:4] = (0x7777).to_bytes(4, "big")
    assert any(code == 7 for _, _, code in f.check())


def test_with_exactly_three_blocks_on_a_level_the_middle_is_the_top():
    f = KeyedFile(Disc(1500), "THREE", keym=11, lslides=1, spare=1400)
    for i in range(2400):
        f.write(f"K{i:05d}", b"v")
        if i % 300 == 299:
            f.close()
    f.close()
    top = f.disc.g[f.TDA]
    assert level(top) == 1 and word(top, 0) and word(top, 1)   # it has both neighbours
    first = f.disc.g[word(top, 0)]
    assert not word(first, 0) and word(f.disc.g[word(top, 1)], 1) == 0
    assert f.read("K00000") == b"v" and f.read("K02399") == b"v"


# --- directories and OPEN/CLOSE -------------------------------------------------------------

from uts.files import Directory, FileSystem, account_key


def test_directory_entries_have_the_fix1_sizes():
    fs = FileSystem(Disc(64))
    assert (fs.ad.SCR, fs.ad.IMT) == (9, 18)
    fs.add_account("ALPHA")
    fd = fs.file_directory("ALPHA")
    assert (fd.SCR, fd.IMT) == (32, 41)
    blk = fs.disc.g[fs.ad.FDA]
    e = fs.ad.decode(blk, MIDIS)
    assert e.key == "ALPHA   ".encode("cp037") and e.da == fd.FDA
    assert blk[MIDIS + 17] == FAK                       # flags at IMT-1 in the account directory
    assert not control(blk) & F_FIT


def test_accounts_sort_in_ebcdic():
    fs = FileSystem(Disc(64))
    for a in (":SYS", "ALPHA", "9LIVES", "BETA"):
        fs.add_account(a)
    # EBCDIC: specials (X'7A' for :) < letters (X'C1'..) < digits (X'F0'..), unlike ASCII
    assert [k.strip() for k in fs.ad.keys()] == [":SYS", "ALPHA", "BETA", "9LIVES"]


def test_the_directory_room_check_keeps_spare_slots_and_the_dual_words():
    fs = FileSystem(Disc(64))
    first, other = fs.disc.g[fs.ad.FDA], bytearray(GRAN)
    fs.ad._init_block(other, blink=fs.ad.FDA, flink=0)
    assert fs.ad.limit(first) == GRAN - 1 - 4 * 18 - 11
    assert fs.ad.limit(other) == GRAN - 1 - 2 * 18 - 11


def test_a_big_file_directory_splits_and_finds_every_file():
    fs = FileSystem(Disc(1200))
    fs.add_account("ALPHA")
    for i in range(120):
        c = fs.open(f"FILE{i:03d}", "ALPHA", "OUT")
        c.file.write("K", f"{i}".encode())
        fs.close(c)
    fd = fs.file_directory("ALPHA")
    assert len(fd._level0_blocks()) >= 3 and len(fs.files("ALPHA")) == 120
    assert fs.open("FILE077", "ALPHA", "IN").file.read("K") == b"77"


def test_open_shares_the_cfu_and_close_releases_it():
    fs = FileSystem(Disc(64))
    fs.add_account("A")
    one = fs.open("F", "A", "OUT")
    two = fs.open("F", "A", "OUT")
    assert one is two and one.nou == 2
    fs.close(one)
    assert fs.cfus and fs.files("A") == ["F"]
    fs.close(two)
    assert not fs.cfus


def test_open_errors():
    fs = FileSystem(Disc(64))
    with pytest.raises(FileError) as e:
        fs.open("F", "NOACCT", "IN")
    assert e.value.code == 0x03
    fs.add_account("A")
    with pytest.raises(FileError) as e:
        fs.open("F", "A", "IN")
    assert e.value.code == 0x03
