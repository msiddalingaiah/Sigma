"""COC: the terminal lines (docs/coc.md). Translated from c00co/COC.txt: the input
interrupt (COCIP), the immediate characters, BREAK, echo (COCECHO), reads (COCIO,
COCRD, COCMU), writes (COCWR) and lines coming and going (T:COCHC, COCMINT, COCOFF).

A line's buffers are a Python list for the line being typed and a list of completed
lines, in place of the 16-byte buffer chains. Characters stay ASCII (Latin-1), the
translation's convention for text in memory. Not translated: tab stops, escape
sequences (consumed), vertical format control, output pacing, time-outs, lost data,
parity, paper tape and the 2741.
"""

from .sched import E_CBK, E_CEC, E_CIC, E_OFF

BS, CAN, EM, ESC, CR, LF, DEL = 0x08, 0x18, 0x19, 0x1B, 0x0D, 0x0A, 0x7F
CRLF = b"\r\n"
# TTYOUT  COC.txt:4655 - the output table's first four rows, EBCDIC X'00'-X'3F': an
# ASCII control, or (X'80' up) a COC function. X'82' is *CR and *NL (X'0D', X'15'): a
# new line. The rest of the table is EBCDIC's graphics, which code page 037 gives.
TTYOUT_CONTROLS = bytes.fromhex(
    "00010203EA810607" "8B05150B80820E0F" "1011121314821617" "18E58E1BE1E2E3E4"
    "8D1C1D1E1F192F5E" "3D0D040829090A23" "848685D6D2C3CBD3" "D5D7D78CCEC68788")
NEW_LINE = 0x82


def ttyout(data):
    """A record's bytes as the terminal gets them (TTYOUT): graphics through code page
    037, a new line for *CR and *NL (as EBCDIC NL, U+0085, which write() expands), an
    ASCII control as itself. COC's other functions (tabs, ESC sequences, *FF, *LF) and
    TTYOUT's '+' controls aren't translated: dropped."""
    out = []
    for c in data:
        if c >= 0x40:
            out.append(bytes([c]).decode("cp037"))
            continue
        t = TTYOUT_CONTROLS[c]
        if t == NEW_LINE:
            out.append("\x85")
        elif t < 0x80:
            out.append(chr(t))
    return "".join(out)


class Line:
    """One line's tables (docs/coc.md section 1)."""

    def __init__(self, number):
        self.number = number
        self.send = None                               # where the line's output goes
        self.reset()

    def reset(self):
        """COCMINT  COC.txt:4182-4422: the mode bits before a new user logs on."""
        self.typed = []                                # the line being typed (COCII)
        self.done = []                                 # completed lines, not yet read
        self.reading = False                           # MODE: a read is pending
        self.echoed = 0                                # how much of ``typed`` was echoed
        self.esc = False                               # MODE: an escape is pending
        self.after_cr = False                          # an LF after CR is the same NL
        self.col = 0                                   # CPOS: the carriage position
        self.output = []                               # what was sent (for tests)


