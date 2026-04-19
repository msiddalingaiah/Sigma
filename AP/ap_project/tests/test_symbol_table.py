"""
tests/test_symbol_table.py — Tests for value.py, symbol_table.py, expression.py

Covers:
  1. Value arithmetic (add, subtract, negate, complement, int operators)
  2. Addressing functions (BA, HA, WA, DA, ABSVAL)
  3. ControlSection location counter operations
  4. SymbolTable: define, lookup, local scopes, external marking
  5. ExpressionEvaluator: full integration through the token pipeline
"""

from typing import List

import pytest

from ap_assembler.value import (
    Value, ValueKind, Resolution, Addend, AssemblerError,
    _add_values, _negate, _complement, _int_binop,
    apply_address_function, _s32, _u32,
)
from ap_assembler.symbol_table import (
    SymbolTable, ControlSection, CsectKind, SymbolEntry,
    PASS_DEF, PASS_GEN,
)
from ap_assembler.expression import ExpressionEvaluator, evaluate_arg
from ap_assembler.lexer import ArgTokenizer, TT, Token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def abs_val(n: int) -> Value:
    return Value.absolute(n)

def rel_val(csect: int, offset: int) -> Value:
    return Value.relocatable(csect, offset)

def tokens(text: str) -> List[List[Token]]:
    return ArgTokenizer(text, line_no=1, start_col=0).tokenize()

def eval_expr(text: str, sym: SymbolTable = None) -> Value:
    """Parse and evaluate a single expression string."""
    if sym is None:
        sym = SymbolTable()
    toks = tokens(text)
    if not toks:
        return Value.blank()
    v, errs = evaluate_arg(toks[0], sym)
    return v


# ---------------------------------------------------------------------------
# 1. Value: basic construction
# ---------------------------------------------------------------------------

class TestValueConstruction:
    def test_absolute(self):
        v = Value.absolute(42)
        assert v.kind == ValueKind.ABSOLUTE
        assert v.int_val == 42

    def test_absolute_negative(self):
        v = Value.absolute(-1)
        assert v.int_val == -1

    def test_absolute_wraps_32bit(self):
        # Values larger than 32-bit should be masked
        v = Value.absolute(0x1_0000_0001)
        assert v.int_val == 1

    def test_relocatable(self):
        v = Value.relocatable(3, 100)
        assert v.kind == ValueKind.RELOCATABLE
        assert v.csect == 3
        assert v.int_val == 100

    def test_undefined(self):
        v = Value.undefined()
        assert v.kind == ValueKind.UNDEFINED
        assert not v.is_defined

    def test_blank(self):
        v = Value.blank()
        assert v.kind == ValueKind.BLANK

    def test_external(self):
        v = Value.external('M:LO')
        assert v.kind == ValueKind.EXTERNAL
        assert v.name == 'M:LO'

    def test_pkdec(self):
        v = Value.pkdec('+99')
        assert v.kind == ValueKind.PKDEC
        assert v.raw == '+99'

    def test_charstr(self):
        v = Value.charstr('ABCD')
        assert v.kind == ValueKind.CHARSTR
        assert v.raw == 'ABCD'

    def test_fs(self):
        v = Value.fs('5.5E-3')
        assert v.kind == ValueKind.FS

    def test_predicates(self):
        assert Value.absolute(0).is_integer()
        assert Value.relocatable(1, 0).is_address()
        assert not Value.absolute(0).is_address()
        assert Value.pkdec('+1').is_constant()


# ---------------------------------------------------------------------------
# 2. Value: arithmetic
# ---------------------------------------------------------------------------

