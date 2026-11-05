"""A card reader and a card punch whose media are host files (docs/devopen.md, "Card
devices"). NOT a translation: the reader and punch handlers (HANDLERS.txt) aren't
translated; these stand in for the devices under OPEN, as simh attaches a deck file.

A text file loaded into the reader is a deck: each line is a card, 80 columns in
EBCDIC, blank-filled. Cards punched go to a text file, a line each, trailing blanks
dropped.
"""

from .files import EBCDIC

COLUMNS = 80


def card(line):
    """A line of text as an 80-column EBCDIC card."""
    return line.rstrip("\r\n")[:COLUMNS].ljust(COLUMNS).encode(EBCDIC, errors="replace")


class CardReader:
    def __init__(self, cards=(), path=None):
        self.cards = list(cards)
        self.path = path
        self.read = 0                                  # cards read so far

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls([card(line) for line in f], path)

    def next(self):
        """The next card, or None: the hopper is empty."""
        if self.read >= len(self.cards):
            return None
        self.read += 1
        return self.cards[self.read - 1]


class CardPunch:
    def __init__(self, path=None):
        self.cards = []
        self.path = path

    def punch(self, data):
        self.cards.append(bytes(data[:COLUMNS]).ljust(COLUMNS, b"\x40"))
        if self.path is not None:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(self.text(self.cards[-1]) + "\n")

    @staticmethod
    def text(c):
        return c.decode(EBCDIC).rstrip()


class UnitRecord:
    """The card devices of a system: their media and which user holds each."""

    def __init__(self, reader=None, punch=None):
        self.media = {"CR": reader, "CP": punch}
        self.holder = {}                               # device -> user number

    def allocate(self, device, u):
        """OPENDEV's allocation, for a device with a medium: one user at a time."""
        if self.media.get(device) is None or self.holder.get(device, u) != u:
            return False
        self.holder[device] = u
        return True

    def release(self, u, device=None):
        for d in [d for d, h in self.holder.items() if h == u and device in (None, d)]:
            del self.holder[d]
