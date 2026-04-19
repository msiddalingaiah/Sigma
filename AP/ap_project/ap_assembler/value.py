"""
ap_assembler/value.py — Value representation for the AP assembler.

Every symbol, expression result, and constant in AP has a "Value".  This
module defines the Value type hierarchy and the arithmetic rules that govern
how values combine.

The original AP assembler packed value information into 1–3 32-bit words
with elaborate bit-fields.  Here we use Python dataclasses that carry the
same semantic content in a readable form.

Value kinds (mirroring the ET field of the original Expression Value Table):
  UNDEFINED    symbol referenced before definition
  ABSOLUTE     pure integer constant (no control section)
  RELOCATABLE  csect-relative address = csect_num + byte_offset
  EXTERNAL     external reference / definition (loader resolves it)
  COMPLEX_SUM  sum of relocatables from different csects (rare)
  PKDEC        packed-decimal constant  D'...'
  CHARSTR      character-string constant  C'...' / '...'
  FX           fixed-point decimal constant  FX'...'
  FS           floating-point short constant  FS'...'
  FL           floating-point long constant  FL'...'
  BLANK        explicitly absent (blank) argument position

Resolution values (byte width of one "unit"):
  BYTE = 0  →  1 byte   (BA addressing)
  HW   = 1  →  2 bytes  (HA addressing)
  WORD = 2  →  4 bytes  (WA addressing, the default)
  DW   = 3  →  8 bytes  (DA addressing)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ValueKind(Enum):
    UNDEFINED    = auto()   # symbol used but not yet defined
    ABSOLUTE     = auto()   # pure integer (not relocatable)
    RELOCATABLE  = auto()   # csect-relative address
    EXTERNAL     = auto()   # external symbol (DEF/REF)
    COMPLEX_SUM  = auto()   # sum involving multiple control sections
    PKDEC        = auto()   # D'...'   packed decimal constant
    CHARSTR      = auto()   # C'...'   character string constant
    FX           = auto()   # FX'...'  fixed-point decimal
    FS           = auto()   # FS'...'  floating-point short
    FL           = auto()   # FL'...'  floating-point long
    BLANK        = auto()   # blank / absent argument
    LIST         = auto()   # ordered sequence of Values


class Resolution(Enum):
    """Intrinsic resolution — determines how an offset scales to bytes."""
    BYTE = 0       # 1 byte  per unit
    HW   = 1       # 2 bytes per unit
    WORD = 2       # 4 bytes per unit  (default for most symbols)
    DW   = 3       # 8 bytes per unit

    @property
    def bytes_per_unit(self) -> int:
        return 1 << self.value   # 1, 2, 4, or 8

    def to_byte_offset(self, units: int) -> int:
        """Convert an offset in this resolution to bytes."""
        return units * self.bytes_per_unit

    def from_byte_offset(self, byte_offset: int) -> int:
        """Convert a byte offset to units of this resolution (truncates)."""
        return byte_offset >> self.value


# ---------------------------------------------------------------------------
# Addend — one component of a COMPLEX_SUM value
# ---------------------------------------------------------------------------

@dataclass
class Addend:
    """
    One term in a complex address expression.

    sign    :  +1 for addition, -1 for subtraction
    csect   :  control section number  (0 = absolute)
    offset  :  byte offset within the control section
    """
    sign:   int    # +1 or -1
    csect:  int    # 0 = absolute / constant contribution
    offset: int    # byte value


# ---------------------------------------------------------------------------
# Value — the core type
# ---------------------------------------------------------------------------

MASK32 = 0xFFFF_FFFF   # 32-bit mask


@dataclass
class Value:
    """
    Represents the value of a symbol or expression in the AP assembler.

    For ABSOLUTE:       int_val holds the integer value.
    For RELOCATABLE:    int_val is the byte offset, csect is the section.
    For EXTERNAL:       name holds the external symbol name.
    For COMPLEX_SUM:    addends is a list of Addend objects.
    For PKDEC/CHARSTR/FX/FS/FL: raw holds the original string content.
    For UNDEFINED/BLANK: all numeric fields are 0.
    """
    kind:        ValueKind           = ValueKind.UNDEFINED
    int_val:     int                 = 0         # ABSOLUTE value or RELOCATABLE byte offset
    csect:       int                 = 0         # control section number (RELOCATABLE)
    resolution:  Resolution          = Resolution.WORD
    raw:         object              = None      # constant body (str for PKDEC/CHARSTR/etc.)
    addends:     List[Addend]        = field(default_factory=list)
    items:       list                = field(default_factory=list)  # LIST elements
    name:        str                 = ''        # EXTERNAL symbol name
    is_defined:  bool                = True      # False for UNDEFINED

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def absolute(cls, n: int, resolution: Resolution = Resolution.WORD) -> 'Value':
        """Create an absolute (non-relocatable) integer value."""
        return cls(kind=ValueKind.ABSOLUTE,
                   int_val=_s32(n),
                   resolution=resolution)

    @classmethod
    def relocatable(cls, csect: int, byte_offset: int,
                    resolution: Resolution = Resolution.WORD) -> 'Value':
        """Create a relocatable address value."""
        return cls(kind=ValueKind.RELOCATABLE,
                   int_val=byte_offset,
                   csect=csect,
                   resolution=resolution)

    @classmethod
    def undefined(cls, resolution: Resolution = Resolution.WORD) -> 'Value':
        """Create an undefined-symbol placeholder."""
        return cls(kind=ValueKind.UNDEFINED, is_defined=False, resolution=resolution)

    @classmethod
    def blank(cls) -> 'Value':
        return cls(kind=ValueKind.BLANK)

    @classmethod
    def list_val(cls, items: list) -> 'Value':
        """Create a list value from a sequence of Values."""
        return cls(kind=ValueKind.LIST, items=list(items))

    @classmethod
    def external(cls, name: str, resolution: Resolution = Resolution.WORD) -> 'Value':
        """Create an external-reference value."""
        return cls(kind=ValueKind.EXTERNAL, name=name, resolution=resolution)

    @classmethod
    def pkdec(cls, signed_digits: str) -> 'Value':
        return cls(kind=ValueKind.PKDEC, raw=signed_digits)

    @classmethod
    def charstr(cls, text: str) -> 'Value':
        return cls(kind=ValueKind.CHARSTR, raw=text)

    @classmethod
    def fx(cls, body: str) -> 'Value':
        return cls(kind=ValueKind.FX, raw=body)

    @classmethod
    def fs(cls, body: str) -> 'Value':
        return cls(kind=ValueKind.FS, raw=body)

    @classmethod
    def fl(cls, body: str) -> 'Value':
        return cls(kind=ValueKind.FL, raw=body)

    # ------------------------------------------------------------------
    # Predicates
    # ------------------------------------------------------------------

    def is_integer(self) -> bool:
        return self.kind == ValueKind.ABSOLUTE

    def is_address(self) -> bool:
        return self.kind in (ValueKind.RELOCATABLE, ValueKind.COMPLEX_SUM)

    def is_list(self) -> bool:
        return self.kind == ValueKind.LIST

    def is_constant(self) -> bool:
        return self.kind in (ValueKind.PKDEC, ValueKind.CHARSTR,
                              ValueKind.FX, ValueKind.FS, ValueKind.FL)

    def is_scalar(self) -> bool:
        """True if the value can be used in arithmetic as a single number."""
        return self.kind in (ValueKind.ABSOLUTE, ValueKind.RELOCATABLE)

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    def to_byte_offset(self) -> int:
        """Return the value in bytes regardless of its intrinsic resolution."""
        if self.kind in (ValueKind.ABSOLUTE, ValueKind.RELOCATABLE):
            return self.int_val
        return 0

    def apply_resolution(self, res: Resolution) -> 'Value':
        """
        Return a copy of this value converted to the given resolution.
        Used by addressing functions BA(), HA(), WA(), DA().
        """
        if self.kind not in (ValueKind.ABSOLUTE, ValueKind.RELOCATABLE,
                              ValueKind.COMPLEX_SUM):
            return self
        new = Value(kind=self.kind, int_val=self.int_val, csect=self.csect,
                    resolution=res, addends=list(self.addends))
        return new

    def __repr__(self) -> str:
        if self.kind == ValueKind.ABSOLUTE:
            return f"Value.absolute({self.int_val:#x})"
        if self.kind == ValueKind.RELOCATABLE:
            return (f"Value.relocatable(csect={self.csect}, "
                    f"offset={self.int_val:#x})")
        if self.kind == ValueKind.UNDEFINED:
            return "Value.undefined()"
        if self.kind == ValueKind.BLANK:
            return "Value.blank()"
        return f"Value({self.kind.name}, {self.raw or self.int_val!r})"


# ---------------------------------------------------------------------------
# 32-bit integer helpers
# ---------------------------------------------------------------------------

def _u32(n: int) -> int:
    """Mask to unsigned 32-bit."""
    return n & MASK32


def _s32(n: int) -> int:
    """Mask to signed 32-bit (two's complement)."""
    n &= MASK32
    if n >= 0x8000_0000:
        n -= 0x1_0000_0000
    return n


# ---------------------------------------------------------------------------
# Arithmetic on Values
# ---------------------------------------------------------------------------

class AssemblerError(Exception):
    """Raised when an expression cannot be evaluated."""


def _add_values(a: Value, b: Value, sign: int = +1) -> Value:
    """
    Compute  a + sign*b  according to AP addressing rules.

    Rules:
      int  + int  = int
      int  + addr = addr (same csect)
      addr + int  = addr (same csect)
      addr - addr = int  (if same csect, result is integer difference)
      addr + addr = error  (can't add two relocatable addresses)
      addr - addr (different csects) → COMPLEX_SUM
    """
    ka, kb = a.kind, b.kind

    # Both absolute integers
    if ka == ValueKind.ABSOLUTE and kb == ValueKind.ABSOLUTE:
        return Value.absolute(_s32(a.int_val + sign * b.int_val))

    # Integer ± relocatable address
    if ka == ValueKind.ABSOLUTE and kb == ValueKind.RELOCATABLE:
        if sign == -1:
            raise AssemblerError(
                "Cannot subtract a relocatable address from an integer")
        return Value.relocatable(b.csect,
                                  _s32(a.int_val + b.int_val),
                                  b.resolution)

    # Relocatable address ± integer
    if ka == ValueKind.RELOCATABLE and kb == ValueKind.ABSOLUTE:
        return Value.relocatable(a.csect,
                                  _s32(a.int_val + sign * b.int_val),
                                  a.resolution)

    # Relocatable address ± relocatable address
    if ka == ValueKind.RELOCATABLE and kb == ValueKind.RELOCATABLE:
        if sign == -1 and a.csect == b.csect:
            # addr - addr (same section) = absolute integer
            return Value.absolute(_s32(a.int_val - b.int_val))
        else:
            # Build a complex sum
            addends = [
                Addend(+1, a.csect, a.int_val),
                Addend(sign, b.csect, b.int_val),
            ]
            return Value(kind=ValueKind.COMPLEX_SUM, addends=addends,
                         resolution=a.resolution)

    # Complex sum ± simple value
    if ka == ValueKind.COMPLEX_SUM:
        addends = list(a.addends)
        if kb == ValueKind.ABSOLUTE:
            # Fold integer into the absolute addend
            for ad in addends:
                if ad.csect == 0:
                    ad.offset = _s32(ad.offset + sign * b.int_val)
                    return Value(kind=ValueKind.COMPLEX_SUM,
                                 addends=addends, resolution=a.resolution)
            addends.append(Addend(sign, 0, b.int_val))
        elif kb == ValueKind.RELOCATABLE:
            # Try to cancel an existing addend in the same section
            for i, ad in enumerate(addends):
                if ad.csect == b.csect:
                    net = ad.sign * ad.offset + sign * b.int_val
                    if net == 0:
                        addends.pop(i)
                    else:
                        ad.sign = +1 if net > 0 else -1
                        ad.offset = abs(net)
                    break
            else:
                addends.append(Addend(sign, b.csect, b.int_val))
        # If only one relocatable addend remains, simplify
        rel = [ad for ad in addends if ad.csect != 0]
        abs_sum = sum(ad.sign * ad.offset for ad in addends if ad.csect == 0)
        if not rel:
            return Value.absolute(_s32(abs_sum))
        if len(rel) == 1 and rel[0].sign == +1:
            return Value.relocatable(rel[0].csect,
                                      _s32(rel[0].offset + abs_sum),
                                      a.resolution)
        return Value(kind=ValueKind.COMPLEX_SUM, addends=addends,
                     resolution=a.resolution)

    # Undefined propagates
    if ka == ValueKind.UNDEFINED or kb == ValueKind.UNDEFINED:
        return Value.undefined()

    raise AssemblerError(
        f"Cannot add values of kinds {ka.name} and {kb.name}")


def _negate(v: Value) -> Value:
    """Negate a value. Only valid for absolute integers."""
    if v.kind == ValueKind.ABSOLUTE:
        return Value.absolute(_s32(-v.int_val))
    if v.kind == ValueKind.UNDEFINED:
        return v
    raise AssemblerError(f"Cannot negate a {v.kind.name} value")


def _complement(v: Value) -> Value:
    """Bitwise complement (~). Only valid for absolute integers."""
    if v.kind == ValueKind.ABSOLUTE:
        return Value.absolute(_s32(~v.int_val))
    if v.kind == ValueKind.UNDEFINED:
        return v
    raise AssemblerError(f"Cannot complement a {v.kind.name} value")


def _int_binop(op: str, a: Value, b: Value) -> Value:
    """
    Apply a binary integer operator that requires both operands to be
    absolute integers.  Returns UNDEFINED if either operand is undefined.
    """
    if a.kind == ValueKind.UNDEFINED or b.kind == ValueKind.UNDEFINED:
        return Value.undefined()
    if a.kind != ValueKind.ABSOLUTE or b.kind != ValueKind.ABSOLUTE:
        raise AssemblerError(
            f"Operator '{op}' requires integer operands, "
            f"got {a.kind.name} and {b.kind.name}")
    av, bv = a.int_val, b.int_val
    if op == '*':
        result = _s32(av * bv)
    elif op == '/':
        if bv == 0:
            raise AssemblerError("Division by zero")
        # AP '/' is truncating integer division
        result = _s32(int(av / bv))
    elif op == '//':
        # 'Covered quotient': round toward zero (same as C division)
        if bv == 0:
            raise AssemblerError("Division by zero (covered quotient)")
        result = _s32(av // bv if (av >= 0) == (bv >= 0) else -(abs(av) // abs(bv)))
    elif op == '**':
        # Binary shift: a ** b means shift a left by b (right if b < 0)
        if bv >= 0:
            result = _s32(_u32(av) << (bv & 31))
        else:
            result = _s32(_u32(av) >> ((-bv) & 31))
    elif op == '&':
        result = _s32(_u32(av) & _u32(bv))
    elif op == '|':
        result = _s32(_u32(av) | _u32(bv))
    elif op == '||':
        result = _s32(_u32(av) ^ _u32(bv))
    elif op == '=':
        result = -1 if av == bv else 0      # AP: true = -1, false = 0
    elif op == '~=':
        result = -1 if av != bv else 0
    elif op == '>':
        result = -1 if av > bv else 0
    elif op == '>=':
        result = -1 if av >= bv else 0
    elif op == '<':
        result = -1 if av < bv else 0
    elif op == '<=':
        result = -1 if av <= bv else 0
    else:
        raise AssemblerError(f"Unknown operator '{op}'")
    return Value.absolute(result)


def apply_address_function(func: str, v: Value) -> Value:
    """
    Apply an addressing function (BA, HA, WA, DA, ABSVAL) to a value.

    BA(x) → byte address    (multiply by bytes_per_unit)
    HA(x) → halfword address (divide by 2)
    WA(x) → word address    (divide by 4)
    DA(x) → doubleword addr  (divide by 8)
    ABSVAL(x) → absolute value (strip relocation)
    """
    if v.kind == ValueKind.UNDEFINED:
        return v

    target_res = {
        'BA': Resolution.BYTE,
        'HA': Resolution.HW,
        'WA': Resolution.WORD,
        'DA': Resolution.DW,
    }.get(func.upper())

    if target_res is not None:
        # int_val is always stored in bytes; divide to get target-resolution units.
        if v.kind in (ValueKind.ABSOLUTE, ValueKind.RELOCATABLE):
            new_int = target_res.from_byte_offset(v.int_val)  # int_val >> target_res.value
            if v.kind == ValueKind.ABSOLUTE:
                return Value.absolute(new_int)
            else:
                return Value.relocatable(v.csect, new_int, target_res)
        return v.apply_resolution(target_res)

    if func.upper() == 'ABSVAL':
        # Strip relocatability — just return the numeric value
        if v.kind == ValueKind.RELOCATABLE:
            return Value.absolute(v.int_val, v.resolution)
        return v

    raise AssemblerError(f"Unknown address function '{func}'")