class TestValueArithmetic:
    # --- int + int ---
    def test_add_int_int(self):
        r = _add_values(abs_val(10), abs_val(5))
        assert r.kind == ValueKind.ABSOLUTE
        assert r.int_val == 15

    def test_sub_int_int(self):
        r = _add_values(abs_val(10), abs_val(5), sign=-1)
        assert r.int_val == 5

    def test_add_overflow_wraps(self):
        r = _add_values(abs_val(0x7FFF_FFFF), abs_val(1))
        # Wraps to -2147483648
        assert r.int_val == -0x8000_0000

    # --- int + addr ---
    def test_add_int_addr(self):
        r = _add_values(abs_val(4), rel_val(1, 100))
        assert r.kind == ValueKind.RELOCATABLE
        assert r.csect == 1
        assert r.int_val == 104

    def test_sub_int_from_addr_disallowed(self):
        with pytest.raises(AssemblerError):
            _add_values(abs_val(10), rel_val(1, 4), sign=-1)

    # --- addr + int ---
    def test_add_addr_int(self):
        r = _add_values(rel_val(2, 8), abs_val(4))
        assert r.kind == ValueKind.RELOCATABLE
        assert r.csect == 2
        assert r.int_val == 12

    def test_sub_addr_int(self):
        r = _add_values(rel_val(2, 8), abs_val(4), sign=-1)
        assert r.int_val == 4

    # --- addr - addr (same section) → int ---
    def test_sub_addr_addr_same_section(self):
        r = _add_values(rel_val(1, 20), rel_val(1, 8), sign=-1)
        assert r.kind == ValueKind.ABSOLUTE
        assert r.int_val == 12

    # --- addr + addr (same section) → COMPLEX_SUM (not an error in AP)
    def test_add_addr_addr_same_section_complex(self):
        r = _add_values(rel_val(1, 0), rel_val(1, 4))
        assert r.kind == ValueKind.COMPLEX_SUM

    # --- addr - addr (different sections) → complex ---
    def test_sub_addr_addr_diff_sections(self):
        r = _add_values(rel_val(1, 20), rel_val(2, 8), sign=-1)
        assert r.kind == ValueKind.COMPLEX_SUM
        assert len(r.addends) == 2

    # --- complex + int ---
    def test_complex_plus_int(self):
        base = _add_values(rel_val(1, 20), rel_val(2, 8), sign=-1)
        r = _add_values(base, abs_val(4))
        assert r.kind == ValueKind.COMPLEX_SUM

    # --- negate ---
    def test_negate_int(self):
        r = _negate(abs_val(5))
        assert r.int_val == -5

    def test_negate_addr_raises(self):
        with pytest.raises(AssemblerError):
            _negate(rel_val(1, 10))

    def test_negate_undefined(self):
        r = _negate(Value.undefined())
        assert r.kind == ValueKind.UNDEFINED

    # --- complement ---
    def test_complement_zero(self):
        r = _complement(abs_val(0))
        assert r.int_val == -1   # ~0 = 0xFFFFFFFF = -1 in signed 32-bit

    def test_complement_minus_one(self):
        r = _complement(abs_val(-1))
        assert r.int_val == 0


# ---------------------------------------------------------------------------
# 3. Integer binary operators
# ---------------------------------------------------------------------------

