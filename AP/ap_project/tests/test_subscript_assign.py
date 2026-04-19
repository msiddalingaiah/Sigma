"""
tests/test_subscript_assign.py — Tests for subscripted label assignment.

Covers:
  1. _parse_subscript_label: splitting the raw label string
  2. _set_subscript: the pure list-mutation function
  3. DefPass integration: IAN/IAL style patterns through the full pass
  4. GenPass integration: bytes emitted from subscript-built lists

Run with:  python -m pytest tests/test_subscript_assign.py -v
"""

import pytest
from ap_assembler.def_pass import (
    DefPass, _parse_subscript_label, _set_subscript,
)
from ap_assembler.gen_pass import GenPass
from ap_assembler.listing_writer import ListingWriter
from ap_assembler.object_writer import ObjectWriter
from ap_assembler.lexer import tokenize_text
from ap_assembler.symbol_table import SymbolTable
from ap_assembler.value import Value, ValueKind


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_def(source: str) -> SymbolTable:
    stmts = list(tokenize_text(source))
    sym   = SymbolTable()
    DefPass(stmts, sym).run()
    return sym


def assemble(source: str):
    stmts = list(tokenize_text(source))
    sym   = SymbolTable()
    DefPass(stmts, sym).run()
    obj = ObjectWriter()
    lst = ListingWriter()
    GenPass(stmts, sym, obj, lst).run()
    return sym, obj, lst


def sec_bytes(obj, section=1):
    s = obj.get_section(section)
    return bytes(s.data) if s else b''


def sym_val(sym, name):
    e = sym.lookup(name)
    assert e is not None, f"Symbol {name!r} not found"
    return e.value


def sym_list(sym, name):
    v = sym_val(sym, name)
    assert v.kind == ValueKind.LIST, \
        f"{name}: expected LIST, got {v.kind.name}"
    return v.items


def list_item(sym, name, *indices):
    """Navigate into a (possibly nested) list symbol using 1-based indices."""
    v = sym_val(sym, name)
    for idx in indices:
        assert v.kind == ValueKind.LIST, \
            f"Expected LIST at depth, got {v.kind.name}"
        v = v.items[idx - 1]
    return v


# ---------------------------------------------------------------------------
# 1. _parse_subscript_label
# ---------------------------------------------------------------------------

class TestParseSubscriptLabel:
    def test_plain_symbol_returns_none(self):
        assert _parse_subscript_label('SIMPLE') is None

    def test_plain_symbol_with_colon(self):
        assert _parse_subscript_label('M:LO') is None

    def test_single_index(self):
        result = _parse_subscript_label('IAN(I)')
        assert result == ('IAN', ['I'])

    def test_two_indices(self):
        result = _parse_subscript_label('IAN(I,J)')
        assert result == ('IAN', ['I', 'J'])

    def test_two_symbolic_indices(self):
        result = _parse_subscript_label('IAN(INL,:TY)')
        assert result == ('IAN', ['INL', ':TY'])

    def test_three_indices(self):
        result = _parse_subscript_label('X(A,B,C)')
        assert result == ('X', ['A', 'B', 'C'])

    def test_nested_index(self):
        # IAL(IAN(INL,:SC)) → outer index is the whole IAN(...) expression
        result = _parse_subscript_label('IAL(IAN(INL,:SC))')
        assert result == ('IAL', ['IAN(INL,:SC)'])

    def test_nested_two_level(self):
        result = _parse_subscript_label('A(B(C,D),E)')
        assert result == ('A', ['B(C,D)', 'E'])

    def test_integer_index(self):
        result = _parse_subscript_label('CODES(3)')
        assert result == ('CODES', ['3'])

    def test_integer_two_indices(self):
        result = _parse_subscript_label('M(2,1)')
        assert result == ('M', ['2', '1'])

    def test_expression_index(self):
        result = _parse_subscript_label('ARR(I+1)')
        assert result == ('ARR', ['I+1'])

    def test_strips_whitespace_from_indices(self):
        result = _parse_subscript_label('IAN( INL , :TY )')
        assert result is not None
        name, indices = result
        assert name == 'IAN'
        assert indices[0].strip() == 'INL'
        assert indices[1].strip() == ':TY'


# ---------------------------------------------------------------------------
# 2. _set_subscript
# ---------------------------------------------------------------------------

