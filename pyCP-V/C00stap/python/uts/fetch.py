"""FETCH: a load module into the user's memory (docs/loadmodule.md). Translated from
the step, STPNR.txt: FETCH's checks of HEAD and TREE (:2959-:3101), the root's
sections read to their addresses (FETCH1, :3102-:3123, :3398-:3475), and the start
(XIT34-XIT39, :1443-:1519): J:START, the TCB in register 0, J:DCBLINK.

The memory limits are set (LINKLIMS, OLAYLIM). An overlaid module's root is loaded and
M:SGLD set up; M:SEGLD (cal.py) loads the rest. Not translated: the access codes and
page counts (T:SNAC), page allocation and cleaning, the DCB checker (DCBCHK), core
libraries, debuggers and the runner, paged (X'85') and LINK-built (X'84') modules.
"""

from dataclasses import dataclass, field

from . import jit
from .files import EBCDIC, FileError, KeyedFile
from .monitor import NotTranslated

HEADMASK = 0x78FF0000                    # STPNR.txt:426
HEAD_KEY, TREE_KEY = "HEAD".encode(EBCDIC), "TREE".encode(EBCDIC)
CFU_NAME = "M:*"                         # TXTCFU: the CFU area, not a DCB (CALPROC.txt:166)
DATA, PROC, DCBS = 3, 5, 7               # the section record types (:3104, :3118, :3121)
# Load module error codes, ABC A6-xx (STPNR.txt:432-:441)
BADHEAD, BADBIAS, BADPP, BADDCBLOC = 0x31, 0x32, 0x33, 0x34
SMALLHEAD, SMALLTREE, NOTKEYED, BADTCB = 0x35, 0x36, 0x39, 0x3B


class LoadModuleError(Exception):
    """FETCH3: the user is aborted with A6 (B6 from the DCB checks, ABN2) and this code."""

    def __init__(self, code, why="", abc=0xA6):
        super().__init__(f"{abc:02X}-{code:02X} {why}".rstrip())
        self.code, self.abc = code, abc


@dataclass
class LoadModule:
    name: str
    head: list                            # HEAD's 12 words
    tree: list                            # TREE's words
    words: dict = field(default_factory=dict)    # address -> word, the root's sections
    start: int = 0                        # J:START
    tcb: int = 0                          # J:TCB, a word address (0: none)
    dcblink: int = 0                      # J:DCBLINK
    dcbs: dict = field(default_factory=dict)     # the DCB table: name -> address
    symbols: bytes = b""                  # the root's type-0 record (not read by FETCH)
    limits: dict = field(default_factory=dict)   # JIT word -> page: the memory limits


def linklims(h):
    """XIT101 (STPNR.txt:1352-:1384) and OLAYLIM (:1419-:1430): the memory limits FETCH
    sets from HEAD, as {JIT word: page number}. LINKLIMS (:1622-:1630) takes an area's
    lower limit from the high byte of its bias (the data area: the module's bias, HEAD
    word 2) and its upper from bias + size - 1; an area of size 0 keeps T:RSTLMS's
    empty limits (:1145-:1156). The dynamic data starts above the procedure, else the
    DCBs, else the data, and ends at J:EUP. The access codes and page counts (T:SNAC)
    aren't set."""
    lim = {jit.PLL: jit.JBUPVP, jit.PUL: jit.JBUPVP - 1, jit.DLL: jit.JBUPVP,
           jit.DUL: jit.JBUPVP - 1, jit.DCBLL: jit.JBUPVP, jit.DCBUL: jit.JBUPVP - 1}
    for lower, word, bias in ((jit.DCBLL, h[6], h[6]), (jit.DLL, h[3], h[2]),
                              (jit.PLL, h[4], h[4])):
        size = word >> 16                                      # LH,6 *2
        if size:
            lim[lower] = (bias & 0xFFFF) >> 8                  # LB,7 *2,6
            lim[lower + 1] = (((word & 0xFFFF) + size - 1) >> 8) & 0xFF
    if lim[jit.PUL] >= lim[jit.PLL]:                           # OLAYLIM
        top = lim[jit.PUL]
    elif lim[jit.DCBUL] >= lim[jit.DCBLL]:
        top = lim[jit.DCBUL]
    else:
        top = lim[jit.DUL]
    lim[jit.DDLL], lim[jit.DDUL] = top + 1, jit.JEUPVP         # J:DDUL = J:EUP (XIT9)
    return lim


