"""Granule allocation, keyed, consecutive and random files, directories, OPEN and
CLOSE on a disc of granules. See docs/files.md.

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
  (REWRITEUB reuses space in place). Deleting follows DLT.txt DEL: entries slid out,
  except control keys (displacement 0) and first entries, which stay null.
- The search doesn't start from the block left in the buffer by the last CAL.
- Upper-level blocks use the same room check as level 0 (MUL's COMP wasn't read),
  and the old pyramid's granules are released rather than reused.
- The FIT holds the X'09', X'0C' and X'0D' VLPs FIX1 requires, written at create and
  close (CLS's FIT update wasn't read).
- Consecutive files (ConsecutiveFile, from WRTF/RDF SEQ0, DLT and FIX1 CHKCON) read
  forward only: no backward reads, positioning CALs, read-ahead or volume switching.
"""

from dataclasses import dataclass, field

from .sched import Buffer

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


# --- the disc: granule allocation (docs/files.md section 8) ---------------------------

class Hgp:
    """One device's allocation table (GRANSUB.txt): its PFA bit map, a set bit a free
    granule, and where the last single get stopped (word 3). A public device allocated by
    granule; PER, cylinders and other devices aren't modeled."""

    def __init__(self, first, granules):
        self.first, self.n = first, granules
        self.map = bytearray(b"\xff" * (granules // 8))
        if granules % 8:
            self.map.append((0xFF << (8 - granules % 8)) & 0xFF)
        self.last = 0                                  # word 3: the last bit gotten
        self.dual = []                                 # LOGDUAL error records

    def _bit(self, i):
        return self.map[i >> 3] & (0x80 >> (i & 7))

    def _set(self, i, on):
        if on:
            self.map[i >> 3] |= 0x80 >> (i & 7)
        else:
            self.map[i >> 3] &= ~(0x80 >> (i & 7)) & 0xFF

    def get(self):
        """CMNGG / GETBIT  :87, :258 - the next set bit from where the last get stopped,
        then from the start (GBIT0's full search). 0 if the map is empty (SETEMPTY)."""
        for i in list(range(self.last, self.n)) + list(range(0, self.last)):
            if self._bit(i):
                self._set(i, False)                    # GBIT5: ZAP BIT
                self.last = i
                return self.first + i
        return 0

    def get_n(self, count):
        """CMNGNG  :105 - a run of ``count`` free granules, searched for from the end of
        the map backward. Returns its first address, or 0."""
        run = 0
        for i in range(self.n - 1, -1, -1):
            run = run + 1 if self._bit(i) else 0
            if run == count:
                for j in range(i, i + count):
                    self._set(j, False)
                return self.first + i
        return 0

    def release(self, da, count=1):
        """CMNRG / CMNRNG  :362 - set the bits. One already set is a dual allocation:
        logged (LOGDUAL), and the release goes on. False for an address not in the map."""
        i = da - self.first
        if i < 0 or i + count > self.n:
            return False                               # GGERRET: BAD DISC ADDRESS
        for j in range(i, i + count):
            if self._bit(j):
                self.dual.append(self.first + j)
            self._set(j, True)
        return True

    def free(self):
        return [self.first + i for i in range(self.n) if self._bit(i)]


# HGPSTK.txt:17-28: the pack stack's size and levels
STACK_SLOTS, LOLEVEL, HILEVEL, LOTHRSH, HITHRSH = 128, 40, 80, 16, 100
F_HGPEMPTY, F_EMPTIED, F_FILLED, F_BUSY = 0x8000, 0x4000, 0x2000, 0x0001


class Stack(Buffer):
    """One of HGPSTK's circular stacks of free disc addresses (the pack one). The
    scheduler's STUQFAC commits ALLOCAT's changes to it (sched.Buffer.unqueue)."""

    def __init__(self, slots=STACK_SLOTS):
        super().__init__(BUFMASK=slots - 1)
        self.slots = [0] * slots                       # CATBUF
        self.TOP = 0

    def addresses(self):
        """What the stack holds, ALLOCAT's pending fill included."""
        return [a for a in self.slots if a]


class Disc:
    """Granules by disc address, handed out as GRAN does: GBG pops the stack and RBG
    pushes it (GRAN.txt), ALLOCAT fills and empties it from the bit map (ALLYCAT.txt
    ADJBUFS), and STUQFAC makes that real. ``cat`` starts the ALLOCAT ghost (THRESH);
    without one, nothing starts it. ``ad_fda`` is where the account directory starts
    (ACNCFU's FDA; how the real start-up finds it hasn't been read)."""

    def __init__(self, granules=256, first=0x100):
        self.hgp = Hgp(first, granules)
        self.stack = Stack()
        self.g = {}
        self.reads = 0
        self.ad_fda = 0
        self.cat = None
        self.log = []

    # -- GRAN: the user's side ---------------------------------------------------------

    def get(self):
        """GBG / GETGRAN  GRAN.txt:193 - pop the stack. Empty, a user waits on E:QFAC
        while ALLOCAT fills it; here ALLOCAT's turn, and the commit, come at once. 0 if
        the bit map is empty too (SATDISK)."""
        s = self.stack
        for _ in range(2):
            if s.TOP != s.BOTTOM or s.BUFLAGS & F_HGPEMPTY:
                break
            self.allocat()                             # REG4CAT: the CAT runs ...
            self.commit()                              # ... and is swapped out (E:UQFAC)
        if s.TOP == s.BOTTOM:
            return 0                                   # RELX
        s.TOP = (s.TOP - 1) & s.BUFMASK                # GETONE
        s.WORDCNT -= 1
        da, s.slots[s.TOP] = s.slots[s.TOP], 0         # XW,R8 0,R4
        self._chkthrsh()
        self.g[da] = bytearray(GRAN)
        return da

    def release(self, da):
        """RBG  GRAN.txt:95, :144 - push the address. With no room, it goes to ALLOCAT
        in a message (NORELROM), which releases it into the map; here at once."""
        self.g.pop(da, None)
        s = self.stack
        if s.TOP == s.TEMPBOT and s.WORDCNT:
            self._to_map(da)                           # ALLOCAT RELN
            return
        s.slots[s.TOP] = da                            # ROOM
        s.TOP = (s.TOP + 1) & s.BUFMASK
        s.WORDCNT += 1
        self._chkthrsh()

    def _chkthrsh(self):
        """CHKTHRSH  GRAN.txt:230 - start ALLOCAT at a threshold."""
        s = self.stack
        if s.WORDCNT >= HITHRSH or (s.WORDCNT <= LOTHRSH and not s.BUFLAGS & F_HGPEMPTY):
            if self.cat:
                self.cat()                             # THRESH: T:GJOBSTRT 'ALLOCAT'

    def get_n(self, count):
        """GNBG  GRAN.txt:253 - ``count`` contiguous granules for a random file, from
        ALLOCAT (GETN: CMNGNG). The user waits for the answer; here it comes at once."""
        da = self.hgp.get_n(count)
        if da:
            for a in range(da, da + count):
                self.g[a] = bytearray(GRAN)
        return da

    def release_n(self, da, count):
        """RNBG  GRAN.txt:281 - give a run back (ALLOCAT RELN: CMNRNG)."""
        for a in range(da, da + count):
            self.g.pop(a, None)
        self._to_map(da, count)

    def read(self, da):
        self.reads += 1
        if da not in self.g:
            raise FileError(0x75, f"read of an unallocated granule X'{da:X}'")
        return self.g[da]

    # -- ALLOCAT's side ------------------------------------------------------------------

    def _to_map(self, da, count=1):
        if not self.hgp.release(da, count):
            self.log.append(f"ALLOCAT: bad disc address X'{da:X}'")   # LOGERR
        self.stack.BUFLAGS &= 0x7FFF                   # M15: REMOVE EMPTY HGP BIT

    def allocat(self):
        """ADJBUFS  ALLYCAT.txt:330 - one stack: fill it to HILEVEL from at or below
        LOLEVEL (FILL), or empty it to LOLEVEL from above HILEVEL (EMPTY1). The changes
        stay pending (TEMPBOT, ADJSTCNT) until STUQFAC."""
        s = self.stack
        if s.BUFLAGS & (F_EMPTIED | F_FILLED | F_BUSY):
            return                                     # NOT FOR THIS ONE YET
        s.BUFLAGS |= F_BUSY
        s.ADJSTCNT, n = 0, s.WORDCNT
        if n <= LOLEVEL:                               # FILL
            if s.BUFLAGS & F_HGPEMPTY:
                return
            want = HILEVEL - n
            s.TEMPBOT = (s.BOTTOM - want) & s.BUFMASK
            at = s.BOTTOM
            for _ in range(want):
                da = self.hgp.get()
                if not da:
                    s.TEMPBOT = at                     # WHERE WE STOPPED
                    s.BUFLAGS |= F_HGPEMPTY | F_FILLED  # X'A000'
                    return
                at = (at - 1) & s.BUFMASK
                s.slots[at] = da
                s.ADJSTCNT += 1
            s.BUFLAGS |= F_FILLED
        elif n > HILEVEL:                              # empty
            k = n - LOLEVEL
            s.BOTTOM = (s.BOTTOM + k) & s.BUFMASK
            at = s.TEMPBOT
            for _ in range(k):
                s.ADJSTCNT -= 1                        # FIRST, FOR A CRASH
                da, s.slots[at] = s.slots[at], 0
                at = (at + 1) & s.BUFMASK
                self._to_map(da)
            s.BUFLAGS |= F_EMPTIED

    def commit(self):
        """STUQFAC for this stack, as when the swapper takes ALLOCAT out (E:UQFAC)."""
        if not self.stack.unqueue():
            raise FileError(0x88, "allocation stack count past its size (SCREECH X'88')")

    @property
    def free(self):
        """Every granule not in a file: the map's free bits and the stack's addresses."""
        return self.hgp.free() + self.stack.addresses()


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


# --- the FIT ---------------------------------------------------------------------------

def put_fit(b, at, end, name, vlps):
    """A FIT from word ``at`` (up to ``end``): the name as TEXTC in 9 words, then the
    VLPs, each behind a control word (code, X'FF' on the last, words used, reserved)."""
    b[at * 4:end * 4] = bytes((end - at) * 4)
    name = as_key(name)[:31]
    b[at * 4] = len(name)
    b[at * 4 + 1:at * 4 + 1 + len(name)] = name
    w = at + 9                                         # FIT10: AI,R1 9
    for i, (code, data) in enumerate(vlps):
        last = 0xFF if i == len(vlps) - 1 else 0
        setword(b, w, (code << 24) | (last << 16) | (len(data) << 8) | len(data))
        for j, v in enumerate(data):
            setword(b, w + 1 + j, v)
        w += 1 + len(data)


def read_fit(b, at, end):
    """The FIT's name and its VLPs, {code: [words]}."""
    n = b[at * 4]
    name = text(b[at * 4 + 1:at * 4 + 1 + n])
    vlps, w = {}, at + 9
    while w < end:
        cw = word(b, w)
        vlps[cw >> 24] = [word(b, w + 1 + i) for i in range(cw & 0xFF)]
        if (cw >> 16) & 0xFF == 0xFF:
            break
        w += 1 + (cw & 0xFF)
    return name, vlps


def check_fit(disc, fda, at, end, org):
    """FITCHK  FIX1.txt:1758 - the VLPs FIX1 requires, and the organization in X'09'."""
    b = disc.read(fda)
    found, w = {}, at + 9
    while w < end:
        cw = word(b, w)
        found[cw >> 24] = (w + 1, cw & 0xFF)
        if (cw >> 16) & 0xFF == 0xFF:
            break
        w += 1 + (cw & 0xFF)
    errors = []
    for code, minimum, err in ((0x0D, 1, 33), (0x09, 3, 34), (0x0C, 7, 35)):
        if code not in found:
            errors.append((fda, 0, 33))
        elif found[code][1] < minimum:
            errors.append((fda, 0, err))
    if 0x09 in found and (word(b, found[0x09][0]) >> 24) != org:
        errors.append((fda, 0, 34))
    return errors


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
            if level(b) == 1 and pick > 0 and b[offs[pick]] & CONT                     and self._ukey(b, offs[pick]) == key:
                pick -= 1                              # MLSET00: a continuation key: BACK UP
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
        name, vlps = read_fit(disc.read(fda), NWFITST, WXBUFSIZ)
        if 0x09 not in vlps or 0x0C not in vlps:
            raise FileError(0x75, "FIT inconsistency")  # 75-03
        keym = (vlps[0x09][0] >> 16) & 0xFF
        self.disc, self.name, self.log = disc, name, log if log is not None else []
        self.prot = {c: w for c, w in vlps.items() if c in PROTECTION}
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
        """DEL  DLT.txt:195 - each of the record's entries loses its key (count 0, the
        key bytes zeroed). Then, by its displacement and size word (CI,D1 X'F0000' is
        sign-extended: the displacement):
        - displacement 0, size X'800': a full granule, released now (DEL13), its
          displacement made 3 so it can't be released twice, and the entry slid out;
        - displacement 0 with a data granule: kept as a null 'control key', so that
          REL finds the granule later (DEL11);
        - otherwise slid out (DEL1), unless it is first in its block (DEL16)."""
        da, off, found = self.locate(key)
        if not found:
            return False
        for seg_da, seg_off in reversed(list(self._segment_positions(da, off))):
            b = self.disc.read(seg_da)
            e = self.decode(b, seg_off)
            b[seg_off:seg_off + self.SCR] = bytes(self.SCR)   # NULL KEY, ZAP UNUSED POSITIONS
            if e.disp == 0 and e.orig == GRAN:
                self.disc.release(e.da)                # DEL13: FULL GRANULE
                b[seg_off + self.SCR + 1] += 3         # MTB,3: PREVENT DOUBLE RELEASE
            elif e.disp == 0 and e.da:
                continue                               # DEL11: keep the control key
            if seg_off != MIDIS:                       # DEL16: a first entry stays
                n = nav(b)
                b[seg_off:n - self.IMT] = b[seg_off + self.IMT:n]   # DEL31: SLIDE UP
                b[n - self.IMT:n] = bytes(self.IMT)
                setnav(b, n - self.IMT)
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
        """MOVEAKEY  MUL.txt:231 - level 0: a deleted (null) first key is slid out of
        the block, unless its displacement's low byte is 0 (ZERO BLDISP: it may be a
        control key REL needs) or it is the block's only entry (DON'T EMPTY SECTOR)."""
        while nav(b) > MIDIS and not b[MIDIS] & 0x7F:
            if b[MIDIS + self.SCR + 1] == 0 or MIDIS + self.IMT >= nav(b):
                break
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

    def release(self):
        """REL  DLT.txt:665 - the upper levels (MUL entry 1), then each level-0 block:
        the data granule of every entry at displacement 0 (REL9), null entries too,
        and the block itself (REL29)."""
        self._drop_pyramid()
        for da in self._level0_blocks():
            b = self.disc.read(da)
            for off in self.offsets(b):
                e = self.decode(b, off)
                if e.disp == 0 and e.da:               # DISPL = 0, RELEASE GRANULE
                    self.disc.release(e.da)
            self.disc.release(da)
        self.FDA = self.LDA = self.SREC = self.TDA = 0

    # -- the FIT ---------------------------------------------------------------------

    def _write_fit(self):
        """The FIT at word X'1B0' of the first block: the name, then the VLPs."""
        put_fit(self.disc.g[self.FDA], NWFITST, WXBUFSIZ, self.name,
                fit_protection(getattr(self, "prot", {}), NWFITST) +
                [(0x09, [(2 << 24) | (self.KEYM << 16), 0, 0]),
                 (0x0C, [self.FDA, 0, 0, 0, self.TDA, self.SREC, self.LDA]),
                 (0x0D, [0])])

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
        if not control(self.disc.g[self.FDA]) & F_FIT:
            return [(self.FDA, 0, 3)]
        return check_fit(self.disc, self.FDA, NWFITST, WXBUFSIZ, 2)


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
        """DELF / DEL1  DLT.txt:314, :343 - slide the entries after it up over it, and
        NAV down by one entry. An emptied block stays, its first word cleared."""
        da, off, found = self.locate(key)
        if found:
            b = self.disc.read(da)
            n = nav(b)
            b[off:n - self.IMT] = b[off + self.IMT:n]  # DEL31: SLIDE UP NULL ENTRY
            b[n - self.IMT:n] = bytes(self.IMT)
            setnav(b, n - self.IMT)                    # RESET NAV
            if n - self.IMT <= MIDIS:
                setword(b, 3, MIDIS)                   # BLITZ 1ST ENTRY
        return found


def account_key(account):
    return as_key(str(account)[:8].ljust(8))           # 8 characters, EBCDIC blanks


# --- a consecutive file ------------------------------------------------------------------

# Segment control-word flags, bits 0-3 (docs/files.md section 4)
X_UNBLK, X_FAK, X_CONT, X_BKSP = 0x8, 0x4, 0x2, 0x1
# The granule control word (word 2): flags in the left half, NAV in the right
G_UNBLK, G_FULL, G_NOTCONSEC = 0x80000000, 0x40000000, 0x3FFF0000
WBUFS = WXBUFSIZ                # BUFSIZ**-2: words in a granule
FITSEG = 0x01400000             # =FX'80B13'  WRTF.txt:298: 320 bytes, no flags
CFIT = 4                        # the FIT's first word (OPNF.txt:1746)


def gnav(b):
    return word(b, 2) & 0xFFFF                         # LH,3 BUFF1,1 (R1 = 5): halfword 5


def setgnav(b, v):
    sethalf(b, 10, v)


def flags_of(cw):
    return cw >> 28                                    # INT: the condition code


def seg_words(cw):
    """Words from a control word to the next: 1 for an unblocked one, else 1 plus the
    data (SEQFRD2  RDF.txt:2940)."""
    return 1 if cw & 0x80000000 else 1 + (((cw >> 16) & 0xFFF) + 3) // 4


@dataclass
class Position:
    """A DCB's place in a consecutive file: DCBCDAM, the word in HACMD, and W14.
    ``start`` is the last record read (M:DELREC deletes it)."""
    da: int = 0                  # 0: the beginning of the file
    w: int = 0
    rec: int = 0
    start: tuple = None


class ConsecutiveFile:
    """One consecutive file (organization 1): a chain of granules of segments, the
    FIT in the first one. Translated from WRTF.txt SEQ0 (:273), RDF.txt SEQ0, SEQPOS,
    SEQFRD (:2841-:3268), DLT.txt SEQ0 and SEQ2-SEQ9, and FIX1.txt CHKCON."""

    ORG = 1

    def __init__(self, disc, name, log=None):
        """ENTERO2  WRTF.txt:521 - the first granule at create ('PHONY FIT')."""
        self.disc, self.name = disc, name
        self.log = log if log is not None else []
        self.FDA = self.LDA = self.TDA = 0             # TDA: the number of records
        self.written = False
        self._granule(0)
        self._write_fit()

    def _granule(self, prev):
        """SEQ1C  WRTF.txt:292 - a new granule after ``prev`` (0: the first, with room
        for the FIT); the old one's FLINK points at it (SEQ1F2)."""
        da = self.disc.get()
        if not da:
            raise FileError(0x0A, "no granule for a consecutive file")   # SATDISK
        b = self.disc.g[da]
        setword(b, 0, prev)                            # BLINK
        setword(b, 1, 0)                               # FLINK = 0 FOR EOF
        if prev:
            setword(self.disc.g[prev], 1, da)
            setword(b, 3, 0)
            setword(b, 2, 3)                           # NAV = 3
        else:
            self.FDA = da
            setword(b, 3, FITSEG)                      # LOOKS LIKE DEL'D REC
            setword(b, FITSIZE + 4, 3)                 # its back pointer
            setword(b, 2, FITSIZE + 4)                 # NAV = 84
        self.LDA = da
        return da

    # -- position --------------------------------------------------------------------

    def _forward(self, da, w):
        """SEQFRD  RDF.txt:2896 - past the segment at ``w``. At the end of the file,
        the last granule and WBUFS."""
        b = self.disc.read(da)
        n = gnav(b)
        if w < n:
            w += seg_words(word(b, w))
            if w < WBUFS and w <= n:
                return da, w
        if not word(b, 1):
            return da, WBUFS                           # SEQFRD4: END OF FILE
        return word(b, 1), 3                           # SEQFRD1: the next granule

    def _seek(self, pos):
        """SEQPOS  RDF.txt:3017, forward: from the position to the next segment with
        the X'4' flag (a record's first), or the end. Returns (granule, word)."""
        da, w = (pos.da, pos.w) if pos.da else (self.FDA, 3)
        if not da:
            return 0, WBUFS                            # no granules: an empty file
        while True:
            if w < WBUFS and flags_of(word(self.disc.read(da), w)) & X_FAK:
                return da, w
            nda, nw = self._forward(da, w)
            if (nda, nw) == (da, w):
                return da, w
            da, w = nda, nw

    # -- read ------------------------------------------------------------------------

    def read(self, pos):
        """SEQ0  RDF.txt:3136, forward: the next record, or None at the end of the file
        (W14 >= TDA). The position moves past it."""
        if pos.rec >= self.TDA:
            return None                                # SEQ02: HIT EOF
        da, w = self._seek(pos)
        if w >= WBUFS:
            return None                                # UNEXPECTED EOF
        start, data, after = (da, w), b"", w
        while True:
            b = self.disc.read(da)
            cw = word(b, w)
            if cw & 0x80000000:                        # unblocked: its own granule
                n = ((cw >> 24) & 0xF) + UNBLOCKED
                data += bytes(self.disc.read(cw & 0xFFFFFF)[:n])
            else:
                n = (cw >> 16) & 0xFFF
                if n == 0:                             # SEQ3: nothing here, go on
                    nda, nw = self._forward(da, w)
                    if nw >= WBUFS or (nda, nw) == (da, w):
                        break
                    da, w = nda, nw
                    continue
                data += bytes(b[(w + 1) * 4:(w + 1) * 4 + n])
            after = w + seg_words(cw)                  # SEQE: NXT CTL WD OR END OF BFR
            if not flags_of(cw) & X_CONT:
                break
            da, w = self._forward(da, w)
            if w >= WBUFS:
                break
        pos.da, pos.w, pos.rec, pos.start = da, after, pos.rec + 1, start
        return data

    def seek_record(self, q):
        """PRECORD2 / SEQPOS  POS.txt:516, RDF.txt:3017 - a position before record ``q``
        (0 to TDA). CP-V keeps the skip in W19 and makes it at the next read; here
        the file is read from the beginning to it."""
        pos = Position()
        while pos.rec < q and self.read(pos) is not None:
            pass
        pos.start = None
        return pos

    # -- write -----------------------------------------------------------------------

    def write(self, pos, data):
        """SEQ0  WRTF.txt:273 - a record at the current granule's NAV. Not at the end
        (W14 != TDA), the file is first cut at the position (delete forward)."""
        da, w = self._seek(pos)
        if pos.rec != self.TDA:                        # SEQ01: DLT FRWD INFO
            self.delete_forward(da, w, pos.rec)
        pos.start = None
        self.written = True
        if not data:
            return                                     # SEQ1B1: no record
        if not self.FDA:
            da = self._granule(0)                      # after the whole file was deleted
        rest, first, pending = bytes(data), True, None
        b = self.disc.g[da]
        while True:
            n, full = gnav(b), word(b, 2) & G_FULL
            if full or n > WBUFS - 1 or (n == WBUFS - 1 and len(rest) < UNBLOCKED):
                da = self._granule(da)                 # SEQ1G, SEQ1F: a new granule
                b = self.disc.g[da]
                continue
            if pending is not None:                    # SEQ2B: GET ABORTED CTL WD
                flags, pending = pending, None
            else:
                flags = 0
                if first:                              # SEQ2A: FAK = 1, UP REC COUNT
                    flags, first = X_FAK, False
                    self.TDA += 1
                    pos.rec += 1
            if len(rest) >= UNBLOCKED:
                if n > 3 and word(b, n) + 1 < n:       # SEQ2H: the segment before is blocked
                    if n + 1 >= WBUFS:
                        pending = flags                # the control word goes on
                        da = self._granule(da)
                        b = self.disc.g[da]
                        continue
                    flags |= X_BKSP                    # SEQ2G: SPECIAL BACKSPACE
                    n += 1
                    setgnav(b, n)
                addr = self.disc.get()                 # SEQ2F
                if not addr:
                    raise FileError(0x0A, "no granule for an unblocked record")
                seg = rest[:GRAN]
                if len(rest) > GRAN:
                    flags, code = flags | X_CONT, 15   # Y28: C & SIZE
                else:
                    code = len(rest) - UNBLOCKED
                self.disc.g[addr][:len(seg)] = seg
                setword(b, n, ((X_UNBLK | flags) << 28) | (code << 24) | addr)
                setword(b, 2, word(b, 2) | G_UNBLK)
                nxt = n + 1
            else:                                      # SEQ3A: blocked
                at = (n + 1) * 4
                seg = rest[:GRAN - at]
                if len(seg) < len(rest):
                    flags |= X_CONT                    # SET C BIT
                b[at:at + len(seg)] = seg
                setword(b, n, word(b, n) + ((flags << 28) | (len(seg) << 16)))   # AWM,4 *14
                nxt = (at + len(seg) + 3) // 4
            rest = rest[len(seg):]
            if nxt >= WBUFS:                           # SEQ3E: FULL FLAG
                setword(b, 2, word(b, 2) | G_FULL)
            else:                                      # SEQ3C
                old = gnav(b)
                setgnav(b, nxt)
                setword(b, nxt, old)                   # FOR BACKUP
            if not rest:
                break
        pos.da = da                                    # SEQ2E: SAVE POSITION
        pos.w = WBUFS if word(b, 2) & G_FULL else gnav(b)

    # -- delete ----------------------------------------------------------------------

    def delete_record(self, pos):
        """DLT.txt SEQ0 (:171) - M:DELREC: the record just read loses its X'4' flag
        (WIPE OUT FAK) and the file one record. Returns False if none was just read."""
        if pos.start is None:
            return False                               # DELER: K15
        da, w = pos.start
        b = self.disc.g[da]
        setword(b, w, word(b, w) & 0xBFFFFFFF)         # NB31TO0+31
        self.TDA -= 1
        pos.da, pos.w, pos.rec, pos.start = da, w, pos.rec - 1, None
        self.written = True
        return True

    def _release_unblocked(self, b, w):
        """SEQ5-SEQ7  DLT.txt:544 - the data granules of unblocked segments from ``w``."""
        if not word(b, 2) & G_UNBLK:
            return
        n = gnav(b)
        while w < WBUFS and w <= n:
            cw = word(b, w)
            if cw & 0x80000000:
                self.disc.release(cw & 0xFFFFFF)
            w += seg_words(cw)

    def delete_forward(self, da, w, rec):
        """DLT.txt SEQ2 (:479) - cut the file at (da, w): release what follows, end
        the granule there (SEQ8A-SEQ83), TDA = the records before, LDA = this granule."""
        b = self.disc.g[da]
        self._release_unblocked(b, w)
        nxt = word(b, 1)
        while nxt:
            nb = self.disc.read(nxt)
            self._release_unblocked(nb, 3)
            after = word(nb, 1)
            self.disc.release(nxt)                     # RELRBGD
            nxt = after
        if w < WBUFS:
            cw = word(b, w)
            if cw & 0x80000000:
                setword(b, w, w - 1)                   # SET BACKSPACE CONTROL WD
            else:
                setword(b, w, cw & 0xFFFF)             # ZAP OUT CTL AND SIZE
            setword(b, 2, (word(b, 2) & 0x8FFF0000) | w)   # Y8FFF
        setword(b, 1, 0)                               # RESET FLINK
        self.TDA, self.LDA = rec, da                   # SEQ92
        self.written = True

    def release(self):
        """DLT.txt SEQ3 (:488), from REL ('NEW CONSECUTIVE') - the whole file: every
        granule, the first too, and the unblocked segments' data granules."""
        da = self.FDA
        while da:
            b = self.disc.read(da)
            self._release_unblocked(b, 3)
            nxt = word(b, 1)
            self.disc.release(da)
            da = nxt
        self.FDA = self.LDA = self.TDA = 0             # SEQ92: NOTHING LEFT

    # -- the FIT ---------------------------------------------------------------------

    @classmethod
    def load(cls, disc, fda, log=None):
        """OPEN of an existing consecutive file: the FIT at word 4 (OPNF.txt:1746)."""
        self = cls.__new__(cls)
        b = disc.read(fda)
        name, vlps = read_fit(b, CFIT, FITSIZE + CFIT)
        if 0x0C not in vlps:
            raise FileError(0x75, "FIT inconsistency")
        c = vlps[0x0C]
        self.disc, self.name, self.log = disc, name, log if log is not None else []
        self.prot = {c: w for c, w in vlps.items() if c in PROTECTION}
        self.FDA, self.TDA, self.LDA = c[0], c[4], c[6]
        self.written = False
        return self

    def _write_fit(self):
        """CLS.txt:2273 ('ASSUME CONSEC'): the name at word 4, organization 1 in the
        X'09' VLP ('MAKE IT EXPLICIT CONSEC', :2392), and the CFU's addresses."""
        put_fit(self.disc.g[self.FDA], CFIT, FITSIZE + CFIT, self.name,
                fit_protection(getattr(self, "prot", {}), CFIT) +
                [(0x09, [1 << 24, 0, 0]),
                 (0x0C, [self.FDA, 0, 0, 0, self.TDA, 0, self.LDA]),
                 (0x0D, [0])])

    def close(self):
        self._write_fit()
        self.written = False

    def records(self):
        """Every record from the beginning (for tests and tools)."""
        pos, out = Position(), []
        while (data := self.read(pos)) is not None:
            out.append(data)
        return out

    # -- FIX1's check ----------------------------------------------------------------

    def check(self):
        """FITCHK and CHKCON  FIX1.txt:1758, :1944 - (granule, word, error number)."""
        errors = check_fit(self.disc, self.FDA, CFIT, FITSIZE + CFIT, self.ORG)
        da, seen = self.FDA, set()
        while da and da not in seen:
            seen.add(da)
            errors += self._chkcon(da, self.disc.read(da))
            da = word(self.disc.g[da], 1)
        return errors

    def _chkcon(self, da, b):
        """CHKCON  FIX1.txt:1944, as read: the previous segment starts as backspace
        control, so an unblocked segment at word 3 needs the X'1' flag (see the open
        question in docs/files.md)."""
        BLOCKED, UNBLK, BKSPC = -1, 0, 1
        prev, kind, w = 0, BKSPC, 3
        n, full = gnav(b), word(b, 2) & G_FULL
        while True:
            cw = word(b, w)
            fl, count, back = flags_of(cw), (cw >> 16) & 0xFFF, cw & 0xFFFF
            if fl & X_UNBLK:                           # CONUBLK
                if kind == BLOCKED or bool(fl & X_BKSP) != (kind == BKSPC):
                    return [(da, w, 42)]
                if (cw & 0xFFFFFF) not in self.disc.g:
                    return [(da, w, 43)]
                kind, prev, step = UNBLK, w, 1
            elif fl == 0 and count == 0:               # CONBKSPC
                if kind != BLOCKED or back != prev:
                    return [(da, w, 44)]
                kind, step = BKSPC, 1
            else:                                      # CHKC15: blocked (or deleted)
                if back != prev:
                    return [(da, w, 41)]
                kind, prev, step = BLOCKED, w, 1 + (count + 3) // 4
            w += step                                  # CHKC20
            if w < n:
                continue
            if w == n:
                if not full:
                    return []
                if w >= WBUFS:
                    return [(da, w, 40)]
                continue
            if not full or prev != n:                  # CHKC30
                return [(da, w, 40)]
            return []


# --- a random file -------------------------------------------------------------------------

class RandomFile:
    """One random file (organization 3, docs/files.md section 6): a run of contiguous
    granules read and written by granule number, and the FIT in a granule of its own
    (SREC). Translated from GRAND.txt, WRTF.txt RWRAND and CLS.txt RELRAND."""

    ORG = 3

    def __init__(self, disc, name, size, log=None):
        """GRANDPUB  GRAND.txt:102 - the FIT's granule (GBG), then the run (GNBG)."""
        self.disc, self.name = disc, name
        self.log = log if log is not None else []
        self.SREC = disc.get()                         # FIT DISK ADDRESS
        if not self.SREC:
            raise FileError(0x57, "no granule for the FIT")
        self.FDA = disc.get_n(size) if size else 0
        if size and not self.FDA:
            disc.release(self.SREC)
            raise FileError(0x57, f"no run of {size} granules")
        self.TDA = size                                # CDAM SET TDA: the size
        b = disc.g[self.SREC]
        setword(b, 2, (MIDIS << 16) | F_FIT | F_FULL)  # the FIT flag OPEN looks for
        self.written = False
        self._write_fit()

    @property
    def fit_da(self):
        return self.SREC                               # what the directory entry names

    def _check(self, gran):
        if not 0 <= gran < self.TDA:
            raise FileError(0x42, f"granule {gran} not in a file of {self.TDA}")   # ERR01

    def read(self, gran, size):
        """RWRAND  WRTF.txt:1928 - up to ``size`` bytes from granule ``gran`` on, no
        further than the end of the file."""
        self._check(gran)
        n = min(size, (self.TDA - gran) * GRAN)
        data = b"".join(bytes(self.disc.read(self.FDA + gran + i))
                        for i in range((n + GRAN - 1) // GRAN))
        return data[:n]

    def write(self, gran, data):
        """RWRAND, write: ``data`` from granule ``gran`` on, cut at the end of the file.
        Returns the bytes written."""
        self._check(gran)
        n = min(len(data), (self.TDA - gran) * GRAN)
        for i in range(0, n, GRAN):
            chunk = data[i:min(i + GRAN, n)]
            self.disc.g[self.FDA + gran + i // GRAN][:len(chunk)] = chunk
        self.written = True
        return n

    def release(self):
        """RELRAND  CLS.txt:1729 - the run back with RNBG; then the FIT's granule (not
        found in RELRAND: assumed released with the file)."""
        if self.TDA:
            self.disc.release_n(self.FDA, self.TDA)
        self.disc.release(self.SREC)
        self.FDA = self.TDA = self.SREC = 0

    @classmethod
    def load(cls, disc, fit, log=None):
        """OPEN of an existing random file: X'0C' word 0 is the run's first address,
        word 1 its size (docs/files.md section 3)."""
        self = cls.__new__(cls)
        name, vlps = read_fit(disc.read(fit), NWFITST, WXBUFSIZ)
        if 0x0C not in vlps:
            raise FileError(0x75, "FIT inconsistency")
        self.disc, self.name, self.log = disc, name, log if log is not None else []
        self.SREC, (self.FDA, self.TDA) = fit, vlps[0x0C][:2]
        self.prot = {c: w for c, w in vlps.items() if c in PROTECTION}
        self.written = False
        return self

    def _write_fit(self):
        put_fit(self.disc.g[self.SREC], NWFITST, WXBUFSIZ, self.name,
                fit_protection(getattr(self, "prot", {}), NWFITST) +
                [(0x09, [3 << 24, 0, 0]),
                 (0x0C, [self.FDA, self.TDA, 0, 0, 0, self.SREC, 0]),
                 (0x0D, [0])])

    def close(self):
        self._write_fit()
        self.written = False

    def check(self):
        """FITCHK  FIX1.txt:1758 for the FIT's granule."""
        if not control(self.disc.g[self.SREC]) & F_FIT:
            return [(self.SREC, 0, 3)]
        return check_fit(self.disc, self.SREC, NWFITST, WXBUFSIZ, self.ORG)


def open_file(disc, fda, log=None):
    """OPNF.txt:1746-:1781 - which organization the first granule is: the FIT flag
    (X'8000') makes it keyed or random, by the X'09' VLP; no flag and X'3FFF0000'
    clear, consecutive."""
    b = disc.g.get(fda)
    if b is None:
        raise FileError(0x75, f"read of an unallocated granule X'{fda:X}'")
    if control(b) & F_FIT:
        _, vlps = read_fit(b, NWFITST, WXBUFSIZ)
        if vlps.get(0x09, [0])[0] >> 24 == RandomFile.ORG:
            return RandomFile.load(disc, fda, log)
        return KeyedFile.load(disc, fda, log)
    if not word(b, 2) & G_NOTCONSEC:
        return ConsecutiveFile.load(disc, fda, log)
    raise FileError(0x75, "FIT inconsistency")


# --- OPEN's checks (docs/files.md section 10) ----------------------------------------------

V_PASSWORD, V_READ, V_WRITE, V_EXECUTE, V_VEHICLE = 0x03, 0x05, 0x06, 0x14, 0x15
PROTECTION = (V_PASSWORD, V_VEHICLE, V_EXECUTE, V_READ, V_WRITE)   # CLOSE's order, CLS.txt:2288
LIST_END = 40                   # CI,SR1 40: a list must end before FIT word 40 (FIL3, 6C2)
WORD_NONE, WORD_ALL = int.from_bytes(as_key("NONE"), "big"), int.from_bytes(as_key("ALL "), "big")


def words_of(b):
    b = bytes(b) + bytes(-len(b) % 4)
    return [int.from_bytes(b[i:i + 4], "big") for i in range(0, len(b), 4)]


def account_words(account):
    return words_of(account_key(account))              # 8 characters: 2 words


def protection(password=None, read=None, write=None, execute=None, vehicle=None):
    """The DCB's protection VLPs, as CLOSE puts them in a new FIT: {code: words}. A
    password is 8 characters (2 words; "" is an empty password); a list holds accounts,
    "ALL" or "NONE"; the vehicle is a processor name (TEXTC)."""
    p = {}
    if password is not None:
        p[V_PASSWORD] = words_of(as_key(password)[:8].ljust(8, as_key(" "))) if password else []
    for code, accounts in ((V_READ, read), (V_WRITE, write), (V_EXECUTE, execute)):
        if accounts is not None:
            p[code] = [w for a in accounts for w in account_words(a)]
    if vehicle:
        name = as_key(vehicle)[:11]
        p[V_VEHICLE] = words_of(bytes([len(name)]) + name)
    return p


def fit_protection(prot, at):
    """The protection VLPs for a FIT whose name starts at word ``at``: in CLOSE's order,
    each account list cut short an entry at a time until it ends before FIT word 40;
    a list with no entry left is dropped (FILIMG2's NO ROOM)."""
    out, w = [], at + 9
    for code in PROTECTION:
        if code not in prot:
            continue
        data = list(prot[code])
        if code in (V_READ, V_WRITE, V_EXECUTE):
            while data and w + 1 + len(data) - at >= LIST_END:
                data = data[:-2]                       # REDUCE BY 1 ENTRY
            if not data:
                continue
        out.append((code, data))
        w += 1 + len(data)
    return out


@dataclass
class Opener:
    """Who is opening: J:JIT's account, JB:PRIV, and the program running (M:XX's
    name and account in MXFPL, for the execute vehicle)."""
    account: str = ":SYS"
    priv: int = 0
    program: tuple = None


def secchk(prot, own, fun, who, password=None):
    """SECCHK  OBSE.txt:310 - may ``who`` open a file with these protection VLPs?
    ``own`` is the DCB's account equal to the user's (USR clear); ``password`` the
    DCB's X'03' words. Returns 'own', 'read', 'special' or None (refused: X'14')."""
    if who.priv >= 0xC0:
        return "own"                                   # MONITOR CAN OPEN ALL FILES
    if V_PASSWORD in prot:
        if not prot[V_PASSWORD]:                       # SECCHK0: empty password
            return "own" if account_key(who.account) == account_key(":SYS") else None
        if password != prot[V_PASSWORD]:
            return None                                # SECCHK05: CLRFIB
    if own:
        return "own"                                   # SECCHK1
    mine = account_words(who.account)

    def search(code):
        """SECCHK2 / SEC1: True for the user's account or ALL, False for NONE or no
        match, None for no list."""
        if code not in prot:
            return None
        ws = prot[code]
        for i in range(0, len(ws) - 1, 2):
            if ws[i] == WORD_NONE:
                return False
            if ws[i] == WORD_ALL or ws[i:i + 2] == mine:
                return True
        return False

    if search(V_WRITE):
        return "own"                                   # SECCHK3 -> SEC3: as its own
    if fun != "IN":
        return None                                    # SECCHK4
    reads = search(V_READ)
    if reads:
        return "read"
    if reads is None and V_EXECUTE not in prot:
        return "read"                                  # SEC0: GIVE ACCESS
    if not search(V_EXECUTE):
        return None                                    # NO ACCESS
    if V_VEHICLE not in prot:
        return None                                    # SEC98: not a fetch
    name, account = who.program or ("", "")
    vehicle = bytes(b for w in prot[V_VEHICLE] for b in w.to_bytes(4, "big"))
    vehicle = vehicle[1:1 + vehicle[0]]
    if account_key(account) != account_key(":SYS") or as_key(name) != vehicle:
        return None                                    # SEC99M1
    return "special"                                   # SEC97: SPECIAL ACCESS


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

    def open(self, name, account, mode="IN", keym=11, lslides=254, lrdl0=2, spare=102,
             org=2, size=0, who=None, password=None, prot=None):
        """OPNF  OPNF.txt - the CFU scan, then the directory search, then the FIT.
        ``mode`` is IN, OUT, INOUT or UPDATE; a missing file is created for OUT or INOUT, not IN or UPDATE (OPNF.txt:165),
        keyed (``org`` 2), consecutive (1) or random (3, of ``size`` granules: RSTORE).
        An existing file keeps its own.

        With ``who`` (an Opener), OPEN's checks apply (docs/files.md section 10): an
        existing file goes through SECCHK with the DCB's ``password`` (X'03' words), and
        only privilege X'C0' creates a file in another account (OP71). Either refusal is
        X'14'. A new file gets ``prot``, the DCB's protection VLPs, in its FIT. The access
        granted is left in ``access``. Without ``who`` (host-side tools), no checks."""
        ident = (account_key(account), as_key(name))
        own = who is None or account_key(account) == account_key(who.account)
        self.access = "own"
        cfu = self.cfus.get(ident)
        if cfu is not None:                            # CFU SCAN: already open
            self._secchk(cfu.file, own, mode, who, password)
            cfu.nou += 1
            return cfu
        fd = self.file_directory(account)
        fit = fd.find(name)
        if fit:
            kf = open_file(self.disc, fit, self.log)
            self._secchk(kf, own, mode, who, password)  # OP3: SECCHK
            if isinstance(kf, KeyedFile):
                kf.LSLIDES, kf.LRDL0, kf.SPARE = lslides, lrdl0, spare
            new = False
        elif mode in ("IN", "UPDATE"):
            raise FileError(0x03, f"no such file {name}")   # OP1: OPENER
        elif not own and who.priv < 0xC0:
            raise FileError(0x14, f"{name}.{account}: not the user's account")   # OP71
        elif org == ConsecutiveFile.ORG:
            kf = ConsecutiveFile(self.disc, name, self.log)                          # ENTERO2
            new = True
        elif org == RandomFile.ORG:
            kf = RandomFile(self.disc, name, size, self.log)                         # GRAND
            new = True
        else:
            kf = KeyedFile(self.disc, name, keym, lslides, lrdl0, spare, self.log)   # ENTER1
            new = True
        if new:
            kf.prot = dict(prot or {})                 # into the FIT at close (CLS.txt:2288)
        cfu = self.cfus[ident] = Cfu(account, name, kf, new=new, fd=fd)
        self.log.append(f"OPEN {name}.{account} {mode}: FIT X'{kf.FDA:X}'"
                        + (" (new)" if new else ""))
        return cfu

    def _secchk(self, f, own, mode, who, password):
        if who is None:
            return
        access = secchk(getattr(f, "prot", {}), own, mode, who, password)
        if access is None:
            raise FileError(0x14, f"{f.name}: no access")   # OPENER03
        self.access = access

    def close(self, cfu, release=False):
        """CLSFIL  CLS.txt:1443 - the pyramid and the FIT; a new file goes into its
        directory (CLSFIL4). With ``release`` (REL) and no other user, the file is
        deleted: its directory entry unless it was never entered (DELF), then its
        granules (REL). The CFU goes when its last user closes."""
        cfu.file.close()
        if release and cfu.nou <= 1:                   # MORE THAN 1 USER: no release
            if not cfu.new:
                cfu.fd.remove(cfu.name)                # CL6A: DELF
            cfu.file.release()                         # CLSFIL2: REL
            cfu.new = False
            self.log.append(f"RELEASE {cfu.name}.{cfu.account}")
        elif cfu.new:
            cfu.fd.add(cfu.name, getattr(cfu.file, "fit_da", cfu.file.FDA))
            cfu.new = False
        cfu.nou -= 1
        if cfu.nou <= 0:
            self.cfus.pop((account_key(cfu.account), as_key(cfu.name)), None)
        self.log.append(f"CLOSE {cfu.name}.{cfu.account}")
