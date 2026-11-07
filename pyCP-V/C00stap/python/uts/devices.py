"""Stub peripherals: operator console, line printer, card reader, tape, swap disc.

Each stub models just enough for the boot code: the console returns scripted
replies (an empty reply stands for the 10-second MESSG timeout), the tape is a
list of records, and the disc is a sparse array of 256-word sectors.
"""

from collections import deque

SECTOR_WORDS = 256  # RAD sector; a granule is 2 sectors (one page)
RECORD_WORDS = 512  # a 2048-byte tape record


class ConsoleExhausted(Exception):
    """The script ran out of replies while the boot code was still asking."""


class DeviceError(Exception):
    """An I/O condition the boot code would wait on forever (no operator to fix it)."""


class Console:
    """Operator console (OC). ``replies`` is a script; ``interactive`` reads stdin."""

    KEYIN_PROMPT = "\n!"                    # KEYIN's TP25: NL, '!'

    def __init__(self, replies=(), interactive=False, echo=False):
        self.replies = deque(replies)
        self.interactive = interactive
        self.echo = echo
        self.transcript = []
        self.eof = False
        # live: key-ins typed on the host while the system runs (--terminals with -i
        # --console). The operator types after a '!' the console shows when it is ready,
        # so KEYIN's own prompt and the echo of the line are left out on the host.
        self.live = False
        self.prompt_shown = False
        self.at_line_start = True
        self.just_typed = False

    def show_prompt(self):
        """Live: '!' when the console is ready for a key-in, on a line of its own."""
        if self.live and not self.prompt_shown:
            print(("" if self.at_line_start else "\n") + "!", end="", flush=True)
            self.prompt_shown, self.at_line_start = True, False

    def typed(self):
        """Live: the operator ended a line with Enter (the host has echoed it)."""
        self.prompt_shown, self.at_line_start, self.just_typed = False, True, True

    def write(self, text):
        # The source uses X'15' (EBCDIC NL) inside messages; we use '\n'.
        self.transcript.append(text)
        if not (self.echo or self.interactive):
            return
        if self.live:
            if text == self.KEYIN_PROMPT:
                return                              # the operator typed after our '!'
            if self.just_typed and text.startswith("\n"):
                text = text[1:]                     # the host's Enter was that new line
            if text:
                self.just_typed = False
            if self.prompt_shown and not text.startswith("\n"):
                text = "\n" + text                  # output while '!' waits: a new line
            self.prompt_shown = False
            if text:
                self.at_line_start = text.endswith("\n")
        print(text, end="", flush=True)

    def read(self):
        """Read one reply. '' means no input before the timeout."""
        if self.replies:
            reply = self.replies.popleft()
            if self.interactive:
                print(reply)                       # a scripted answer, shown as if typed
        elif self.interactive:
            try:
                reply = input()
            except EOFError:
                reply = ""
                self.eof = True
        else:
            raise ConsoleExhausted("console script has no more replies")
        if not self.interactive:
            self.transcript.append(reply + "\n")
            if self.echo and not self.live:             # live: the host showed it as typed
                print(reply)
        return reply

    def at_end(self):
        """No more input: the script is used up, or stdin reached end of file."""
        return self.eof if self.interactive else not self.replies

    def text(self):
        return "".join(self.transcript)


class LinePrinter:
    def __init__(self):
        self.lines = []

    def print(self, text):
        self.lines.append(text)


class CardReader:
    def __init__(self, cards=()):
        self.cards = deque(cards)

    def read_card(self):
        if not self.cards:
            raise DeviceError("card reader empty")
        return self.cards.popleft()


class Card(str):
    """An 80-byte tape record holding one patch card."""


class Tape:
    """Magnetic tape: a list of records, each a 512-word list or a Card."""

    def __init__(self, records=()):
        self.records = list(records)
        self.pos = 0

    def write_record(self, words):
        words = list(words)[:RECORD_WORDS]
        self.records.append(words + [0] * (RECORD_WORDS - len(words)))

    def write_card(self, text):
        self.records.append(Card(text[:80]))

    def _next(self):
        if self.pos >= len(self.records):
            raise DeviceError("tape: read past the last record")
        rec = self.records[self.pos]
        self.pos += 1
        return rec

    def read_record(self):
        """A 2048-byte read. An 80-byte record ends with incorrect length, which
        ERROREC's TPREC (BOOTSUBR.txt:944) retries, so cards are skipped."""
        rec = self._next()
        while isinstance(rec, Card):
            rec = self._next()
        return rec

    def read_card(self):
        """XDELTA's card read (72 bytes, incorrect length suppressed)."""
        rec = self._next()
        if not isinstance(rec, Card):
            raise DeviceError("tape: expected a patch card, found a 2048-byte record")
        return str(rec)


class Disc:
    """Swap disc (RAD) as a sparse sector store. Disc addresses are sector numbers.

    ``model`` is the controller model byte the sense command returns (X'80' 7212,
    X'56' 7232). ``attached`` holds, per sector, root variables that the Python
    keeps on ``Monitor`` instead of in memory; they ride along with the root image
    WRTROOT writes, so that a disc boot can read them back.
    """

    def __init__(self, write_protected=False, model=0x80):
        self.sectors = {}
        self.write_protected = write_protected
        self.model = model
        self.attached = {}
        self.reads = []  # (sector, nwords) for tracing

    def read_words(self, sector, nwords):
        self.reads.append((sector, nwords))
        out = []
        while len(out) < nwords:
            data = self.sectors.get(sector, [0] * SECTOR_WORDS)
            out.extend(data[: nwords - len(out)])
            sector += 1
        return out

    def write_words(self, sector, words):
        if self.write_protected:
            raise DeviceError("SWAPPER WRITE PROTECTED")
        for i in range(0, len(words), SECTOR_WORDS):
            chunk = list(words[i:i + SECTOR_WORDS])
            chunk += [0] * (SECTOR_WORDS - len(chunk))
            self.sectors[sector] = chunk
            sector += 1
