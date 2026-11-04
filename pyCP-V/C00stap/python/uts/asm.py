"""A small assembler for test programs (docs/interpreter.md section 8): absolute code
at an ORG, in a subset of the Sigma assembly language. Not Meta-Symbol or AP: no
procedures, no relocation, no literals. Real programs come from load modules later.

    label   OP,R    address,X       a memory reference; *address is indirect
    label   OP,R    value           an immediate instruction (LI, AI, CI, MI, LCFI, MBS...)
            CAL1,n  address
            SLS,R   count           shifts: SLS SLD SCS SCD SAS SAD SSS SSD (negative: right)
            DATA    expr,...        words
            TEXT    'chars'         characters, padded with blanks to a word
            TEXTC   'chars'         a count byte, then the characters
            RES     n               n words of zeros
            ORG     expr            a word address
            BOUND   n               to a multiple of n bytes (4 or 8)
    label   EQU     expr
            END     expr            the start address

A label beginning F: or M: names a DCB: it goes in the image's DCB table, which the
loader stand-in puts in the user's J:DCBLINK (docs/dcb.md).

An expression is terms joined by + and -: a decimal number, X'hex', a label, BA(expr)
(a byte address: expr * 4), or *, the current word address. A comment starts with *
in column 1, or follows the operand field after a blank.
"""

import re

from .cpu import OP

SHIFTS = {"SLS": 0, "SLD": 1, "SCS": 2, "SCD": 3, "SAS": 4, "SAD": 5, "SSS": 6, "SSD": 7}
IMMEDIATE = {"LI", "AI", "CI", "MI", "LCFI", "MBS", "CBS", "TBS", "TTBS", "EBS"}


class AsmError(Exception):
    pass


def _fields(line):
    """label, command, operand: blank-separated, with a quoted string kept whole."""
    m = re.match(r"(\S*)\s+(\S+)\s*((?:'[^']*'|[^\s'])*)", line)
    if not m:
        raise AsmError(f"can't read: {line!r}")
    return m.group(1), m.group(2).upper(), m.group(3)


class Assembler:
    def __init__(self, text):
        self.lines = [l.rstrip() for l in text.splitlines()]
        self.sym = {}
        self.dcbs = {}                                 # F:/M: labels: the DCB table

    def value(self, expr, here):
        total, sign, pos = 0, 1, 0
        for tok in re.findall(r"BA\([^)]*\)|X'[0-9A-Fa-f]+'|[+-]|[^+-]+", expr.replace(" ", "")):
            if tok in "+-":
                sign = 1 if tok == "+" else -1
                continue
            if tok.upper().startswith("BA("):
                v = self.value(tok[3:-1], here) * 4
            elif tok.upper().startswith("X'"):
                v = int(tok[2:-1], 16)
            elif tok == "*":
                v = here
            elif tok.isdigit():
                v = int(tok)
            elif tok in self.sym:
                v = self.sym[tok]
            elif self.pass2:
                raise AsmError(f"undefined: {tok}")
            else:
                v = 0
            total += sign * v
            sign = 1
            pos += 1
        return total

    def assemble(self):
        """Returns (words {word address: value}, start)."""
        for self.pass2 in (False, True):
            words, loc, start = {}, 0, None
            for line in self.lines:
                if not line.strip() or line.startswith("*"):
                    continue
                label, cmd, opnd = _fields(line)
                base, _, rfield = cmd.partition(",")
                if label and base != "EQU":
                    self.sym[label] = loc
                    if label[:2] in ("F:", "M:"):
                        self.dcbs[label] = loc
                if base == "EQU":
                    self.sym[label] = self.value(opnd, loc)
                elif base == "ORG":
                    loc = self.value(opnd, loc)
                elif base == "BOUND":
                    n = self.value(opnd, loc) // 4 or 1
                    loc = -(-loc // n) * n
                elif base == "RES":
                    for _ in range(self.value(opnd, loc)):
                        words[loc] = 0
                        loc += 1
                elif base == "END":
                    start = self.value(opnd, loc) if opnd else None
                    break
                elif base == "DATA":
                    for e in opnd.split(","):
                        words[loc] = self.value(e, loc) & 0xFFFFFFFF
                        loc += 1
                elif base in ("TEXT", "TEXTC"):
                    s = opnd.strip()[1:-1]
                    data = (bytes([len(s)]) if base == "TEXTC" else b"") + s.encode("latin-1")
                    data += b" " * (-len(data) % 4)
                    for i in range(0, len(data), 4):
                        words[loc] = int.from_bytes(data[i:i + 4], "big")
                        loc += 1
                else:
                    words[loc] = self.instruction(base, rfield, opnd, loc)
                    loc += 1
        return words, start

    def instruction(self, base, rfield, opnd, loc):
        r = self.value(rfield, loc) & 0xF if rfield else 0
        if base in SHIFTS:
            count = self.value(opnd, loc) & 0x7F
            return (OP["S"] << 24) | (r << 20) | (SHIFTS[base] << 8) | count
        if base not in OP:
            raise AsmError(f"unknown instruction {base}")
        word = (OP[base] << 24) | (r << 20)
        if base in IMMEDIATE:
            return word | (self.value(opnd, loc) & 0xFFFFF)
        ind = opnd.startswith("*")
        addr, _, x = (opnd[1:] if ind else opnd).partition(",")
        word |= self.value(addr, loc) & 0x1FFFF if addr else 0
        if x:
            word |= (self.value(x, loc) & 7) << 17
        return word | (0x80000000 if ind else 0)


def assemble(text, dcbs=None):
    """Assemble ``text``; returns (words {word address: value}, start address). With a
    ``dcbs`` dict, the DCB table (name: address) is put in it too."""
    a = Assembler(text)
    result = a.assemble()
    if dcbs is not None:
        dcbs.update(a.dcbs)
    return result
