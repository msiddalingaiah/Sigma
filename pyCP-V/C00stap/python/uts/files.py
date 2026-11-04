"""Keyed files, directories, OPEN and CLOSE on a disc of granules. See docs/files.md.

Translated from c00co/WRTF.txt (INST, COMPLEN, INSTN, MULCHK, ENTKEYUB/IMAGEREC,
INITMI), RDF.txt (SETUPUB, LOCCODEUB, MLCHK, the key compare 1A3), MUL.txt (the
pyramid build at close), CLS.txt (CLSFILD) and FIX1.txt (VALBUF, FNDKEY, FITCHK, as
``check``). Comments of the form ``# FILE:NNN`` point at the source.

The blocks are byte-exact: 2048-byte granules, a 3-word header (BLINK, FLINK and the
control word), entries from byte 12 (MIDIS), the FIT in the last 80 words of the
first block. The algorithms follow the source's decisions (where an entry goes, when
a block overflows, which block an upper-level entry names); the code around them
(buffers, the DCB, I/O, dual copies) is Python.

Simplifications (also in python/README.md):
- A rewrite of an existing key deletes its entries and inserts the record again
  (REWRITEUB reuses space in place). Deleting clears the entries' key counts, the
  deleted-entry mark FIX1 and RDF skip (DLT.txt wasn't read).
- The search doesn't start from the block left in the buffer by the last CAL.
- Upper-level blocks use the same room check as level 0 (MUL's COMP wasn't read),
  and the old pyramid's granules are released rather than reused.
- The FIT holds the X'09', X'0C' and X'0D' VLPs FIX1 requires, written at create and
  close (CLS's FIT update wasn't read).
"""

from dataclasses import dataclass, field

GRAN = 2048                     # BUFSIZ: bytes in a granule
MIDIS = 12                      # UTS.txt:489 displacement to the first key
WXBUFSIZ = 0x200                # WRTF.txt:21 (index blocks are full granules in C00)
FITSIZE = 80                    # WRTF.txt:45
NWFITST = WXBUFSIZ - FITSIZE    # X'1B0': the FIT's first word
UNBLOCKED = GRAN - 15           # BUFSIZ-15: a record this long gets whole granules

# Control word (word 2): NAV in the left half; flags, level and SCR in the right
F_FIT, F_FULL, F_ADDED = 0x8000, 0x4000, 0x100
LEVEL_MASK, LEVEL_SHIFT = 0x1C00, 10

# Entry flags (the byte at IMT-3)
FAK, MORE, EOFBIT = 0x04, 0x01, 0x02
CONT = 0x80                     # count-byte flag: an upper-level key for a continuation

ERR = {1: "BLINK bad", 2: "FLINK bad", 4: "keyed NAV bad", 5: "level wrong", 6: "bad SCR",
       7: "link check", 20: "key too long", 22: "data address bad", 24: "segment outside "
       "granule", 25: "size above original", 26: "flags bad", 30: "keys out of order",
       33: "VLP missing", 34: "X'09' VLP bad", 35: "X'0C' VLP bad"}


class FileError(Exception):
    def __init__(self, code, msg=""):
        super().__init__(f"error X'{code:02X}' {msg}".rstrip())
        self.code = code


# --- the disc -------------------------------------------------------------------------

class Disc:
    """Granules by disc address. GETIGRAN/GETDGRAN take from a free list (the GRAN
    stacks, refilled by ALLOCAT, aren't modeled)."""

    def __init__(self, granules=256, first=0x100):
        self.free = list(range(first, first + granules))
        self.g = {}
        self.reads = 0

    def get(self):
        if not self.free:
            return 0                                   # no granule: SATDISK
        da = self.free.pop(0)
        self.g[da] = bytearray(GRAN)
        return da

    def release(self, da):
        self.g.pop(da, None)
        self.free.append(da)

    def read(self, da):
        self.reads += 1
        if da not in self.g:
            raise FileError(0x75, f"read of an unallocated granule X'{da:X}'")
        return self.g[da]


def word(b, i):
    return int.from_bytes(b[4 * i:4 * i + 4], "big")


def setword(b, i, v):
    b[4 * i:4 * i + 4] = (v & 0xFFFFFFFF).to_bytes(4, "big")


def half(b, byte):
    return int.from_bytes(b[byte:byte + 2], "big")


def sethalf(b, byte, v):
    b[byte:byte + 2] = (v & 0xFFFF).to_bytes(2, "big")


def nav(b):
    return half(b, 8)                                  # NAV EQU 4: halfword 4