def pages(lm):
    """The pages FETCH leaves mapped (JX:CMAP): the root's sections (TREE words 6, 8, 10),
    the data from the area's lower limit (the module's bias: library data and blank
    common). An overlay's pages are got when M:SEGLD loads it (SEGLD's MEMSET)."""
    out = set()
    for index, lower in ((6, jit.DLL), (8, None), (10, None)):
        size, bias = lm.tree[index] >> 16, lm.tree[index] & 0xFFFF
        if size:
            first = lm.limits[lower] if lower else bias >> 8
            out.update(range(first, ((bias + size - 1) >> 8) + 1))
    return out


def overlaid(lm):
    """A tree of more than the root's 12 words: M:SEGLD loads the rest (:1482-:1485)."""
    return lm.tree[0] > 12


VLP_WORDS = 10                           # M:XX's VLPs, from word 22 (STPNR.txt:1497-:1499)


def init_sgld(lm, mem, xx):
    """XIT38's M:SGLD (STPNR.txt:1480-:1499): an overlaid module must have the DCB (B6-00
    otherwise, ABN2), and M:XX's 10 VLP words (the load module's name, account and
    password) go to its word 22, where its FLP points. The room check (B6-0C: the DCB
    and 10 words within the DCB area's buffer) isn't made."""
    if not overlaid(lm):
        return
    a = lm.dcbs.get("M:SGLD")
    if not a:
        raise LoadModuleError(0x00, "no M:SGLD for an overlaid module", abc=0xB6)
    for i in range(VLP_WORDS):
        mem[a + 22 + i] = mem.get(xx + 22 + i, 0)


def _words(data):
    return [int.from_bytes(data[i:i + 4].ljust(4, bytes(1)), "big") for i in range(0, len(data), 4)]


def is_load_module(fs, name, account):
    """A keyed file with a HEAD record."""
    try:
        cfu = fs.open(name, account, "IN")
    except FileError:
        return False
    try:
        return isinstance(cfu.file, KeyedFile) and cfu.file.read(HEAD_KEY) is not None
    finally:
        fs.close(cfu)


def read_load_module(fs, name, account):
    """FETCH: open NAME.ACCOUNT, check HEAD and TREE, read the root's sections. Raises
    LoadModuleError for a bad load module (FileError if it can't be opened)."""
    cfu = fs.open(name, account, "IN")
    try:
        kf = cfu.file
        if not isinstance(kf, KeyedFile):
            raise LoadModuleError(NOTKEYED, "not keyed")       # :2994-:2998
        head = kf.read(HEAD_KEY)
        if head is None or len(head) != 0x30:
            raise LoadModuleError(SMALLHEAD, "HEAD isn't 48 bytes")   # :2965-:2968
        h = _words(head)
        if h[0] & HEADMASK:
            raise LoadModuleError(BADHEAD, "HEAD word 0")             # :2970-:2974
        kind = h[0] >> 24
        if kind in (0x84, 0x85):
            raise NotTranslated(f"load module kind X'{kind:02X}' (LINK-built or paged)")
        for word, code in ((h[2], BADBIAS), (h[4], BADPP), (h[6], BADDCBLOC)):
            if word & 0xFF:                                    # :2981-:2992: page boundaries
                raise LoadModuleError(code, "not on a page boundary")
        tree = kf.read(TREE_KEY)
        t = _words(tree or b"")
        if not t or len(tree) < 12 * 4:
            raise LoadModuleError(SMALLTREE, "TREE")                  # :3089-:3091
        lm = LoadModule(name, h, t)                            # overlaid: the root only
        root = bytes(tree[4:16])                               # LMKEY: TBUF+1..3
        seg = root[1:1 + root[0]]
        for kind, index in ((DATA, 6), (PROC, 8), (DCBS, 10)):  # FETCH1
            size, bias = t[index] >> 16, t[index] & 0xFFFF
            if not size:
                continue                                       # LH,6 7 / BEZ BISR2
            data = kf.read(seg + bytes([kind])) or b""
            address = bias * 2                                 # SLS,7 1: a word address
            for i, w in enumerate(_words(data[:size * 8])):    # SLS,6 3: size in bytes
                lm.words[address + i] = w
        lm.symbols = kf.read(seg + bytes([0])) or b""
    finally:
        fs.close(cfu)
    lm.limits = linklims(h)
    lm.start = h[1] & 0x1FFFF                                  # XIT39 :1504-:1506
    lm.tcb = (h[2] >> 16) * 2                                  # :1507-:1509
    if lm.tcb and h[6] >> 16:
        lm.dcblink = lm.words.get(lm.tcb + 10, 0) & 0x1FFFF    # XIT34 :1446-:1450
    if not lm.dcblink and h[6] >> 16:
        lm.dcblink = (h[6] & 0xFFFF) * 2                       # XIT81: J:DCBLL
    lm.dcbs = dcb_table(lm.words, lm.dcblink)
    return lm