class TestSetSubscript:
    # --- scalar root ---

    def test_scalar_index_1_replaces(self):
        root   = Value.absolute(42)
        result = _set_subscript(root, [1], Value.absolute(99))
        assert result.kind == ValueKind.LIST
        assert len(result.items) == 1
        assert result.items[0].int_val == 99

    def test_scalar_index_2_discards_and_pads(self):
        root   = Value.absolute(42)
        result = _set_subscript(root, [2], Value.absolute(99))
        assert result.kind == ValueKind.LIST
        assert len(result.items) == 2
        assert result.items[0].kind == ValueKind.BLANK   # scalar discarded
        assert result.items[1].int_val == 99

    def test_scalar_index_3_discards_and_pads(self):
        root   = Value.absolute(0)
        result = _set_subscript(root, [3], Value.absolute(5))
        assert len(result.items) == 3
        assert result.items[0].kind == ValueKind.BLANK
        assert result.items[1].kind == ValueKind.BLANK
        assert result.items[2].int_val == 5

    def test_scalar_undefined_index_1(self):
        root   = Value.undefined()
        result = _set_subscript(root, [1], Value.absolute(7))
        assert result.items[0].int_val == 7

    def test_scalar_blank_index_1(self):
        root   = Value.blank()
        result = _set_subscript(root, [1], Value.absolute(7))
        assert result.items[0].int_val == 7

    # --- list root ---

    def test_list_in_range_replaces(self):
        root   = Value.list_val([Value.absolute(10), Value.absolute(20)])
        result = _set_subscript(root, [2], Value.absolute(99))
        assert result.items[0].int_val == 10   # unchanged
        assert result.items[1].int_val == 99   # replaced

    def test_list_in_range_first_element(self):
        root   = Value.list_val([Value.absolute(10), Value.absolute(20)])
        result = _set_subscript(root, [1], Value.absolute(99))
        assert result.items[0].int_val == 99
        assert result.items[1].int_val == 20   # unchanged

    def test_list_extends_with_one_blank(self):
        root   = Value.list_val([Value.absolute(10), Value.absolute(20)])
        result = _set_subscript(root, [3], Value.absolute(30))
        assert len(result.items) == 3
        assert result.items[2].int_val == 30

    def test_list_extends_with_multiple_blanks(self):
        root   = Value.list_val([Value.absolute(1)])
        result = _set_subscript(root, [4], Value.absolute(99))
        assert len(result.items) == 4
        assert result.items[1].kind == ValueKind.BLANK
        assert result.items[2].kind == ValueKind.BLANK
        assert result.items[3].int_val == 99

    def test_original_list_not_mutated(self):
        items  = [Value.absolute(1), Value.absolute(2)]
        root   = Value.list_val(items)
        _set_subscript(root, [1], Value.absolute(99))
        # Original items list should be unchanged
        assert root.items[0].int_val == 1

    # --- 2D indices ---

    def test_2d_in_range(self):
        inner1 = Value.list_val([Value.absolute(1), Value.absolute(2)])
        inner2 = Value.list_val([Value.absolute(3), Value.absolute(4)])
        outer  = Value.list_val([inner1, inner2])
        result = _set_subscript(outer, [2, 1], Value.absolute(99))
        assert result.items[0].items[0].int_val == 1   # unchanged
        assert result.items[1].items[0].int_val == 99  # replaced
        assert result.items[1].items[1].int_val == 4   # unchanged

    def test_2d_on_scalar_root(self):
        # Scalar: index (1,2) → list[[BLANK, val]]
        result = _set_subscript(Value.absolute(0), [1, 2], Value.absolute(5))
        assert result.kind == ValueKind.LIST
        inner  = result.items[0]
        assert inner.kind == ValueKind.LIST
        assert inner.items[0].kind == ValueKind.BLANK
        assert inner.items[1].int_val == 5

    def test_2d_growing_inner_list(self):
        inner = Value.list_val([Value.absolute(10)])
        outer = Value.list_val([inner])
        result = _set_subscript(outer, [1, 3], Value.absolute(30))
        inner2 = result.items[0]
        assert inner2.items[0].int_val == 10  # preserved
        assert inner2.items[1].kind == ValueKind.BLANK
        assert inner2.items[2].int_val == 30

    def test_index_clamped_to_1(self):
        root   = Value.absolute(5)
        result = _set_subscript(root, [0], Value.absolute(9))
        assert result.items[0].int_val == 9

    def test_empty_indices_returns_value(self):
        root   = Value.absolute(42)
        result = _set_subscript(root, [], Value.absolute(99))
        assert result.int_val == 99


# ---------------------------------------------------------------------------
# 3. DefPass integration
# ---------------------------------------------------------------------------