def setnav(b, v):
    sethalf(b, 8, v)


def control(b):
    return half(b, 10)


def level(b):
    return (control(b) & LEVEL_MASK) >> LEVEL_SHIFT


EBCDIC = "cp037"                # keys and names are EBCDIC on the disc, so they sort as there


def as_key(k):
    return k if isinstance(k, bytes) else str(k).encode(EBCDIC)


def text(b):
    return bytes(b).decode(EBCDIC)


# --- a keyed file ------------------------------------------------------------------------

@dataclass
class Entry:
    key: bytes
    disp: int = 0                # byte displacement in the data granule
    orig: int = 0                # original segment size
    da: int = 0                  # data granule
    size: int = 0                # current size
    flags: int = 0


class KeyedFile:
    """One keyed file: the CFU's disc addresses, the DCB's pyramid parameters, and
    the index and data granules on ``disc``."""

    def __init__(self, disc, name, keym=11, lslides=254, lrdl0=2, spare=102, log=None):
        self.disc, self.name = disc, name
        self.KEYM = keym
        self.SCR = keym + 1                            # FITCHK: SCR = KEYM+1
        self.IMT = self.SCR + 13                       # KEYSIZE = SCR+4+4+5
        self.FLAGOFF = self.IMT - 3                    # the flags byte (RDF FNDKY: IMT-3)
        self.LSLIDES, self.LRDL0, self.SPARE = lslides, lrdl0, spare   # DCB word 19
        self.TDA = 0                                   # top of the pyramid
        self.SREC = 0                                  # data granule for records
        self.CCBD = 0                                  # next free byte in it
        self.SLIDES = 0                                # CFU byte 3
        self.LDA = 0
        self.written = False
        self.log = log if log is not None else []
        self.FDA = disc.get()                          # ENTER1: the FIT granule
        b = disc.g[self.FDA]
        self._init_block(b, blink=0, flink=0, fit=True)
        self._write_fit()

    # -- blocks --------------------------------------------------------------------

    def _init_block(self, b, blink, flink, fit=False, lvl=0):
        """INITMI  WRTF.txt:1437 - the first 3 words of an index granule."""
        setword(b, 0, blink)
        setword(b, 1, flink)
        flags = F_FULL | (lvl << LEVEL_SHIFT) | (self.SCR & 0xFF) | (F_FIT if fit else 0)
        setword(b, 2, (MIDIS << 16) | flags)

    def _new_block(self, blink, flink):
        """GETIGRAN + INITMI1: a new level-0 block, counted as a slide."""
        da = self.disc.get()
        if not da:
            raise FileError(0x0A, "no granule for an index block")   # TYC X'A': saturated
        b = self.disc.g[da]
        self._init_block(b, blink, flink)
        if self.TDA:
            sethalf(b, 10, control(b) | F_ADDED)       # SET ADDED FLAG IN MI
        self.SLIDES = min(self.SLIDES + 1, 0xFF)       # INCREMENT CFU:SLIDES  :1508
        if self.SLIDES > self.LSLIDES:
            self.SLIDES = 0xFF                         # SO THAT HIGHER LEVEL REBUILT AT CLOSE
        self.log.append(f"new index block X'{da:X}' (slides {self.SLIDES})")
        return da

    def limit(self, b):
        """COMPLEN  WRTF.txt:956 - the highest NAV an insert may reach."""
        lim = -self.SPARE                              # SPARE: room kept free in the block
        if control(b) & F_FIT or word(b, 0) == 0:
            lim += NWFITST * 4 - GRAN                  # HERE'S THE FIT
        lim += GRAN - 1
        if not control(b) & F_FULL:
            lim -= GRAN // 2
        return lim

    # -- entries -------------------------------------------------------------------

    def encode(self, e):
        k = e.key
        out = bytearray(self.IMT)
        out[0] = len(k) if not e.flags & CONT else (len(k) | CONT)
        out[1:1 + len(k)] = k                          # only the key's own length moved
        p = self.SCR
        sethalf(out, p, e.disp)
        sethalf(out, p + 2, e.orig)
        out[p + 4:p + 8] = e.da.to_bytes(4, "big")
        sethalf(out, p + 8, e.size)
        out[p + 10] = e.flags & 0x7F
        return bytes(out)

    def decode(self, b, off):
        n = b[off] & 0x7F
        p = off + self.SCR
        return Entry(bytes(b[off + 1:off + 1 + n]), half(b, p), half(b, p + 2),
                     int.from_bytes(b[p + 4:p + 8], "big"), half(b, p + 8), b[p + 10])

    def offsets(self, b, size=None):
        size = size or self.IMT
        return range(MIDIS, nav(b), size)

    def first_key(self, b):
        for off in self.offsets(b):
            if b[off] & 0x7F:
                return bytes(b[off + 1:off + 1 + (b[off] & 0x7F)])
        return None

    # -- search ---------------------------------------------------------------------

    def locate(self, key):
        """SETUPUB  RDF.txt:1575 - the level-0 block and offset of the first entry
        whose key is not below ``key``; ``found`` if it is the key's FAK entry."""
        key = as_key(key)
        start = self.FDA
        if self.TDA:
            start = self._down_pyramid(key) or self.FDA
        return self._level0(start, key)

    def _down_pyramid(self, key):
        """MLCHK / MLSET  RDF.txt:1671 - from the top, a binary search per level."""
        da = self.TDA
        b = self.disc.read(da)
        while word(b, 1) and self._above(b, key):      # FLINK FORWARD FURIOUSLY
            da = word(b, 1)
            b = self.disc.read(da)
        while word(b, 0) and self._below(b, key):      # still in reverse
            da = word(b, 0)
            b = self.disc.read(da)
        while level(b) > 0:
            size = self.SCR + 4                        # upper entry: IMT-9
            offs = list(self.offsets(b, size))
            lo, hi, pick = 0, len(offs) - 1, 0
            while lo <= hi:                            # MLSET03A: binary search
                mid = (lo + hi) // 2
                if self._ukey(b, offs[mid]) <= key:
                    pick, lo = mid, mid + 1
                else:
                    hi = mid - 1
            off = offs[pick]
            promised = self._ukey(b, off)
            da = int.from_bytes(b[off + self.SCR:off + self.SCR + 4], "big")
            b = self.disc.read(da)
            if self.first_key(b) != promised and level(b) == 0:   # KEYVERIF
                self.log.append(f"75-07: block X'{da:X}' doesn't start with the upper key")
                return 0                               # HILFAIL: level 0 from FDA
        return da

    def _ukey(self, b, off):
        n = b[off] & 0x7F
        return bytes(b[off + 1:off + 1 + n])

    def _above(self, b, key):
        last = None
        for off in self.offsets(b, self.SCR + 4):
            last = self._ukey(b, off)
        nxt = self.disc.g.get(word(b, 1))
        return nxt is not None and last is not None and \
            self._ukey(nxt, MIDIS) <= key

    def _below(self, b, key):
        return nav(b) > MIDIS and key < self._ukey(b, MIDIS)

    def _level0(self, da, key):
        """LOCCODEUB  RDF.txt:1252 - forward through level 0, counting reads (RDL0)."""
        reads = 0
        while True:
            b = self.disc.read(da)
            for off in self.offsets(b):
                if not b[off] & 0x7F:
                    continue                           # IS IT SIGNIF? deleted
                e = self.decode(b, off)
                if not e.flags & FAK:
                    continue                           # continuation segments
                if e.key >= key:
                    return da, off, e.key == key
            if not word(b, 1):
                return da, nav(b), False               # past the last key
            reads += 1
            if reads > self.LRDL0:                     # congestion
                self.SLIDES = 0xFF
            da = word(b, 1)

    # -- reading --------------------------------------------------------------------

    def read_next(self, after=None):
        """A sequential read (ISEQUB without a key): the record after key ``after``
        (KBUF), in key order. Returns (key, data), or None at the end of the file."""
        if after is None:
            da, off, _ = self._level0(self.FDA, b"")
        else:
            da, off, found = self.locate(after)
            if found:
                b = self.disc.read(da)
                off += self.IMT                        # past this record's FAK entry
                if off >= nav(b) and word(b, 1):
                    da, off = word(b, 1), MIDIS
        while da:
            b = self.disc.read(da)
            while off < nav(b):
                if b[off] & 0x7F and b[off + self.FLAGOFF] & FAK:
                    key = bytes(b[off + 1:off + 1 + (b[off] & 0x7F)])
                    return key, self.read(key)
                off += self.IMT
            da, off = word(b, 1), MIDIS
        return None

    @classmethod
    def load(cls, disc, fda, log=None):
        """OPEN of an existing file: the FIT's name, X'09' (KEYM) and X'0C' (FDA, TDA,
        SREC, LDA). The next free byte of SREC isn't in the FIT: a new data granule is
        taken for the next record."""
        self = cls.__new__(cls)
        b = disc.read(fda)
        n = b[NWFITST * 4]
        name = text(b[NWFITST * 4 + 1:NWFITST * 4 + 1 + n])
        vlps, w = {}, NWFITST + 9
        while w < WXBUFSIZ:
            cw = word(b, w)
            vlps[cw >> 24] = [word(b, w + 1 + i) for i in range(cw & 0xFF)]
            if (cw >> 16) & 0xFF == 0xFF:
                break
            w += 1 + (cw & 0xFF)
        if 0x09 not in vlps or 0x0C not in vlps:
            raise FileError(0x75, "FIT inconsistency")  # 75-03
        keym = (vlps[0x09][0] >> 16) & 0xFF
        self.disc, self.name, self.log = disc, name, log if log is not None else []
        self.KEYM, self.SCR = keym, keym + 1
        self.IMT = self.SCR + 13
        self.FLAGOFF = self.IMT - 3
        self.LSLIDES, self.LRDL0, self.SPARE = 254, 2, 102   # DFRDL0 defaults
        c = vlps[0x0C]
        self.FDA, self.TDA, self.SREC, self.LDA = c[0], c[4], c[5], c[6]
        self.CCBD, self.SLIDES, self.written = GRAN, 0, False
        return self

    def read(self, key):
        """A keyed read: the FAK entry, then its continuations (MORE)."""
        da, off, found = self.locate(key)
        if not found:
            return None
        out = bytearray()
        for e in self._segments(da, off):
            if e.size:
                out += self.disc.read(e.da)[e.disp:e.disp + e.size]
        return bytes(out)

    def _segments(self, da, off):
        while True:
            b = self.disc.read(da)
            e = self.decode(b, off)
            yield e
            if not e.flags & MORE:
                return
            off += self.IMT
            while off >= nav(b):
                da = word(b, 1)
                b = self.disc.read(da)
                off = MIDIS

    def keys(self):
        da, out = self.FDA, []
        while da:
            b = self.disc.read(da)
            for off in self.offsets(b):
                if b[off] & 0x7F and b[off + self.FLAGOFF] & FAK:
                    out.append(text(b[off + 1:off + 1 + (b[off] & 0x7F)]))
            da = word(b, 1)
        return out

    # -- writing --------------------------------------------------------------------

    def write(self, key, data, newkey=False, onewkey=True):
        """IOSEQUB1 / ENTKEYUB  WRTF.txt:262, :1523 - write a record by key. NEWKEY: the
        key must be new; ONEWKEY: old or new; neither: it must exist (a rewrite)."""
        key, data = as_key(key), bytes(data)
        if not 0 < len(key) <= self.KEYM:
            raise FileError(0x42, "key length")        # KEY LENGTH ERROR (1A4)
        da, off, found = self.locate(key)
        if found:
            if newkey and not onewkey:
                raise FileError(0x16, "NEWKEY on an existing key")   # KEYER2
            self.delete(key)
            da, off, found = self.locate(key)
        elif not (newkey or onewkey):
            raise FileError(0x13, "no NEWKEY for a key that doesn't exist")   # KEYER4
        self.written = True
        segments = list(self._place(data))
        for i, (dda, disp, size) in enumerate(segments):
            flags = (FAK if i == 0 else 0) | (MORE if i < len(segments) - 1 else 0)
            e = Entry(key, disp, size, dda, size, flags)
            da, off = self.insert(da, off, self.encode(e))
            off += self.IMT                            # the next segment goes after it

    def _place(self, data):
        """The blocking routine (ENTKEYUB1, BLK1-BLK4A): segments in data granules."""
        if not data:
            yield 0, 0, 0                              # IMGZ: a zero-length record
            return
        rest = memoryview(data)
        while rest:
            if len(data) >= UNBLOCKED:                 # unblocked: whole granules
                da = self._data_granule()
                n = min(GRAN, len(rest))
                self.disc.g[da][:n] = rest[:n]
                yield da, 0, n
            else:
                if not self.SREC or self.CCBD >= GRAN:
                    self.SREC, self.CCBD = self._data_granule(), 0
                n = min(GRAN - self.CCBD, len(rest))   # SVSIZ
                self.disc.g[self.SREC][self.CCBD:self.CCBD + n] = rest[:n]
                yield self.SREC, self.CCBD, n
                self.CCBD = (self.CCBD + n + 3) & ~3   # word-aligned next position
            rest = rest[n:]

    def _data_granule(self):
        da = self.disc.get()                           # GETDGRAN
        if not da:
            raise FileError(0x0A, "no data granule")   # SATDISK
        return da

    def insert(self, da, off, entry):
        """INST  WRTF.txt:600 - put an entry at ``off`` in block ``da``. Returns where
        it went (block, offset)."""
        b = self.disc.read(da)
        # TO POSITION INSERTION WITH RESPECT TO DELETED ENTRIES (skip them)
        if off == nav(b):                              # INST2D: at the end of the block
            if nav(b) + self.IMT <= self.limit(b):
                return self._put(da, off, entry)
            nxt = word(b, 1)
            if not nxt:                                # NO FLINK - ADD NEW GRANULE AT EOF
                new = self._new_block(da, 0)
                setword(b, 1, new)
                return self._put(new, MIDIS, entry)
            return self.insert(nxt, MIDIS, entry)      # INST2A: try the next block
        if off == MIDIS and self._pointed_at(b) and word(b, 0):   # INST4 / MULCHK
            prev = word(b, 0)
            pb = self.disc.read(prev)
            if nav(pb) + self.IMT <= self.limit(pb):
                return self._put(prev, nav(pb), entry)  # at the end of the previous block
            return self._new_between(prev, entry)
        if nav(b) + self.IMT <= self.limit(b):         # INST3: room enough
            return self._put(da, off, entry)
        nxt = word(b, 1)                               # INST3A3: the next block
        if nxt:
            nb = self.disc.read(nxt)
            if not self._pointed_at(nb) and nav(nb) + self.IMT <= self.limit(nb):
                self._move_last(b, nxt)                # LAST KEY ... TO FIRST POSITION IN BUFF3
                return self._put(da, off, entry)
        new = self._new_block(da, nxt)                 # INSTN: build a new block
        if nxt:
            setword(self.disc.read(nxt), 0, new)
        setword(b, 1, new)
        self._move_last(b, new)
        return self._put(da, off, entry)

    def _new_between(self, prev, entry):
        pb = self.disc.read(prev)
        nxt = word(pb, 1)
        new = self._new_block(prev, nxt)
        setword(pb, 1, new)
        if nxt:
            setword(self.disc.read(nxt), 0, new)
        return self._put(new, MIDIS, entry)

    def _pointed_at(self, b):
        """MULCHK  WRTF.txt:893 - with a pyramid, a block not added since the build."""
        return bool(self.TDA) and not control(b) & F_ADDED

    def _put(self, da, off, entry):
        b = self.disc.read(da)
        n = nav(b)
        b[off + self.IMT:n + self.IMT] = b[off:n]      # SLIDE DOWN KEYS
        b[off:off + self.IMT] = entry
        setnav(b, n + self.IMT)
        return da, off

    def _move_last(self, b, to):
        """Move ``b``'s last entry to the first position of block ``to``."""
        n = nav(b) - self.IMT
        last = bytes(b[n:n + self.IMT])
        b[n:n + self.IMT] = bytes(self.IMT)
        setnav(b, n)
        self._put(to, MIDIS, last)

    def delete(self, key):
        """Clear the key count of the record's entries (the deleted-entry mark)."""
        da, off, found = self.locate(key)
        if not found:
            return False
        for seg_da, seg_off in self._segment_positions(da, off):
            self.disc.read(seg_da)[seg_off] = 0
        self.written = True
        return True

    def _segment_positions(self, da, off):
        while True:
            b = self.disc.read(da)
            flags = b[off + self.FLAGOFF]
            yield da, off
            if not flags & MORE:
                return
            off += self.IMT
            while off >= nav(b):
                da, off = word(b, 1), MIDIS
                b = self.disc.read(da)

    # -- close and the pyramid ----------------------------------------------------------

    def close(self):
        """CLSFILD  CLS.txt:1424 - rebuild the pyramid if the slides passed LSLIDES."""
        if self.written and self.SLIDES > self.LSLIDES:
            self.build_pyramid()
        self._write_fit()
        self.written = False

    def build_pyramid(self):
        """MUL  MUL.txt - level 1 from the first key of each level-0 block, and on up
        while a level has more than 3 blocks."""
        self._drop_pyramid()
        lower, lvl = self._level0_blocks(), 0
        while True:
            lvl += 1
            blocks = self._build_level(lower, lvl)
            if not blocks:
                self.TDA = 0
                return
            if len(blocks) > 3:
                lower = blocks
                continue
            self.TDA = blocks[1] if len(blocks) == 3 else blocks[0]   # MIDDLE IS TOP
            break
        self.SLIDES = 1                                # SLIDES TO 1
        for da in self._level0_blocks():
            b = self.disc.read(da)
            sethalf(b, 10, control(b) & ~F_ADDED)
        self.log.append(f"pyramid: {lvl} level(s), top X'{self.TDA:X}'")

    def _level0_blocks(self):
        out, da = [], self.FDA
        while da:
            out.append(da)
            da = word(self.disc.read(da), 1)
        return out

    def _build_level(self, lower, lvl):
        """STRTALEV / MOVEAKEY  MUL.txt:203, :245"""
        size, blocks, cur = self.SCR + 4, [], None
        for da in lower:
            b = self.disc.read(da)
            if lvl == 1:
                self._slide_deleted_firsts(b)
            if nav(b) <= MIDIS:
                continue
            first = bytearray(b[MIDIS:MIDIS + 1 + (b[MIDIS] & 0x7F)])
            if lvl == 1 and not b[MIDIS + self.FLAGOFF] & FAK:
                first[0] |= CONT                       # NOT FIRST: + X'80'
            ent = bytearray(size)
            ent[:len(first)] = first
            ent[self.SCR:self.SCR + 4] = da.to_bytes(4, "big")
            if cur is None or nav(self.disc.read(cur)) + size > self.limit(self.disc.read(cur)):
                new = self.disc.get()
                if not new:
                    raise FileError(0x0C, "partial higher level index built")
                self._init_block(self.disc.g[new], cur or 0, 0, lvl=lvl)
                if cur:
                    setword(self.disc.read(cur), 1, new)
                blocks.append(new)
                cur = new
            cb = self.disc.read(cur)
            n = nav(cb)
            cb[n:n + size] = ent
            setnav(cb, n + size)
        return blocks

    def _slide_deleted_firsts(self, b):
        """MOVEAKEY's level-0 case: deleted first keys are slid out of the block."""
        while nav(b) > MIDIS and not b[MIDIS] & 0x7F:
            n = nav(b)
            b[MIDIS:n - self.IMT] = b[MIDIS + self.IMT:n]
            b[n - self.IMT:n] = bytes(self.IMT)
            setnav(b, n - self.IMT)

    def _drop_pyramid(self):
        if not self.TDA:
            return
        seen, todo = set(), [self.TDA]
        while todo:                                    # every upper block, any level
            da = todo.pop()
            if da in seen or da not in self.disc.g:
                continue
            b = self.disc.g[da]
            if level(b) == 0:
                continue
            seen.add(da)
            todo += [word(b, 0), word(b, 1)]
            for off in self.offsets(b, self.SCR + 4):
                todo.append(int.from_bytes(b[off + self.SCR:off + self.SCR + 4], "big"))
        for da in seen:
            self.disc.release(da)
        self.TDA = 0

    # -- the FIT ---------------------------------------------------------------------

    def _write_fit(self):
        """The FIT at word X'1B0' of the first block: the name, then the VLPs."""
        b = self.disc.g[self.FDA]
        b[NWFITST * 4:] = bytes(GRAN - NWFITST * 4)
        name = as_key(self.name)[:31]
        b[NWFITST * 4] = len(name)
        b[NWFITST * 4 + 1:NWFITST * 4 + 1 + len(name)] = name
        w = NWFITST + 9                                # FIT10: AI,R1 9
        vlps = [(0x09, [(2 << 24) | (self.KEYM << 16), 0, 0]),
                (0x0C, [self.FDA, 0, 0, 0, self.TDA, self.SREC, self.LDA]),
                (0x0D, [0])]
        for i, (code, data) in enumerate(vlps):
            last = 0xFF if i == len(vlps) - 1 else 0
            setword(b, w, (code << 24) | (last << 16) | (len(data) << 8) | len(data))
            for j, v in enumerate(data):
                setword(b, w + 1 + j, v)
            w += 1 + len(data)

    # -- FIX1's checks -----------------------------------------------------------------

    def check(self):
        """FITCHK, VALBUF and FNDKEY  FIX1.txt:1758, :2103, :2194 - a list of
        (block, offset, error number)."""
        errors = []
        errors += self._check_fit()
        prev_key, prev_da = None, 0
        for da in self._level0_blocks():
            b = self.disc.read(da)
            errors += self._valbuf(da, b, 0, prev_da)
            for off in self.offsets(b):
                if not b[off] & 0x7F:
                    continue                           # FND40: deleted
                e = self.decode(b, off)
                if len(e.key) >= self.SCR:
                    errors.append((da, off, 20))
                if e.flags & FAK and prev_key is not None and e.key < prev_key:
                    errors.append((da, off, 30))       # ORDRFLAG: out of order
                if e.flags & 0xF8:
                    errors.append((da, off, 26))
                if e.da == 0 and e.orig != 0:
                    errors.append((da, off, 22))
                elif e.da and e.da not in self.disc.g:
                    errors.append((da, off, 22))
                if e.disp + e.orig > GRAN:
                    errors.append((da, off, 24))
                if e.size > e.orig:
                    errors.append((da, off, 25))
                if e.flags & FAK:
                    prev_key = e.key
            prev_da = da
        return errors

    def _valbuf(self, da, b, lvl, prev_da):
        errors = []
        if word(b, 0) != prev_da:
            errors.append((da, 0, 7))                  # LINK CHECK FAILURE
        if word(b, 1) and word(b, 1) not in self.disc.g:
            errors.append((da, 0, 2))
        n = nav(b)
        if n < MIDIS or n > 0x800 or (n - MIDIS) % self.IMT:
            errors.append((da, 0, 4))
        if level(b) != lvl:
            errors.append((da, 0, 5))
        if control(b) & 0xFF != self.SCR:
            errors.append((da, 0, 6))
        return errors

    def _check_fit(self):
        b = self.disc.read(self.FDA)
        if not control(b) & F_FIT:
            return [(self.FDA, 0, 3)]
        found, w = {}, NWFITST + 9
        while w < WXBUFSIZ:
            cw = word(b, w)
            found[cw >> 24] = (w + 1, cw & 0xFF)
            if (cw >> 16) & 0xFF == 0xFF:
                break
            w += 1 + (cw & 0xFF)
        errors = []
        for code, minimum, err in ((0x0D, 1, 33), (0x09, 3, 34), (0x0C, 7, 35)):
            if code not in found:
                errors.append((self.FDA, 0, 33))
            elif found[code][1] < minimum:
                errors.append((self.FDA, 0, err))
        if 0x09 in found and (word(b, found[0x09][0]) >> 24) != 2:
            errors.append((self.FDA, 0, 34))
        return errors


