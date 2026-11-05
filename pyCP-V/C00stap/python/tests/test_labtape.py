"""Labeled tapes (uts/labtape.py): LBLT's blocking read back, and a restore into the
file system. A small writer builds tapes the way LBLT blocks them."""

import os

import pytest

from uts import labtape
from uts.files import EBCDIC, Disc, FileSystem

UTIL = os.path.join(os.path.dirname(__file__), "..", "..", "c00si", "sw-lib-utility-pgm-util.tap")


def tap(*records):
    """simh .tap framing; None is a tape mark."""
    out = b""
    for r in records:
        if r is None:
            out += bytes(4)
        else:
            n = len(r).to_bytes(4, "little")
            out += n + r + n
    return out


def label(tag, rest):
    return tag.encode(EBCDIC) + rest


def bof(name):
    n = name.encode(EBCDIC)
    return label(":BOF", bytes([1, 0, 8, 8, len(n)]) + n.ljust(43, b"\0"))


def blocks(records, area=4, stale=b"", limit=60):
    """LBLT's blocks for [(key, data)]: entries of key area, size word and data; a
    record that doesn't fit is split (flags 3 then 0); one over ``limit`` bytes goes
    out unblocked (flag 04, the data as the next tape record)."""
    out, block, entries, prev = [], b"", 0, 0

    def flush():
        nonlocal block, entries, prev
        if entries:
            out.append((prev << 16 | entries).to_bytes(4, "big") + block)
            prev, block, entries = len(out[-1]), b"", 0

    def entry(key, flags, data, size=None):
        nonlocal block, entries
        keyfield = (bytes([len(key)]) + key + stale)[:area].ljust(area, b"\0")
        size = len(data) if size is None else size
        block += keyfield + (flags << 24 | size).to_bytes(4, "big") + data
        block += bytes(-len(block) % 4)
        entries += 1

    for key, data in records:
        if len(data) > limit:                          # WRTL1: control record, then data
            entry(key, 0x05, b"", len(data))
            flush()
            out.append(data)
            prev = 0xFFFF
            continue
        room = labtape.BLOCK - 4 - len(block) - area - 4
        if len(data) <= room:
            entry(key, 0x01, data)
        else:
            entry(key, 0x03, data[:room])
            flush()
            entry(key, 0x00, data[room:])
        if len(block) > labtape.BLOCK - 4 - area - 8:
            flush()
    flush()
    return out


def image(files, reel="TEST", account=":TEST"):
    recs = [label(":LBL", reel.encode(EBCDIC).ljust(8, b"@")),
            label(":ACN", account.encode(EBCDIC).ljust(8, b"@") + bytes(16)), None]
    for name, records, kw in files:
        recs += [bof(name), None, *blocks(records, **kw), None, label(":EOF", bytes(8)), None]
    return tap(*recs, None)


def test_blocked_split_and_unblocked_records_read_back():
    seq = [(i.to_bytes(3, "big"), bytes([i]) * 108) for i in range(40)]    # splits blocks
    lmn = [(b"HEAD", bytes(48)), (b"ROOT\x03", bytes(range(200))), (b"TREE", bytes(48))]
    tape = labtape.read_tape(image([("ROM", seq, {}),
                                    ("LMN", lmn, {"area": 16, "stale": b"D:SLUPDA"})]))
    assert (tape.reel, tape.account) == ("TEST", ":TEST")
    rom, lm = tape.files
    assert rom.name == "ROM" and rom.records == seq and rom.key_area == 4
    assert lm.records == lmn and lm.key_area == 16       # stale bytes after short keys
    assert labtape.sequential(rom.records) and not labtape.sequential(lm.records)


def test_restore_makes_consecutive_and_keyed_files():
    seq = [(i.to_bytes(3, "big"), f"CARD {i}".encode(EBCDIC)) for i in range(5)]
    edit = [((n * 1000).to_bytes(3, "big"), f"LINE {n}".encode(EBCDIC)) for n in (1, 2, 5)]
    tape = labtape.read_tape(image([("DECK", seq, {}), ("TEXT", edit, {})]))
    fs = FileSystem(Disc(1024))
    assert labtape.restore(fs, tape) == ["DECK", "TEXT"]
    deck = fs.open("DECK", ":TEST", "IN")
    assert type(deck.file).__name__ == "ConsecutiveFile"
    assert deck.file.records() == [d for _, d in seq]
    fs.close(deck)
    text = fs.open("TEXT", ":TEST", "IN")
    assert text.file.read((5000).to_bytes(3, "big")) == "LINE 5".encode(EBCDIC)
    fs.close(text)
    labtape.restore(fs, tape)                            # again: the files are replaced
    assert sorted(fs.files(":TEST")) == ["DECK", "TEXT"]


def test_bad_images_are_refused():
    with pytest.raises(labtape.TapeError):
        labtape.read_tape(tap(label(":EOF", bytes(8))))
    with pytest.raises(labtape.TapeError):
        labtape.read_tape(bytes([10, 0, 0, 0]) + b"short")


@pytest.mark.skipif(not os.path.exists(UTIL), reason="the UTIL tape image isn't here")
def test_the_util_tape():
    with open(UTIL, "rb") as f:
        tape = labtape.read_tape(f.read())
    assert (tape.reel, tape.account, len(tape.files)) == ("UTIL", ":UTIL", 16)
    slip = {f.name: f for f in tape.files}["SLIP"]
    keys = [k for k, _ in slip.records]
    assert keys[0] == "HEAD".encode(EBCDIC) == b"\xc8\xc5\xc1\xc4" and slip.key_area == 16
    assert [len(d) for _, d in slip.records] == [48, 1220, 7768, 48, 4096, 48]
    fs = FileSystem(Disc(2048))
    labtape.restore(fs, tape)
    for name in fs.files(":UTIL"):
        cfu = fs.open(name, ":UTIL", "IN")
        assert cfu.file.check() == [], name
        fs.close(cfu)