class TestIntBinop:
    def test_multiply(self):
        assert _int_binop('*', abs_val(6), abs_val(7)).int_val == 42

    def test_divide(self):
        assert _int_binop('/', abs_val(7), abs_val(2)).int_val == 3

    def test_divide_by_zero(self):
        with pytest.raises(AssemblerError):
            _int_binop('/', abs_val(1), abs_val(0))

    def test_covered_divide(self):
        assert _int_binop('//', abs_val(7), abs_val(2)).int_val == 3
        assert _int_binop('//', abs_val(-7), abs_val(2)).int_val == -3

    def test_scale_left(self):
        # 1**4 means 1 << 4 = 16
        assert _int_binop('**', abs_val(1), abs_val(4)).int_val == 16

    def test_scale_right(self):
        # 16 ** -1 means 16 >> 1 = 8
        assert _int_binop('**', abs_val(16), abs_val(-1)).int_val == 8

    def test_and(self):
        assert _int_binop('&', abs_val(0xFF), abs_val(0x0F)).int_val == 0x0F

    def test_or(self):
        assert _int_binop('|', abs_val(0xF0), abs_val(0x0F)).int_val == 0xFF

    def test_xor(self):
        assert _int_binop('||', abs_val(0xFF), abs_val(0x0F)).int_val == 0xF0

    def test_eq_true(self):
        assert _int_binop('=', abs_val(5), abs_val(5)).int_val == -1

    def test_eq_false(self):
        assert _int_binop('=', abs_val(5), abs_val(6)).int_val == 0

    def test_neq(self):
        assert _int_binop('~=', abs_val(5), abs_val(6)).int_val == -1

    def test_gt(self):
        assert _int_binop('>', abs_val(5), abs_val(3)).int_val == -1
        assert _int_binop('>', abs_val(3), abs_val(5)).int_val == 0

    def test_lt(self):
        assert _int_binop('<', abs_val(3), abs_val(5)).int_val == -1

    def test_gte(self):
        assert _int_binop('>=', abs_val(5), abs_val(5)).int_val == -1
        assert _int_binop('>=', abs_val(4), abs_val(5)).int_val == 0

    def test_lte(self):
        assert _int_binop('<=', abs_val(5), abs_val(5)).int_val == -1

    def test_undefined_propagates(self):
        r = _int_binop('*', Value.undefined(), abs_val(5))
        assert r.kind == ValueKind.UNDEFINED


# ---------------------------------------------------------------------------
# 4. Addressing functions
# ---------------------------------------------------------------------------

class TestAddressFunctions:
    def test_wa_on_byte_addr(self):
        # 8-byte address → WA = 8 / 4 = 2 word units
        v = Value.relocatable(1, 8, Resolution.BYTE)
        r = apply_address_function('WA', v)
        assert r.int_val == 2
        assert r.resolution == Resolution.WORD

    def test_ba_on_word_addr(self):
        # 16-byte address (stored as 16 regardless of resolution label) → BA = 16
        v = Value.relocatable(1, 16, Resolution.WORD)
        r = apply_address_function('BA', v)
        assert r.int_val == 16
        assert r.resolution == Resolution.BYTE

    def test_ha_on_word_addr(self):
        # 16-byte address → HA = 16 / 2 = 8 halfword units
        v = Value.relocatable(1, 16, Resolution.WORD)
        r = apply_address_function('HA', v)
        assert r.int_val == 8
        assert r.resolution == Resolution.HW

    def test_da_on_word_addr(self):
        # 16-byte address → DA = 16 / 8 = 2 doubleword units
        v = Value.relocatable(1, 16, Resolution.WORD)
        r = apply_address_function('DA', v)
        assert r.int_val == 2
        assert r.resolution == Resolution.DW

    def test_absval_strips_relocation(self):
        v = Value.relocatable(3, 100)
        r = apply_address_function('ABSVAL', v)
        assert r.kind == ValueKind.ABSOLUTE
        assert r.int_val == 100

    def test_ba_on_absolute(self):
        # Absolute value — BA is a no-op (divide by 1)
        v = Value.absolute(16)
        r = apply_address_function('BA', v)
        assert r.kind == ValueKind.ABSOLUTE
        assert r.int_val == 16

    def test_undefined_passes_through(self):
        v = Value.undefined()
        r = apply_address_function('BA', v)
        assert r.kind == ValueKind.UNDEFINED

    def test_unknown_function_raises(self):
        with pytest.raises(AssemblerError):
            apply_address_function('ZZ', abs_val(0))


# ---------------------------------------------------------------------------
# 5. ControlSection
# ---------------------------------------------------------------------------

