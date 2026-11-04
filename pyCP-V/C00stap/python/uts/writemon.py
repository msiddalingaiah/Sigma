"""SYSGEN WRITEMON: build a BO/PO system tape. Translated from c00co/UTMBPMBT.txt.

See docs/tape.md for the format. WRITEMON reads the linked M:MON; we have no
M:MON, so the modules come from ``Sysgen.modules`` and their contents are zero
words. The root image is zero except for what the boot code itself stores.
"""

from .devices import Tape

NONOVS = ("ALLOCAT", "GHOST1", "FIX")   # UTMBPMBT.txt:747, shared processors
PSTART = "/<#"                          # cards copied without a segment check
FIXED_LINES = 9                         # M1 .. '(ROOT)'
BASE_LINES = 11                         # (ENDINFO-M1)/MSZ
VERSION_OFFSET = 36                     # VERSION-GENINFO, in words
MSZ = 6                                 # words per line


class WriteMonError(Exception):
    """WRITEMON aborted (DEF PROCESSOR ABORTED)."""


def ebcdic_words(text, nwords):
    data = text.ljust(nwords * 4)[:nwords * 4].encode("cp037")
    return [int.from_bytes(data[i:i + 4], "big") for i in range(0, len(data), 4)]


def words_text(words):
    return b"".join(w.to_bytes(4, "big") for w in words).decode("cp037")


def piece_word(pages, bias_page):
    """A head word: halfword 0 = size in dw, halfword 1 = bias in dw."""
    return ((pages * 256) << 16) | ((bias_page * 256) & 0xFFFF)


def head_record(mod, overlay=False):
    w = [0] * 8
    if overlay:
        w[0] = 0x85 << 24                 # head WRITEMON builds for an overlay
    w[1] = mod.start & 0x1FFFF
    w[2] = (mod.tcb >> 1) << 16
    w[3] = piece_word(*mod.data)
    w[4] = piece_word(*mod.proc)
    w[6] = piece_word(*mod.dcbs)
    w[7] = 0                              # symbol-table size (no symbols)
    return w


def ordered_modules(sysgen):
    """Shared processors, overlays in name order, RECOVER last."""
    by_name = {mod.name: mod for mod in sysgen.modules}
    overlays = sorted(sysgen.overlays, key=lambda mod: mod.name)
    return [by_name[n] for n in NONOVS] + overlays + [by_name["RECOVER"]]


def pieces(sysgen):
    """(segment name, module, piece kind) in the order TBOOT: copies them.

    Ghost piece names carry a CSECT digit: 0 data, 2 DCBs, 1 procedure (traced
    from LOOP/RECVEC for GHOST1, UTMBPMBT.txt:183; MIDSEG's comment names GHOST11).
    """
    out = []
    for mod in ordered_modules(sysgen):
        if mod.name in NONOVS:
            for kind, digit in (("data", "0"), ("dcbs", "2"), ("proc", "1")):
                if getattr(mod, kind)[0]:
                    out.append((mod.name + digit, mod, kind))
        else:
            out.append((mod.name, mod, "proc"))
    return out


def segment_of(card, names):
    """Segment number a card names, or None if its first field isn't a known name."""
    field = card.split("/", 1)[0][:8].strip()
    if field in names:
        return names.index(field) + 1
    return None


def place_cards(deck, names):
    """RPATCH (UTMBPMBT.txt:428): which piece each card is written after.

    Returns {segno: [cards]}. A card naming a later segment is written at the
    current position and moves the position on; after '*' everything goes after
    the last segment, followed by the '!' card.
    """
    maxseg = len(names)
    at = {k: [] for k in range(maxseg + 1)}
    cur, ended = 0, False
    for card in deck:
        if ended:
            at[maxseg].append(card)
            continue
        at[cur].append(card)
        first = card[:1]
        if first == "*":
            ended = True
            continue
        if first in PSTART:
            continue
        seg = segment_of(card, names)
        if seg is None:
            continue                       # not a known name: part of this segment
        if seg < cur:
            raise WriteMonError("****  OUT OF ORDER PATCH")
        cur = seg
    if not ended:
        at[cur].append("*")                # ASTBANG at end of file
    if not any(c.startswith("!") for c in at[maxseg]):
        at[maxseg].append("!")
    return at


def creation_record(sysgen, names):
    """GENINFO (UTMBPMBT.txt:776) with the segment names inserted."""
    stars = " " + "*" * 23
    lines = [" " * 24, stars, "         C P - V        ", " SYSTEM GENERATED ON:   ",
             "    " + sysgen.timedate[:16].ljust(16) + "    ",
             " VERSION NO. IS:    " + sysgen.version[:4].ljust(4), stars,
             "  PATCH SEGMENT NAMES:  ", "               (ROOT)   "]
    lines += [" " * 15 + name.ljust(9) for name in names]
    lines += [stars, " " * 24]
    words = [(VERSION_OFFSET << 24) | (BASE_LINES + len(names))]
    for line in lines:
        words += ebcdic_words(line, MSZ)
    words.append(0)                        # HGPINFO
    return words


def writemon(sysgen, deck=(), root=None):
    """UTMBPMWRITEMON  UTMBPMBT.txt:47 - returns a Tape."""
    for mod in sysgen.overlays:
        if mod.name != "UMOV" and mod.proc[0] > 6:
            raise WriteMonError("****  OVERLAY EXCEEDS 6 PAGES")
    if sysgen.DLTBIAS + sysgen.DLTPAGES * 512 + 30 > 0x10000:
        raise WriteMonError("****  XDELTA TOO BIG - REDUCE ITS BIAS")

    tape = Tape()
    nrec = (sysgen.MONIRTN + 1 + 511) // 512
    image = list(root) if root is not None else [0] * (nrec * 512)
    image += [0] * (nrec * 512 - len(image))
    # MTBOOT: the Python stand-in holds the record count (LI,1 n) and the start
    # address (STRTADRT) in words 0 and 1.
    tape.write_record([nrec, 0])
    tape.write_record(image[0x5A:0x5A + 512])          # first record from X'5A'
    for k in range(1, nrec):
        tape.write_record(image[512 * k:512 * (k + 1)])

    plist = pieces(sysgen)
    names = [name for name, _, _ in plist]
    tape.write_record(creation_record(sysgen, names))
    cards = place_cards(list(deck), names)

    xd = sysgen.xdelta
    tape.write_record(head_record(xd))
    for _ in range(xd.proc[0]):
        tape.write_record([])
    for card in cards[0]:
        tape.write_card(card)

    segno = 0
    for mod in ordered_modules(sysgen):
        overlay = mod.name not in NONOVS and mod.name != "RECOVER"
        tape.write_record(head_record(mod, overlay))
        for kind in ("data", "dcbs", "proc"):
            npages = getattr(mod, kind)[0]
            if not npages:
                continue
            for _ in range(npages):
                tape.write_record([])
            segno += 1
            for card in cards[segno]:
                tape.write_card(card)
    return tape
