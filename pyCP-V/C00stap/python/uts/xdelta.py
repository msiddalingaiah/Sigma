"""XDELTA's boot-time patcher, PACHSTRT (c00co/XDLT.txt:3238).

Translated: the card protocol, i.e. reading from tape or cards, the ':', '#', '*',
'<' dispatch, segment ordering with one card of look-ahead, and copying the rest
of the deck at the last segment. See docs/tape.md section 2.3.

Not translated: XDELTA's expression evaluator (DRINITB/DREVALIT). Segment fields
are resolved only when they are a plain patch segment name; a card that would
need evaluating stops the boot with NotTranslated.
"""

from .machine import BOOTFLG, FLAG_C, FLAG_P, FLAG_T
from .monitor import NotTranslated
from . import reconfig

INFINITE = 1 << 30   # EXITP0: the segment becomes "infinite"


class BootPatcher:
    def __init__(self, m, mon, names):
        self.m, self.mon = m, mon
        self.names = names          # patch segment names; index + 1 = segment number
        self.held = None            # (segno, card) read ahead for a later segment
        self.done = False           # past the last segment (EXIT1)
        flags = m.mem.get_byte(BOOTFLG)
        tape, cards = flags & FLAG_T, flags & FLAG_C
        if tape and cards:
            raise NotTranslated("XDELTA: merging tape and card patches (EXITP)")
        self.read = (m.tape.read_card if tape else
                     m.card_reader.read_card if cards else None)  # READCARD: none -> no cards

    def segment(self, card):
        field = card.split("/", 1)[0].strip()
        if field == "":
            return 0                                  # root
        if field in self.names:
            return self.names.index(field) + 1
        raise NotTranslated(f"XDELTA: evaluating the segment expression '{field}'")

    def segpatch(self, segno, base=None, size=None):
        """PACHSTRT: apply the patches for ``segno`` (``base``/``size`` = SEGBASE/SEGMAX, words)."""
        if self.done:
            return
        if self.read is not None:
            while True:
                if self.held is None:
                    card = self.read()
                    first = card[:1]
                    if first == ":":
                        reconfig.recnfg(self.m, self.mon, card)
                        continue
                    if first == "#":
                        raise NotTranslated(f"XDELTA: symbol definition card '{card.strip()}'")
                    if first == "<":
                        self.list(card)               # COMMENT
                        continue
                    if first == "*":
                        self.held = (INFINITE, card)  # EXITP0
                    else:
                        self.held = (self.segment(card), card)
                seg, card = self.held
                if seg < segno:
                    raise NotTranslated(f"XDELTA: DRERR for out-of-order patch '{card.strip()}'")
                if seg > segno:
                    break                             # EXITP: keep it for later
                self.held = None
                self.apply(segno, card, base, size)
        if segno == self.mon.MAXSEG:
            self.exit1()

    def apply(self, segno, card, base, size):
        """ANALSTOR: evaluate location and value and store them."""
        self.list(card)
        raise NotTranslated(f"XDELTA: storing patch for segment {segno}: '{card.strip()}'")

    def list(self, card):
        self.mon.patch_cards.append((self.mon.SEGNO, card))
        if self.m.mem.get_byte(BOOTFLG) & FLAG_P:
            self.m.printer.print(card.rstrip())

    def exit1(self):
        """EXIT1  XDLT.txt:3533 - copy the rest of the deck, up to '!', to the patch file."""
        self.done = True
        if self.read is None:
            return
        held = self.held[1] if self.held else None
        while not (held or "").startswith("!"):
            held = self.read()
        self.m.trace(f"XDELTA: patching done, {len(self.mon.patch_cards)} cards listed")