class TestControlSection:
    def test_advance(self):
        cs = ControlSection(1, CsectKind.CSECT, 'TEST')
        cs.advance(8)
        assert cs.exec_lc == 8
        assert cs.load_lc == 8
        assert cs.max_load_lc == 8

    def test_align_no_op(self):
        cs = ControlSection(1, CsectKind.CSECT)
        cs.advance(8)
        pad = cs.align(4)
        assert pad == 0
        assert cs.exec_lc == 8

    def test_align_needed(self):
        cs = ControlSection(1, CsectKind.CSECT)
        cs.advance(5)
        pad = cs.align(4)
        assert pad == 3
        assert cs.exec_lc == 8

    def test_current_value(self):
        cs = ControlSection(2, CsectKind.CSECT)
        cs.advance(16)
        v = cs.current_value()
        assert v.kind == ValueKind.RELOCATABLE
        assert v.csect == 2
        assert v.int_val == 16

    def test_max_load_tracks_high_water(self):
        cs = ControlSection(1, CsectKind.CSECT)
        cs.advance(100)
        assert cs.max_load_lc == 100
        cs.advance(10)
        assert cs.max_load_lc == 110   # always the high-water of load_lc


# ---------------------------------------------------------------------------
# 6. SymbolTable
# ---------------------------------------------------------------------------

class TestSymbolTable:
    def setup_method(self):
        self.sym = SymbolTable()

    def test_initial_state(self):
        assert self.sym.current_pass == PASS_DEF
        assert self.sym.section_count() == 2   # ASECT + default CSECT
        assert self.sym.exec_lc() == 0

    def test_define_and_lookup(self):
        self.sym.define('ALPHA', Value.absolute(5))
        entry = self.sym.lookup('ALPHA')
        assert entry is not None
        assert entry.value.int_val == 5

    def test_lookup_case_insensitive(self):
        self.sym.define('alpha', Value.absolute(99))
        assert self.sym.lookup('ALPHA') is not None
        assert self.sym.lookup('Alpha') is not None

    def test_lookup_missing_returns_none(self):
        assert self.sym.lookup('NOPE') is None

    def test_lookup_or_create_creates_undefined(self):
        entry = self.sym.lookup_or_create('NEW')
        assert entry.value.kind == ValueKind.UNDEFINED
        assert not entry.is_defined

    def test_define_set_redefinable(self):
        self.sym.define('X', Value.absolute(1), is_set=True)
        self.sym.define('X', Value.absolute(2), is_set=True)
        assert self.sym.lookup('X').value.int_val == 2

    def test_mark_external_ref(self):
        self.sym.mark_external('M:LO', 'ref')
        e = self.sym.lookup('M:LO')
        assert e.is_ref
        assert e.value.kind == ValueKind.EXTERNAL

    def test_mark_external_def(self):
        self.sym.define('MYFUNC', Value.absolute(0))
        self.sym.mark_external('MYFUNC', 'def')
        e = self.sym.lookup('MYFUNC')
        assert e.is_def

    def test_advance_lc(self):
        self.sym.advance_lc(12)
        assert self.sym.exec_lc() == 12

    def test_align_lc(self):
        self.sym.advance_lc(5)
        pad = self.sym.align_lc(4)
        assert pad == 3
        assert self.sym.exec_lc() == 8

    def test_dollar_value(self):
        self.sym.advance_lc(16)
        v = self.sym.dollar_value()
        assert v.kind == ValueKind.RELOCATABLE
        assert v.int_val == 16

    def test_open_new_section(self):
        cs = self.sym.open_section(CsectKind.CSECT, 'MYCS')
        assert cs.number == 2
        assert cs.name == 'MYCS'
        assert self.sym.current_section.number == 2

    def test_reenter_named_section(self):
        cs1 = self.sym.open_section(CsectKind.CSECT, 'A')
        self.sym.advance_lc(100)
        # Switch away
        self.sym.open_section(CsectKind.CSECT, 'B')
        self.sym.advance_lc(50)
        # Re-enter A
        cs2 = self.sym.open_section(CsectKind.USECT, 'A')
        assert cs2.number == cs1.number
        assert self.sym.exec_lc() == 100   # resumes where we left off

    def test_gen_pass_resets_lc(self):
        self.sym.advance_lc(200)
        self.sym.begin_gen_pass()
        assert self.sym.current_pass == PASS_GEN
        assert self.sym.exec_lc() == 0

    def test_local_scope(self):
        self.sym.define('LOCSYM', Value.absolute(1))
        self.sym.push_local_scope()
        self.sym.define('LOCSYM', Value.absolute(99), is_local=True)
        assert self.sym.lookup('LOCSYM').value.int_val == 99
        self.sym.pop_local_scope()
        assert self.sym.lookup('LOCSYM').value.int_val == 1

    def test_declare_local(self):
        self.sym.push_local_scope()
        self.sym.declare_local('TMP')
        e = self.sym.lookup('TMP')
        assert e is not None
        assert e.is_local
        self.sym.pop_local_scope()