# --- directories ----------------------------------------------------------------------------

class Directory(KeyedFile):
    """An account or file directory: an index chain like a keyed file's level 0, with
    the directory entry formats (docs/files.md section 2) and no FIT, data or pyramid.

    Account entries: the account (TEXTC, 8 characters), the file directory's main and
    dual addresses (3 bytes each), flags at IMT-1 (RDF FNDKY: ACNCFU), 18 bytes in all.
    File entries: the name (TEXTC, up to 31), the FIT's address (4 bytes), flags at
    IMT-3, 41 bytes. The dual copies aren't kept: their words are reserved, zero."""

    def __init__(self, disc, kind, log=None, fda=None):
        self.disc, self.name, self.kind = disc, kind, kind
        self.log = log if log is not None else []
        self.SCR = 9 if kind == "AD" else 32           # ADSCR, FDSCR  FIX1.txt:62
        self.KEYM = self.SCR - 1
        self.IMT = 18 if kind == "AD" else 41          # ADKSIZE, FDKSIZE
        self.FLAGOFF = self.IMT - 1 if kind == "AD" else self.IMT - 3
        self.LSLIDES, self.LRDL0, self.SPARE = 255, 255, 0
        self.TDA = self.SREC = self.LDA = self.SLIDES = 0
        self.CCBD, self.written = GRAN, False
        if fda is None:
            self.FDA = disc.get()
            self._init_block(disc.g[self.FDA], 0, 0)
        else:
            self.FDA = fda

    def limit(self, b):
        """COMPLEN's directory case: two spare entry slots at the end (four in the
        first granule), and 11 bytes for the dual links (COMPLEN6)."""
        spare = 2 * self.IMT * (2 if word(b, 0) == 0 else 1)
        return GRAN - 1 - spare - 11

    def encode(self, e):
        out = bytearray(self.IMT)
        out[0] = len(e.key)
        out[1:1 + len(e.key)] = e.key
        if self.kind == "AD":
            out[self.SCR:self.SCR + 3] = e.da.to_bytes(3, "big")          # main
            out[self.SCR + 3:self.SCR + 6] = e.disp.to_bytes(3, "big")    # dual
        else:
            out[self.SCR:self.SCR + 4] = e.da.to_bytes(4, "big")          # the FIT
        out[self.FLAGOFF] = e.flags
        return bytes(out)

    def decode(self, b, off):
        n = b[off] & 0x7F
        p = off + self.SCR
        if self.kind == "AD":
            da, dual = int.from_bytes(b[p:p + 3], "big"), int.from_bytes(b[p + 3:p + 6], "big")
        else:
            da, dual = int.from_bytes(b[p:p + 4], "big"), 0
        return Entry(bytes(b[off + 1:off + 1 + n]), dual, 0, da, 0, b[off + self.FLAGOFF])

    def find(self, key):
        da, off, found = self.locate(key)
        return self.decode(self.disc.read(da), off).da if found else 0

    def add(self, key, address):
        """INST for a directory: a new entry, flagged FAK as RDF's FNDKY expects."""
        key = as_key(key)
        da, off, found = self.locate(key)
        if found:
            raise FileError(0x08, f"{self.kind} entry exists")
        self.insert(da, off, self.encode(Entry(key, 0, 0, address, 0, FAK)))

    def remove(self, key):
        da, off, found = self.locate(key)
        if found:
            self.disc.read(da)[off] = 0                # deleted entry
        return found