def dcb_table(words, dcblink):
    """The DCB name table as CAL11M walks it (CALPROC.txt:164-:190): from DCBLINK + 1,
    entries of the name (a byte count and the name, in words) and the DCB's address;
    a zero word ends it. The CFU area M:* isn't a DCB."""
    out, a = {}, dcblink + 1
    while dcblink and (w := words.get(a, 0)):
        n = w >> 24
        nwords = (n + 4) // 4
        text = b"".join(words.get(a + i, 0).to_bytes(4, "big") for i in range(nwords))
        name = text[1:1 + n].decode(EBCDIC)
        address = words.get(a + nwords, 0) & 0x1FFFF
        if name != CFU_NAME:
            out[name] = address
        a += nwords + 1
    return out

# --- writing one: what the overlay loader would leave, for one segment ----------------

PAGE = 512                               # words
TCB_WORDS = 16                           # the TCB: only word 10 (DCBLINK) is set here
LM_KEYM = 15                             # the load modules' key length (their 16-byte key area)


def write_load_module(fs, name, account, words, start, dcbs=None):
    """Words assembled at their addresses as a one-segment load module NAME.ACCOUNT
    that FETCH can read (docs/loadmodule.md, "Writing one"): the data section from the
    page the words start in, a TCB after them, and the DCB table on the next page.
    Not a translation of the overlay loader: a stand-in for its output. Any old
    contents of the file are replaced."""
    lo = min(words) // PAGE * PAGE
    tcb = (max(words) + 2) & ~1                          # doubleword aligned, after the words
    data_end = tcb + TCB_WORDS
    table_at = (data_end + PAGE - 1) // PAGE * PAGE      # the DCB area: its own page
    table = []
    for dcb_name, address in (dcbs or {}).items():
        text = dcb_name.encode(EBCDIC)[:7]
        entry = (bytes([len(text)]) + text).ljust((len(text) + 4) // 4 * 4, b"\x40")
        table += [int.from_bytes(entry[i:i + 4], "big") for i in range(0, len(entry), 4)]
        table.append(address & 0x1FFFF)
    table = [table_at + 1 + len(table)] + table + [0]    # word 0: the zero word that ends it
    image = dict(words)
    for i in range(TCB_WORDS):
        image[tcb + i] = table_at if i == 10 and dcbs else 0
    data_dw = (data_end - lo + 1) // 2
    dcb_dw = (len(table) + 1) // 2 if dcbs else 0
    area = lambda dw, bias: ((dw + 255) // 256 * 256) << 16 | bias   # HEAD: whole pages
    head = [0x8000FF30, 0x80000000 | (start & 0x1FFFF),
            (tcb // 2) << 16 | lo // 2,                  # TCB; the module's bias
            area(data_dw, lo // 2), 0, 0,                 # data; no procedure
            area(dcb_dw, table_at // 2) if dcbs else 0,   # DCBs
            0, 0, 0, 0, 0]                                # (not read by FETCH)
    seg = name.encode(EBCDIC)[:7]
    seg_text = (bytes([len(seg)]) + seg).ljust(12, b"\x40")
    tree = [12] + [int.from_bytes(seg_text[i:i + 4], "big") for i in range(0, 12, 4)]
    tree += [0, 0, data_dw << 16 | lo // 2, 0, 0, 0,
             (dcb_dw << 16 | table_at // 2) if dcbs else 0, 0]
    as_bytes = lambda ws: b"".join((w & 0xFFFFFFFF).to_bytes(4, "big") for w in ws)
    records = {HEAD_KEY: as_bytes(head), TREE_KEY: as_bytes(tree),
               seg + bytes([DATA]): as_bytes(image.get(lo + i, 0) for i in range(data_dw * 2))}
    if dcbs:
        records[seg + bytes([DCBS])] = as_bytes(table + [0] * (dcb_dw * 2 - len(table)))
    fs.add_account(account)
    cfu = fs.open(name, account, "OUT", keym=LM_KEYM)
    for k in cfu.file.keys():
        cfu.file.delete(k)
    for key in sorted(records):
        cfu.file.write(key, records[key])
    fs.close(cfu)