# ---------------------------------------------------------------------------
# 7. ExpressionEvaluator — basic constants
# ---------------------------------------------------------------------------

class TestEvalConstants:
    def setup_method(self):
        self.sym = SymbolTable()

    def test_integer(self):
        v = eval_expr('42', self.sym)
        assert v.kind == ValueKind.ABSOLUTE
        assert v.int_val == 42

    def test_hex(self):
        v = eval_expr("X'FF'", self.sym)
        assert v.int_val == 255

    def test_octal(self):
        v = eval_expr("O'17'", self.sym)
        assert v.int_val == 0o17

    def test_negative(self):
        v = eval_expr('-185', self.sym)
        assert v.int_val == -185

    def test_complement(self):
        v = eval_expr('~0', self.sym)
        assert v.int_val == -1   # ~0 = 0xFFFFFFFF = -1 in signed 32-bit

    def test_char_string(self):
        v = eval_expr("'ABCD'", self.sym)
        assert v.kind == ValueKind.CHARSTR
        assert v.raw == 'ABCD'

    def test_pkdec(self):
        v = eval_expr("D'+99'", self.sym)
        assert v.kind == ValueKind.PKDEC
        assert v.raw == '+99'

    def test_fs(self):
        v = eval_expr("FS'5.5E-3'", self.sym)
        assert v.kind == ValueKind.FS

    def test_blank(self):
        toks = ArgTokenizer('', line_no=1, start_col=0).tokenize()
        assert toks == []

    def test_blank_arg(self):
        toks = ArgTokenizer(',42', line_no=1, start_col=0).tokenize()
        v, _ = evaluate_arg(toks[0], self.sym)
        assert v.kind == ValueKind.BLANK


# ---------------------------------------------------------------------------
# 8. ExpressionEvaluator — arithmetic
# ---------------------------------------------------------------------------

class TestEvalArithmetic:
    def setup_method(self):
        self.sym = SymbolTable()

    def test_add(self):
        assert eval_expr('3+4', self.sym).int_val == 7

    def test_sub(self):
        assert eval_expr('10-3', self.sym).int_val == 7

    def test_mul(self):
        assert eval_expr('6*7', self.sym).int_val == 42

    def test_div(self):
        assert eval_expr('10/3', self.sym).int_val == 3

    def test_covered_div(self):
        assert eval_expr('7//2', self.sym).int_val == 3

    def test_scale_left(self):
        # 1**4 = 16
        assert eval_expr('1**4', self.sym).int_val == 16

    def test_scale_right(self):
        # 16**-1 = 8
        assert eval_expr('16**-1', self.sym).int_val == 8

    def test_and(self):
        assert eval_expr("X'FF'&X'0F'", self.sym).int_val == 0x0F

    def test_or(self):
        assert eval_expr("X'F0'|X'0F'", self.sym).int_val == 0xFF

    def test_xor(self):
        assert eval_expr("X'FF'||X'0F'", self.sym).int_val == 0xF0

    def test_comparison_true(self):
        assert eval_expr('5=5', self.sym).int_val == -1

    def test_comparison_false(self):
        assert eval_expr('5=6', self.sym).int_val == 0

    def test_parens(self):
        assert eval_expr('(3+4)*2', self.sym).int_val == 14

    def test_complex_expr(self):
        # From testtese.txt: NDOI+3  where NDOI=2 → 5
        self.sym.define('NDOI', Value.absolute(2))
        assert eval_expr('NDOI+3', self.sym).int_val == 5