class Coc:
    """The lines, for one scheduler. ``s.LB_UN`` ties a line to its user."""

    def __init__(self, sched, lines=None):
        self.s = sched
        self.lines = [Line(i) for i in range(lines or len(sched.LB_UN))]
        sched.coc = self

    def user(self, n):
        u = self.s.LB_UN[n]
        return u if u not in (0, 0xFF) else 0

    def line_of(self, u):
        for n in range(len(self.lines)):
            if self.s.LB_UN[n] == u:
                return n
        return None

    def _out(self, line, data):
        if isinstance(data, str):
            data = data.encode("latin-1", errors="replace")
        for c in data:                                 # CPOS
            line.col = 0 if c in (CR, LF) else max(line.col - 1, 0) if c == BS else line.col + 1
        line.output.append(data)
        if line.send is not None:
            line.send(data)

    # -- lines coming and going (T:COCHC, COCOFF) -----------------------------------------

    def ready(self, n, send=None):
        """A line comes ready with no user (T:COCHC): COCMINT, then log-on, as for a
        BREAK: E:CBK through T:RCE, which on an empty line is the scheduler's LOGON."""
        line = self.lines[n]
        line.send = send
        line.reset()
        self.s.t_rce(n, E_CBK)
        return self.user(n)

    def drop(self, n):
        """The line drops: E:OFF for its user (T:RCE sets HANGUP), and COCOFF."""
        line = self.lines[n]
        if self.user(n):
            self.s.t_rce(n, E_OFF)
            self.s.hangups.add(self.user(n))
        line.send = None
        line.reset()

    # -- input (COCIP) ------------------------------------------------------------------

    def brk(self, n):
        """COCIPBRK  :857 - a BREAK. On a line with no user: COCMINT and log-on. With a
        user: the input is released and E:CBK reported; with TEL in control, TEL gets
        the terminal back (online.py)."""
        line = self.lines[n]
        u = self.user(n)
        if not u:
            return self.ready(n, line.send)
        line.typed, line.done, line.echoed = [], [], 0
        line.reading = False
        self.s.t_rce(n, E_CBK)
        self.s.breaks.add(u)

    def input(self, n, c):
        """One character from the line: COCIP's immediate characters, buffering and echo."""
        line = self.lines[n]
        u = self.user(n)
        if not u:
            return                                     # NO USER, DON'T BUFFER CHARS (:524)
        c &= 0x7F                                      # SCRUB PARITY (:644)
        if line.esc:                                   # COCIP5F: an escape sequence's
            line.esc = False                           # character (TTESCS): not followed
            return
        if c == LF and line.after_cr:
            line.after_cr = False                      # CR LF: one new line
            return
        line.after_cr = False
        if c == ESC:                                   # COCIESC  :788
            line.esc = True
        elif c == EM:                                  # COCIYC  :719: Ctrl-Y
            line.typed, line.echoed = [], 0
            self.s.t_rce(n, E_CEC)
            self.s.breaks.add(u)
        elif c == CAN:                                 # COCIXC  :795: Ctrl-X
            line.typed, line.echoed = [], 0
            if line.reading:
                self._out(line, "_" + "\r\n")          # ESCX2: BACK ARROW, CR/LF
        elif c in (BS, DEL):                           # backspace, rubout: edit
            if line.typed:
                line.typed.pop()
                if line.reading and line.echoed > len(line.typed):
                    line.echoed = len(line.typed)
                    self._out(line, b"\b \b")
        elif c in (CR, LF):                            # *CR, *NL: activation
            line.after_cr = c == CR
            text = bytes(line.typed).decode("latin-1")
            line.typed, line.echoed = [], 0
            line.done.append(text)
            if line.reading:
                self._out(line, CRLF)
                self.s.t_rce(n, E_CIC)                 # INPUT COMPLETE  (:582-:590)
        elif c >= 0x20:
            line.typed.append(c)
            if line.reading:                           # ECHO ... IF A READ IS PENDING
                self._out(line, bytes([c]))
                line.echoed = len(line.typed)

    # -- reads and writes (COCIO) -----------------------------------------------------------

    def read(self, n, prompt=""):
        """COCRD  :2272 - the next line, or None: then the caller waits (E:CRD) for
        E:CIC. At the start of a read, the prompt and the typed-ahead characters are
        echoed."""
        line = self.lines[n]
        if not line.reading:
            line.reading = True
            if prompt:                                 # SEND PROMPT IF REQUIRED
                self._out(line, (CRLF if line.col else b"") + prompt.encode("latin-1"))
            if line.done:                              # ECHO ALL CHARACTERS READ AHEAD
                self._out(line, line.done[0].encode("latin-1") + CRLF)
            elif line.typed:
                self._out(line, bytes(line.typed))
                line.echoed = len(line.typed)
        if not line.done:
            return None
        line.reading = False
        return line.done.pop(0)

    def write(self, n, text, before=0, after=False):
        """COCWR  :2851 - a record: ``before`` new lines first (a format control under
        VFC, COCWR36; otherwise the DCB's spacing less 1, COCWR38: none), the record,
        then a new line only if ``after`` (COCWR80: not on M:UC, and the record doesn't
        end in a new-line character). An EBCDIC NL (X'15', which code page 037 makes
        U+0085) in the record is a new line, as TTYOUT's *NL. The carriage stays where
        the record leaves it, so a read that follows takes its input on the same line
        (LOGON PLEASE:)."""
        line = self.lines[n]
        text = text.replace("\x85", "\r\n")
        self._out(line, CRLF * before + text.encode("latin-1", errors="replace")
                  + (CRLF if after else b""))

    def finish(self, n):
        """Before the line is closed: the carriage back to the margin."""
        line = self.lines[n]
        if line.col:
            self._out(line, CRLF)