class TestDefPassSubscriptAssign:
    def test_simple_list_element_replace(self):
        src = """\
CODES   EQU    X'AA',X'BB',X'CC'
CODES(2) SET   X'FF'
"""
        sym   = run_def(src)
        items = sym_list(sym, 'CODES')
        assert items[0].int_val == 0xAA
        assert items[1].int_val == 0xFF   # replaced
        assert items[2].int_val == 0xCC

    def test_scalar_grows_to_list(self):
        src = """\
IAN      SET   0
IAN(1)   SET   42
"""
        sym = run_def(src)
        assert list_item(sym, 'IAN', 1).int_val == 42

    def test_scalar_high_index_pads_blanks(self):
        src = """\
X        SET   0
X(3)     SET   99
"""
        sym   = run_def(src)
        items = sym_list(sym, 'X')
        assert len(items) == 3
        assert items[0].kind == ValueKind.BLANK
        assert items[1].kind == ValueKind.BLANK
        assert items[2].int_val == 99

    def test_multiple_subscript_assignments(self):
        # Build a list element by element
        src = """\
ARR      SET   0
ARR(1)   SET   10
ARR(2)   SET   20
ARR(3)   SET   30
"""
        sym   = run_def(src)
        items = sym_list(sym, 'ARR')
        assert [i.int_val for i in items] == [10, 20, 30]

    def test_2d_assignment(self):
        # IAN(1,:TY) SET and IAN(2,:TY) SET where :TY is an EQU
        src = """\
:TY      EQU   1
INL      SET   0
IAN      SET   0
INL      SET   INL+1
IAN(INL,:TY)  SET  X'AA'
INL      SET   INL+1
IAN(INL,:TY)  SET  X'BB'
"""
        sym = run_def(src)
        # INL ends at 2; IAN should be a 2-element list of 1-element lists
        assert list_item(sym, 'IAN', 1, 1).int_val == 0xAA
        assert list_item(sym, 'IAN', 2, 1).int_val == 0xBB

    def test_subscript_uses_set_semantics(self):
        # After subscript assignment, the symbol should be re-definable (SET)
        src = """\
X        EQU   0
X(1)     SET   5
X(1)     SET   6
"""
        sym = run_def(src)
        assert list_item(sym, 'X', 1).int_val == 6

    def test_do_loop_builds_list(self):
        # Classic AP pattern: iterate and fill a list
        src = """\
ARR      SET   0
I        SET   0
         DO    4
I        SET   I+1
ARR(I)   SET   I*10
         FIN
"""
        sym   = run_def(src)
        items = sym_list(sym, 'ARR')
        assert [i.int_val for i in items] == [10, 20, 30, 40]

    def test_ian_ial_pattern(self):
        # Simplified version of the IF/FI IAN/IAL pattern
        src = """\
:TY      EQU   1
:SC      EQU   2
INL      SET   0
IAN      SET   0
IAL      SET   0
*  Push one IF frame
INL           SET   INL+1
IAN(INL,:TY)  SET   1
IAN(INL,:SC)  SET   99
IAL(IAN(INL,:SC))  SET   X'1234'
"""
        sym = run_def(src)
        # INL = 1
        assert sym_val(sym, 'INL').int_val == 1
        # IAN(1,1) = 1  (type = %IF%)
        assert list_item(sym, 'IAN', 1, 1).int_val == 1
        # IAN(1,2) = 99  (success address index)
        assert list_item(sym, 'IAN', 1, 2).int_val == 99
        # IAL(99) = 0x1234  (the address stored at that IAL slot)
        assert list_item(sym, 'IAL', 99).int_val == 0x1234

    def test_undefined_symbol_gets_created(self):
        # Assigning to a subscript of an undefined symbol creates it
        src = "NEW(2)  SET  42\n"
        sym = run_def(src)
        e = sym.lookup('NEW')
        assert e is not None
        assert e.value.kind == ValueKind.LIST

    def test_existing_list_element_unchanged(self):
        # Assigning to element 1 should not disturb other elements
        src = """\
LST      EQU   X'AA',X'BB',X'CC'
LST(1)   SET   X'11'
"""
        sym   = run_def(src)
        items = sym_list(sym, 'LST')
        assert items[0].int_val == 0x11
        assert items[1].int_val == 0xBB
        assert items[2].int_val == 0xCC

    def test_subscript_with_expression_index(self):
        src = """\
N        EQU   2
LST      SET   0
LST(N)   SET   X'AB'
"""
        sym = run_def(src)
        assert list_item(sym, 'LST', 2).int_val == 0xAB

    def test_subscript_with_arithmetic_index(self):
        src = """\
BASE     EQU   1
LST      SET   0
LST(BASE+1)  SET  X'CD'
"""
        sym = run_def(src)
        assert list_item(sym, 'LST', 2).int_val == 0xCD


# ---------------------------------------------------------------------------
# 4. GenPass integration: subscript-built lists produce correct bytes
# ---------------------------------------------------------------------------