# ---------------------------------------------------------------------------
# 9. ExpressionEvaluator — symbol references
# ---------------------------------------------------------------------------

class TestEvalSymbols:
    def setup_method(self):
        self.sym = SymbolTable()

    def test_defined_symbol(self):
        self.sym.define('A1', Value.absolute(5))
        v = eval_expr('A1', self.sym)
        assert v.int_val == 5

    def test_undefined_symbol_returns_undefined(self):
        v = eval_expr('UNKNOWN', self.sym)
        assert v.kind == ValueKind.UNDEFINED

    def test_dollar(self):
        self.sym.advance_lc(16)
        v = eval_expr('%', self.sym)
        assert v.kind == ValueKind.RELOCATABLE
        assert v.int_val == 16

    def test_dollar_plus_int(self):
        self.sym.advance_lc(8)
        v = eval_expr('%+4', self.sym)
        assert v.kind == ValueKind.RELOCATABLE
        assert v.int_val == 12

    def test_symbol_arithmetic(self):
        self.sym.define('A1', Value.absolute(5))
        self.sym.define('A2', Value.absolute(6))
        v = eval_expr('A1+A2', self.sym)
        assert v.int_val == 11

    def test_relocatable_minus_relocatable(self):
        # R1-R2 where R1, R2 in same section → absolute
        self.sym.define('R1', Value.relocatable(1, 20))
        self.sym.define('R2', Value.relocatable(1, 8))
        v = eval_expr('R1-R2', self.sym)
        assert v.kind == ValueKind.ABSOLUTE
        assert v.int_val == 12

    def test_relocatable_plus_absolute(self):
        self.sym.define('R1', Value.relocatable(1, 20))
        self.sym.define('A1', Value.absolute(5))
        v = eval_expr('R1+A1', self.sym)
        assert v.kind == ValueKind.RELOCATABLE
        assert v.int_val == 25


# ---------------------------------------------------------------------------
# 10. ExpressionEvaluator — addressing functions
# ---------------------------------------------------------------------------

class TestEvalAddressFunctions:
    def setup_method(self):
        self.sym = SymbolTable()

    def test_ba_of_word_addr(self):
        # int_val is bytes: 16 bytes with word resolution label → BA = 16
        self.sym.define('ADRS', Value.relocatable(1, 16, Resolution.WORD))
        v = eval_expr('BA(ADRS)', self.sym)
        assert v.int_val == 16
        assert v.resolution == Resolution.BYTE

    def test_wa_of_byte_addr(self):
        # 16 bytes → WA = 16 / 4 = 4 word units
        self.sym.define('ADRS', Value.relocatable(1, 16, Resolution.BYTE))
        v = eval_expr('WA(ADRS)', self.sym)
        assert v.int_val == 4
        assert v.resolution == Resolution.WORD

    def test_ba_of_dollar(self):
        # advance_lc(8) = 8 bytes; BA(%) = 8
        self.sym.advance_lc(8)
        v = eval_expr('BA(%)', self.sym)
        assert v.int_val == 8

    def test_nested_ba_wa(self):
        # BA is identity (bytes→bytes), WA divides by 4
        self.sym.define('X', Value.relocatable(1, 16, Resolution.WORD))
        v = eval_expr('BA(WA(BA(X)))', self.sym)
        # BA(16)=16, WA(16)=4, BA(4)=4
        assert v.int_val == 4

    def test_absval(self):
        self.sym.define('R', Value.relocatable(3, 100))
        v = eval_expr('ABSVAL(R)', self.sym)
        assert v.kind == ValueKind.ABSOLUTE
        assert v.int_val == 100

    def test_ba_plus_int(self):
        # 16-byte address, BA = 16, +1 = 17
        self.sym.define('ADRS', Value.relocatable(1, 16, Resolution.WORD))
        v = eval_expr('BA(ADRS)+1', self.sym)
        assert v.int_val == 17