def account_key(account):
    return as_key(str(account)[:8].ljust(8))           # 8 characters, EBCDIC blanks


# --- the file system: OPEN and CLOSE --------------------------------------------------------

@dataclass
class Cfu:
    """A CFU (UTS.txt:448): one per open file, shared by the DCBs that have it open."""
    account: str
    name: str
    file: object
    nou: int = 1                 # NOU: number of users
    new: bool = False            # created by this open: entered in the directory at close
    fd: object = None


class FileSystem:
    """The account directory (ACNCFU's FDA), the file directories, and the open
    files' CFUs. ``mount`` finds everything again from the account directory alone."""

    def __init__(self, disc=None, log=None, ad_fda=None):
        self.disc = disc or Disc(1024)
        self.log = log if log is not None else []
        self.ad = Directory(self.disc, "AD", self.log, fda=ad_fda)
        self.cfus = {}

    @classmethod
    def mount(cls, disc, ad_fda, log=None):
        return cls(disc, log, ad_fda)

    def add_account(self, account):
        """A new account and its empty file directory (SUPER's job; a stand-in)."""
        if self.ad.find(account_key(account)):
            return
        fd = Directory(self.disc, "FD", self.log)
        self.ad.add(account_key(account), fd.FDA)

    def file_directory(self, account):
        fda = self.ad.find(account_key(account))
        if not fda:
            raise FileError(0x03, f"no such account {account}")
        return Directory(self.disc, "FD", self.log, fda=fda)

    def files(self, account):
        return self.file_directory(account).keys()

    def open(self, name, account, mode="IN", keym=11, lslides=254, lrdl0=2, spare=102):
        """OPNF  OPNF.txt - the CFU scan, then the directory search, then the FIT.
        ``mode`` is IN, OUT, INOUT or UPDATE; a missing file is created for any but IN."""
        ident = (account_key(account), as_key(name))
        cfu = self.cfus.get(ident)
        if cfu is not None:                            # CFU SCAN: already open
            cfu.nou += 1
            return cfu
        fd = self.file_directory(account)
        fit = fd.find(name)
        if fit:
            kf = KeyedFile.load(self.disc, fit, self.log)
            kf.LSLIDES, kf.LRDL0, kf.SPARE = lslides, lrdl0, spare
            new = False
        elif mode == "IN":
            raise FileError(0x03, f"no such file {name}")
        else:
            kf = KeyedFile(self.disc, name, keym, lslides, lrdl0, spare, self.log)   # ENTER1
            new = True
        cfu = self.cfus[ident] = Cfu(account, name, kf, new=new, fd=fd)
        self.log.append(f"OPEN {name}.{account} {mode}: FIT X'{kf.FDA:X}'"
                        + (" (new)" if new else ""))
        return cfu

    def close(self, cfu, release=False):
        """CLSFIL  CLS.txt:1438 - the pyramid and the FIT; a new file goes into its
        directory (CLSFIL4); the CFU goes when its last user closes."""
        cfu.file.close()
        if cfu.new and not release:
            cfu.fd.add(cfu.name, cfu.file.FDA)
            cfu.new = False
        cfu.nou -= 1
        if cfu.nou <= 0:
            self.cfus.pop((account_key(cfu.account), as_key(cfu.name)), None)
        self.log.append(f"CLOSE {cfu.name}.{cfu.account}")