class TestGenPassSubscriptAssign:
    def test_data_from_subscript_built_list(self):
        src = """\
ARR      SET   0
ARR(1)   SET   X'11111111'
ARR(2)   SET   X'22222222'
ARR(3)   SET   X'33333333'
         DATA  ARR(1),ARR(2),ARR(3)
"""
        _, obj, _ = assemble(src)
        raw = sec_bytes(obj)
        assert raw == (b'\x11\x11\x11\x11' +
                       b'\x22\x22\x22\x22' +
                       b'\x33\x33\x33\x33')

    def test_do_loop_fill_then_emit(self):
        # Fill a list by subscripted assignment, then emit it
        src = """\
VALS     SET   0
I        SET   0
         DO    3
I        SET   I+1
VALS(I)  SET   I*X'10'
         FIN
         DATA  VALS(1),VALS(2),VALS(3)
"""
        _, obj, _ = assemble(src)
        raw = sec_bytes(obj)
        assert raw == (b'\x00\x00\x00\x10' +
                       b'\x00\x00\x00\x20' +
                       b'\x00\x00\x00\x30')

    def test_two_pass_consistency(self):
        # DEF and GEN pass must agree on LC
        src = """\
ARR      SET   0
ARR(1)   SET   4
ARR(2)   SET   8
I        SET   0
         DO    2
I        SET   I+1
         RES,1  ARR(I)
         FIN
"""
        stmts = list(tokenize_text(src))
        sym1  = SymbolTable()
        DefPass(stmts, sym1).run()
        def_lc = sym1.exec_lc()

        sym2  = SymbolTable()
        DefPass(stmts, sym2).run()
        obj = ObjectWriter()
        lst = ListingWriter()
        GenPass(stmts, sym2, obj, lst).run()
        gen_lc = sym2.exec_lc()

        assert def_lc == gen_lc
        assert def_lc == 4 + 8   # ARR(1)=4 bytes + ARR(2)=8 bytes

    def test_2d_list_subscript_in_data(self):
        src = """\
M        SET   0
M(1,1)   SET   X'AA'
M(1,2)   SET   X'BB'
M(2,1)   SET   X'CC'
         DATA  M(1,1),M(1,2),M(2,1)
"""
        _, obj, _ = assemble(src)
        raw = sec_bytes(obj)
        assert raw == (b'\x00\x00\x00\xAA' +
                       b'\x00\x00\x00\xBB' +
                       b'\x00\x00\x00\xCC')

    def test_blank_element_emits_zero(self):
        # X(3) SET 5 → [BLANK, BLANK, 5]; DATA X(1) emits zero
        src = """\
X        SET   0
X(3)     SET   5
         DATA  X(1)
"""
        _, obj, _ = assemble(src)
        assert sec_bytes(obj) == b'\x00\x00\x00\x00'


# ---------------------------------------------------------------------------
# 5. Edge cases and error tolerance
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_index_zero_treated_as_one(self):
        src = """\
X        SET   0
X(0)     SET   99
"""
        sym = run_def(src)
        assert list_item(sym, 'X', 1).int_val == 99

    def test_no_existing_tests_broken(self):
        # Ensure plain (non-subscripted) labels still work normally
        sym = run_def("ALPHA  EQU  5\nBETA  EQU  ALPHA+1\n")
        assert sym_val(sym, 'ALPHA').int_val == 5
        assert sym_val(sym, 'BETA').int_val == 6

    def test_plain_label_at_lc(self):
        sym = run_def("START  RES  0\n       RES  2\nEND1   RES  0\n")
        assert sym_val(sym, 'START').int_val == 0
        assert sym_val(sym, 'END1').int_val == 8

    def test_subscript_assign_does_not_affect_other_symbols(self):
        src = """\
A        EQU   1
B        EQU   2
ARR      SET   0
ARR(1)   SET   99
"""
        sym = run_def(src)
        assert sym_val(sym, 'A').int_val == 1
        assert sym_val(sym, 'B').int_val == 2
        assert list_item(sym, 'ARR', 1).int_val == 99

    def test_ial_growing_address_table(self):
        # IAL grows as addresses are stored — simulating the IF/FI pattern
        src = """\
NXTIN    EQU   0
IAL      SET   0
IN1      SET   0
IN2      SET   1
*  NXTIN would normally be a FNAME; simulate with simple counter
IN1      SET   IN1+1
IAL(IN1) SET   X'1000'
IN1      SET   IN1+1
IAL(IN1) SET   X'2000'
IN1      SET   IN1+1
IAL(IN1) SET   X'3000'
"""
        sym   = run_def(src)
        assert sym_val(sym, 'IN1').int_val == 3
        assert list_item(sym, 'IAL', 1).int_val == 0x1000
        assert list_item(sym, 'IAL', 2).int_val == 0x2000
        assert list_item(sym, 'IAL', 3).int_val == 0x3000


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