# ---------------------------------------------------------------------------
# 11. ExpressionEvaluator — full round-trip from testtese examples
# ---------------------------------------------------------------------------

class TestEvalRoundTrip:
    def setup_method(self):
        self.sym = SymbolTable()
        # Set up symbols from testtese.txt
        self.sym.define('A1', Value.absolute(5))
        self.sym.define('A2', Value.absolute(6))
        self.sym.advance_lc(4)    # simulate some progress
        self.sym.define('R1', self.sym.dollar_value())
        self.sym.advance_lc(4)
        self.sym.define('R2', self.sym.dollar_value())
        self.sym.advance_lc(4)
        self.sym.define('R3', self.sym.dollar_value())

    def test_r1_plus_a1(self):
        v = eval_expr('R1+A1', self.sym)
        assert v.kind == ValueKind.RELOCATABLE
        assert v.int_val == 9    # R1=4, A1=5

    def test_r1_minus_a1(self):
        v = eval_expr('R1-A1', self.sym)
        assert v.kind == ValueKind.RELOCATABLE
        assert v.int_val == -1   # R1=4, A1=5 → -1 (addr-int)

    def test_r1_minus_r2(self):
        v = eval_expr('R1-R2', self.sym)
        assert v.kind == ValueKind.ABSOLUTE
        assert v.int_val == -4   # R1=4, R2=8

    def test_a1_plus_a2(self):
        v = eval_expr('A1+A2', self.sym)
        assert v.int_val == 11

    def test_a1_minus_a2(self):
        v = eval_expr('A1-A2', self.sym)
        assert v.int_val == -1

    def test_scale_constant(self):
        # From testtese: 1**128 — shift 1 left by 128 (→ huge number, wraps)
        # In AP, ** is limited to 32-bit, so 1**31 = 0x80000000 = -2^31
        v = eval_expr('1**31', self.sym)
        assert v.int_val == _s32(1 << 31)

    def test_hex_expression(self):
        # X'3C' + 1
        v = eval_expr("X'3C'+1", self.sym)
        assert v.int_val == 0x3D

    def test_complex_r1_minus_r2_plus_r3(self):
        v = eval_expr('R1-R2+R3', self.sym)
        # R1=4, R2=8, R3=12 → all same section
        # R1-R2 = absolute(-4), then +R3(relocatable) → relocatable
        assert v.kind == ValueKind.RELOCATABLE


# ---------------------------------------------------------------------------
# 12. SymbolTable — section-level integration
# ---------------------------------------------------------------------------

class TestSectionIntegration:
    def test_define_label_at_current_lc(self):
        sym = SymbolTable()
        sym.advance_lc(16)
        v = sym.dollar_value()
        sym.define('LABEL', v)
        e = sym.lookup('LABEL')
        assert e.value.kind == ValueKind.RELOCATABLE
        assert e.value.int_val == 16
        assert e.value.csect == 1

    def test_res_advances_lc(self):
        sym = SymbolTable()
        sym.define('R1', sym.dollar_value())
        sym.advance_lc(8)    # RES 2 (2 words = 8 bytes)
        sym.define('R2', sym.dollar_value())
        r1 = sym.lookup('R1').value
        r2 = sym.lookup('R2').value
        assert r2.int_val - r1.int_val == 8

    def test_align_generates_padding(self):
        sym = SymbolTable()
        sym.advance_lc(5)
        sym.align_lc(4)
        assert sym.exec_lc() == 8

    def test_multiple_sections(self):
        sym = SymbolTable()
        cs2 = sym.open_section(CsectKind.CSECT, 'DATA')
        sym.advance_lc(100)
        sym.switch_to_section(1)    # back to default code section
        sym.advance_lc(200)
        assert sym.get_section(2).exec_lc == 100
        assert sym.exec_lc() == 200


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
