"""
tests/test_lists.py — Tests for AP list support.

Covers all five layers of the implementation:
  1. Lexer: (a,b,c) produces COMMA tokens within a single arg
  2. value.py: LIST kind, list_val factory, is_list predicate
  3. expression.py: list literals, subscript navigation, AP blank rules
  4. def_pass.py: multi-arg EQU/SET builds list symbols
  5. gen_pass.py: subscript access in DATA, DO loops over lists

Run with:  python -m pytest tests/test_lists.py -v
"""

import pytest
from ap_assembler.lexer import ArgTokenizer, TT, tokenize_text
from ap_assembler.value import Value, ValueKind, Resolution
from ap_assembler.expression import ExpressionEvaluator, evaluate_arg, _subscript
from ap_assembler.symbol_table import SymbolTable
from ap_assembler.def_pass import DefPass
from ap_assembler.gen_pass import GenPass
from ap_assembler.listing_writer import ListingWriter
from ap_assembler.object_writer import ObjectWriter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def tok(text):
    """Tokenise an argument field and return the list of arg lists."""
    return ArgTokenizer(text, line_no=1, start_col=0).tokenize()


def token_types(arg):
    """Return the TT types of tokens in one arg list."""
    return [t.type for t in arg]


def eval_expr(text, sym=None):
    if sym is None:
        sym = SymbolTable()
    args = tok(text)
    if not args:
        return Value.blank()
    v, _ = evaluate_arg(args[0], sym)
    return v


def run_def(source):
    stmts = list(tokenize_text(source))
    sym = SymbolTable()
    DefPass(stmts, sym).run()
    return sym


def assemble(source):
    stmts = list(tokenize_text(source))
    sym = SymbolTable()
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
    assert v.kind == ValueKind.LIST, f"{name}: expected LIST, got {v.kind.name}"
    return v.items


# ---------------------------------------------------------------------------
# 1. Lexer: parenthesised list tokenisation
# ---------------------------------------------------------------------------

class TestLexerListTokens:
    def test_paren_single_no_comma_is_grouped(self):
        # (42) is a grouped sub-expression, not a list
        args = tok('(42)')
        assert len(args) == 1
        types = token_types(args[0])
        assert types == [TT.LPAREN, TT.INT, TT.RPAREN]
        assert TT.COMMA not in types

    def test_paren_two_elements(self):
        args = tok('(1,2)')
        assert len(args) == 1
        types = token_types(args[0])
        assert types == [TT.LPAREN, TT.INT, TT.COMMA, TT.INT, TT.RPAREN]

    def test_paren_three_elements(self):
        args = tok('(1,2,3)')
        assert len(args) == 1
        types = token_types(args[0])
        assert types == [TT.LPAREN, TT.INT, TT.COMMA,
                         TT.INT, TT.COMMA, TT.INT, TT.RPAREN]

    def test_outer_comma_still_splits_args(self):
        # (1,2),(3,4) → two args, each a parenthesised pair
        args = tok('(1,2),(3,4)')
        assert len(args) == 2
        assert token_types(args[0]) == [TT.LPAREN, TT.INT, TT.COMMA, TT.INT, TT.RPAREN]
        assert token_types(args[1]) == [TT.LPAREN, TT.INT, TT.COMMA, TT.INT, TT.RPAREN]

    def test_flat_comma_still_splits(self):
        # 1,2,3 at top level → 3 separate args (unchanged behaviour)
        args = tok('1,2,3')
        assert len(args) == 3
        assert args[0][0].type == TT.INT and args[0][0].value == 1
        assert args[1][0].type == TT.INT and args[1][0].value == 2
        assert args[2][0].type == TT.INT and args[2][0].value == 3

    def test_paren_with_expression_elements(self):
        args = tok('(A+1,B-2)')
        assert len(args) == 1
        types = token_types(args[0])
        assert TT.LPAREN in types
        assert TT.COMMA in types
        assert TT.RPAREN in types

    def test_paren_hex_elements(self):
        args = tok("(X'1A',X'2B')")
        assert len(args) == 1
        types = token_types(args[0])
        assert TT.COMMA in types

    def test_subscript_a_of_2_unchanged(self):
        # A(2) is SYMBOL subscript, not a paren list — still handled by
        # _parse_subscript_args, so no change
        args = tok('A(2)')
        assert len(args) == 1
        types = token_types(args[0])
        assert types == [TT.SYMBOL, TT.LPAREN, TT.INT, TT.RPAREN]

    def test_subscript_multi_index_unchanged(self):
        args = tok('A(1,2)')
        assert len(args) == 1
        types = token_types(args[0])
        assert types == [TT.SYMBOL, TT.LPAREN, TT.INT,
                         TT.COMMA, TT.INT, TT.RPAREN]


# ---------------------------------------------------------------------------
# 2. value.py: LIST kind
# ---------------------------------------------------------------------------

class TestListValue:
    def test_list_val_factory(self):
        v = Value.list_val([Value.absolute(1), Value.absolute(2)])
        assert v.kind == ValueKind.LIST
        assert len(v.items) == 2

    def test_list_val_items_are_values(self):
        v = Value.list_val([Value.absolute(10), Value.absolute(20)])
        assert v.items[0].int_val == 10
        assert v.items[1].int_val == 20

    def test_is_list_predicate(self):
        v = Value.list_val([Value.absolute(1)])
        assert v.is_list()
        assert not Value.absolute(1).is_list()
        assert not Value.blank().is_list()
        assert not Value.undefined().is_list()

    def test_list_not_integer(self):
        v = Value.list_val([Value.absolute(1)])
        assert not v.is_integer()

    def test_list_not_address(self):
        v = Value.list_val([Value.absolute(1)])
        assert not v.is_address()

    def test_empty_list(self):
        v = Value.list_val([])
        assert v.kind == ValueKind.LIST
        assert v.items == []

    def test_nested_list(self):
        inner = Value.list_val([Value.absolute(1), Value.absolute(2)])
        outer = Value.list_val([inner, Value.absolute(3)])
        assert outer.kind == ValueKind.LIST
        assert outer.items[0].kind == ValueKind.LIST
        assert outer.items[1].kind == ValueKind.ABSOLUTE

    def test_list_val_copies_items(self):
        items = [Value.absolute(1), Value.absolute(2)]
        v = Value.list_val(items)
        items.append(Value.absolute(3))   # mutate original
        assert len(v.items) == 2          # should not affect Value


# ---------------------------------------------------------------------------
# 3. expression.py: _subscript helper
# ---------------------------------------------------------------------------

class TestSubscriptHelper:
    """Unit tests for the _subscript() function — AP's exact rules."""

    def test_scalar_index_1_returns_scalar(self):
        # X(1) where X is scalar → the scalar itself
        scalar = Value.absolute(42)
        result = _subscript(scalar, [Value.absolute(1)])
        assert result.kind == ValueKind.ABSOLUTE
        assert result.int_val == 42

    def test_scalar_index_gt_1_returns_blank(self):
        # X(2) where X is scalar → BLANK
        scalar = Value.absolute(42)
        assert _subscript(scalar, [Value.absolute(2)]).kind == ValueKind.BLANK
        assert _subscript(scalar, [Value.absolute(99)]).kind == ValueKind.BLANK

    def test_scalar_two_indices_returns_blank(self):
        # X(1,1) where X is scalar → BLANK (more subscripts than depth)
        scalar = Value.absolute(42)
        result = _subscript(scalar, [Value.absolute(1), Value.absolute(1)])
        assert result.kind == ValueKind.BLANK

    def test_list_in_range(self):
        lst = Value.list_val([Value.absolute(10), Value.absolute(20), Value.absolute(30)])
        assert _subscript(lst, [Value.absolute(1)]).int_val == 10
        assert _subscript(lst, [Value.absolute(2)]).int_val == 20
        assert _subscript(lst, [Value.absolute(3)]).int_val == 30

    def test_list_out_of_range_returns_blank(self):
        lst = Value.list_val([Value.absolute(1), Value.absolute(2)])
        assert _subscript(lst, [Value.absolute(3)]).kind == ValueKind.BLANK
        assert _subscript(lst, [Value.absolute(0)]).kind == ValueKind.BLANK

    def test_list_index_0_returns_blank(self):
        lst = Value.list_val([Value.absolute(1)])
        assert _subscript(lst, [Value.absolute(0)]).kind == ValueKind.BLANK

    def test_nested_list_two_indices(self):
        # X = ((1,2),(3,4))  →  X(2,1) = 3
        inner1 = Value.list_val([Value.absolute(1), Value.absolute(2)])
        inner2 = Value.list_val([Value.absolute(3), Value.absolute(4)])
        outer  = Value.list_val([inner1, inner2])
        result = _subscript(outer, [Value.absolute(2), Value.absolute(1)])
        assert result.int_val == 3

    def test_nested_list_second_level_out_of_range(self):
        inner = Value.list_val([Value.absolute(1), Value.absolute(2)])
        outer = Value.list_val([inner])
        result = _subscript(outer, [Value.absolute(1), Value.absolute(5)])
        assert result.kind == ValueKind.BLANK

    def test_nested_list_first_level_out_of_range(self):
        inner = Value.list_val([Value.absolute(1)])
        outer = Value.list_val([inner])
        result = _subscript(outer, [Value.absolute(2), Value.absolute(1)])
        assert result.kind == ValueKind.BLANK

    def test_single_element_list(self):
        lst = Value.list_val([Value.absolute(99)])
        assert _subscript(lst, [Value.absolute(1)]).int_val == 99
        assert _subscript(lst, [Value.absolute(2)]).kind == ValueKind.BLANK


# ---------------------------------------------------------------------------
# 4. expression.py: list evaluation through the evaluator
# ---------------------------------------------------------------------------

class TestEvalListLiterals:
    def test_paren_list_two_elements(self):
        v = eval_expr('(1,2)')
        assert v.kind == ValueKind.LIST
        assert len(v.items) == 2
        assert v.items[0].int_val == 1
        assert v.items[1].int_val == 2

    def test_paren_list_three_elements(self):
        v = eval_expr('(10,20,30)')
        assert v.kind == ValueKind.LIST
        assert [i.int_val for i in v.items] == [10, 20, 30]

    def test_paren_single_is_scalar(self):
        # (42) is a grouped expression, not a list
        v = eval_expr('(42)')
        assert v.kind == ValueKind.ABSOLUTE
        assert v.int_val == 42

    def test_paren_list_with_expressions(self):
        sym = SymbolTable()
        sym.define('A', Value.absolute(5))
        v = eval_expr('(A+1,A*2)', sym)
        assert v.kind == ValueKind.LIST
        assert v.items[0].int_val == 6
        assert v.items[1].int_val == 10

    def test_paren_list_hex_values(self):
        v = eval_expr("(X'FF',X'00')")
        assert v.kind == ValueKind.LIST
        assert v.items[0].int_val == 0xFF
        assert v.items[1].int_val == 0x00

    def test_nested_paren_list(self):
        # ((1,2),(3,4)) — the outer is a single-element grouped expression
        # wrapping a list (because only one comma-free sub-expression)
        # Actually: outer ( has one item (1,2) and one item (3,4) separated
        # by COMMA at the outer level... wait, outer level splits args.
        # As a SINGLE arg: (1,2) is evaluated as a list, and that's the
        # whole arg. For nested: we'd write X EQU (1,2),(3,4) as TWO args.
        # Here we test a single arg that evaluates to a list:
        v = eval_expr('(7,8,9)')
        assert v.kind == ValueKind.LIST
        assert len(v.items) == 3


class TestEvalSubscript:
    def test_scalar_subscript_1(self):
        sym = SymbolTable()
        sym.define('X', Value.absolute(42))
        v = eval_expr('X(1)', sym)
        assert v.kind == ValueKind.ABSOLUTE
        assert v.int_val == 42

    def test_scalar_subscript_2_blank(self):
        sym = SymbolTable()
        sym.define('X', Value.absolute(42))
        v = eval_expr('X(2)', sym)
        assert v.kind == ValueKind.BLANK

    def test_list_subscript_in_range(self):
        sym = SymbolTable()
        sym.define('CODES', Value.list_val([
            Value.absolute(0x32),
            Value.absolute(0x35),
            Value.absolute(0x22),
        ]))
        assert eval_expr('CODES(1)', sym).int_val == 0x32
        assert eval_expr('CODES(2)', sym).int_val == 0x35
        assert eval_expr('CODES(3)', sym).int_val == 0x22

    def test_list_subscript_out_of_range(self):
        sym = SymbolTable()
        sym.define('LST', Value.list_val([Value.absolute(1), Value.absolute(2)]))
        assert eval_expr('LST(3)', sym).kind == ValueKind.BLANK
        assert eval_expr('LST(0)', sym).kind == ValueKind.BLANK

    def test_list_subscript_expression_index(self):
        sym = SymbolTable()
        sym.define('N', Value.absolute(2))
        sym.define('LST', Value.list_val([Value.absolute(10), Value.absolute(20)]))
        v = eval_expr('LST(N)', sym)
        assert v.int_val == 20

    def test_nested_list_two_indices(self):
        sym = SymbolTable()
        inner1 = Value.list_val([Value.absolute(1), Value.absolute(2)])
        inner2 = Value.list_val([Value.absolute(3), Value.absolute(4)])
        sym.define('M', Value.list_val([inner1, inner2]))
        assert eval_expr('M(1,1)', sym).int_val == 1
        assert eval_expr('M(1,2)', sym).int_val == 2
        assert eval_expr('M(2,1)', sym).int_val == 3
        assert eval_expr('M(2,2)', sym).int_val == 4

    def test_subscript_in_arithmetic(self):
        sym = SymbolTable()
        sym.define('LST', Value.list_val([Value.absolute(10), Value.absolute(20)]))
        v = eval_expr('LST(1)+LST(2)', sym)
        assert v.int_val == 30

    def test_undefined_symbol_subscript(self):
        sym = SymbolTable()
        v = eval_expr('UNKNOWN(1)', sym)
        assert v.kind == ValueKind.UNDEFINED


# ---------------------------------------------------------------------------
# 5. def_pass.py: EQU/SET build list symbols
# ---------------------------------------------------------------------------

class TestDefPassLists:
    def test_equ_single_arg_scalar(self):
        sym = run_def("A  EQU  42\n")
        v = sym_val(sym, 'A')
        assert v.kind == ValueKind.ABSOLUTE
        assert v.int_val == 42

    def test_equ_two_args_makes_list(self):
        sym = run_def("L  EQU  1,2\n")
        items = sym_list(sym, 'L')
        assert len(items) == 2
        assert items[0].int_val == 1
        assert items[1].int_val == 2

    def test_equ_three_args_makes_list(self):
        sym = run_def("CODES  EQU  X'32',X'35',X'22'\n")
        items = sym_list(sym, 'CODES')
        assert len(items) == 3
        assert items[0].int_val == 0x32
        assert items[1].int_val == 0x35
        assert items[2].int_val == 0x22

    def test_set_two_args_makes_list(self):
        sym = run_def("S  SET  10,20\n")
        assert sym_val(sym, 'S').kind == ValueKind.LIST

    def test_set_redefinable_list(self):
        sym = run_def("S  SET  1,2\nS  SET  3,4,5\n")
        items = sym_list(sym, 'S')
        assert len(items) == 3
        assert items[0].int_val == 3

    def test_equ_paren_list_literal(self):
        # Single arg that is a parenthesised list literal
        sym = run_def("L  EQU  (10,20,30)\n")
        items = sym_list(sym, 'L')
        assert [i.int_val for i in items] == [10, 20, 30]

    def test_equ_nested_paren_lists(self):
        # Two args each being a paren list → outer list of two lists
        sym = run_def("M  EQU  (1,2),(3,4)\n")
        items = sym_list(sym, 'M')
        assert len(items) == 2
        assert items[0].kind == ValueKind.LIST
        assert items[1].kind == ValueKind.LIST
        assert [i.int_val for i in items[0].items] == [1, 2]
        assert [i.int_val for i in items[1].items] == [3, 4]

    def test_list_subscript_in_equ(self):
        # Use a list element in another EQU
        sym = run_def("LST  EQU  X'AA',X'BB',X'CC'\nV  EQU  LST(2)\n")
        assert sym_val(sym, 'V').int_val == 0xBB

    def test_list_subscript_in_set(self):
        sym = run_def("LST  EQU  10,20,30\nN  SET  2\nV  EQU  LST(N)\n")
        assert sym_val(sym, 'V').int_val == 20

    def test_set_list_do_loop_iteration(self):
        # Classic AP pattern: SET counter iterates through a list
        src = """\
CODES  EQU  X'AA',X'BB',X'CC'
I      SET  0
       DO   3
I      SET  I+1
       FIN
"""
        sym = run_def(src)
        # After the loop I should be 3
        assert sym_val(sym, 'I').int_val == 3
        # CODES should still be a 3-element list
        assert len(sym_list(sym, 'CODES')) == 3

    def test_list_element_out_of_range_is_blank(self):
        # CODES(5) where CODES has 3 elements → BLANK
        sym = run_def("CODES  EQU  1,2,3\nV  EQU  CODES(5)\n")
        v = sym_val(sym, 'V')
        assert v.kind == ValueKind.BLANK

    def test_scalar_subscript_1_returns_value(self):
        sym = run_def("SYM  EQU  42\nV  EQU  SYM(1)\n")
        assert sym_val(sym, 'V').int_val == 42

    def test_scalar_subscript_2_returns_blank(self):
        sym = run_def("SYM  EQU  42\nV  EQU  SYM(2)\n")
        assert sym_val(sym, 'V').kind == ValueKind.BLANK


# ---------------------------------------------------------------------------
# 6. gen_pass.py: byte emission using list subscripts
# ---------------------------------------------------------------------------

class TestGenPassLists:
    def test_data_list_element(self):
        # DATA CODES(2) emits the second element
        src = "CODES  EQU  X'AA',X'BB',X'CC'\n  DATA  CODES(2)\n"
        _, obj, _ = assemble(src)
        raw = sec_bytes(obj)
        assert raw == b'\x00\x00\x00\xBB'

    def test_data_all_list_elements_by_subscript(self):
        src = """\
BYT  EQU  X'11',X'22',X'33'
    DATA  BYT(1),BYT(2),BYT(3)
"""
        _, obj, _ = assemble(src)
        raw = sec_bytes(obj)
        assert raw == b'\x00\x00\x00\x11' + b'\x00\x00\x00\x22' + b'\x00\x00\x00\x33'

    def test_do_loop_emitting_list_elements(self):
        # Classic use: iterate over a list with a SET counter
        src = """\
BYTES  EQU  X'AA',X'BB',X'CC'
I      SET  0
       DO   3
I      SET  I+1
       DATA,8  BYTES(I)
       FIN
"""
        _, obj, _ = assemble(src)
        assert sec_bytes(obj) == b'\xAA\xBB\xCC'

    def test_do_loop_len_from_list(self):
        # DO loop runs exactly as many times as there are list elements
        # Here we hard-code 3 to match; later NUM() would give the count
        src = """\
SZ    EQU  3
VALS  EQU  10,20,30
I     SET  0
      DO   SZ
I     SET  I+1
      DATA  VALS(I)
      FIN
"""
        _, obj, _ = assemble(src)
        raw = sec_bytes(obj)
        assert raw == (
            b'\x00\x00\x00\x0A' +
            b'\x00\x00\x00\x14' +
            b'\x00\x00\x00\x1E'
        )

    def test_nested_list_subscript_in_data(self):
        # 2D list: M(1,2) = second element of first sub-list
        src = "M  EQU  (1,2),(3,4)\n  DATA  M(1,2)\n"
        _, obj, _ = assemble(src)
        assert sec_bytes(obj) == b'\x00\x00\x00\x02'

    def test_out_of_range_subscript_emits_zero(self):
        # BLANK used in DATA: value.py blank() has int_val=0
        src = "L  EQU  1,2\n  DATA  L(5)\n"
        _, obj, _ = assemble(src)
        assert sec_bytes(obj) == b'\x00\x00\x00\x00'

    def test_equ_list_listing_shows_first_element(self):
        _, _, lst = assemble("L  EQU  X'DEADBEEF',X'12345678'\n")
        line = next(ll for ll in lst._lines if 'EQU' in ll.source)
        # Listing should show first element in hex column
        assert line.hex_val == 'DEADBEEF'

    def test_equ_scalar_listing_unchanged(self):
        _, _, lst = assemble("K  EQU  X'CAFEBABE'\n")
        line = next(ll for ll in lst._lines if 'EQU' in ll.source)
        assert line.hex_val == 'CAFEBABE'

    def test_two_pass_lc_consistent_with_list_subscript(self):
        # DEF and GEN passes should agree on LC
        src = """\
SIZES  EQU  4,8,4
I      SET  0
       DO   3
I      SET  I+1
       RES,1  SIZES(I)
       FIN
"""
        stmts = list(tokenize_text(src))
        sym = SymbolTable()
        DefPass(stmts, sym).run()
        def_lc = sym.exec_lc()

        sym2 = SymbolTable()
        DefPass(stmts, sym2).run()
        obj = ObjectWriter()
        lst = ListingWriter()
        GenPass(stmts, sym2, obj, lst).run()
        gen_lc = sym2.exec_lc()

        assert def_lc == gen_lc
        assert def_lc == 4 + 8 + 4   # 16 bytes total


# ---------------------------------------------------------------------------
# 7. Round-trip from testtese.txt patterns
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_com1_pattern(self):
        # testtese.txt line: COM1 COM,8,8  35,X'3C'
        # COM1 with no intrinsics just packs two constants into 16 bits
        # Our COM handler is stubbed to 0 — this tests that the LIST symbol
        # itself round-trips correctly
        src = "CODES  EQU  35,X'3C'\n  DATA  CODES(1),CODES(2)\n"
        _, obj, _ = assemble(src)
        raw = sec_bytes(obj)
        assert raw == b'\x00\x00\x00\x23' + b'\x00\x00\x00\x3C'

    def test_set_increment_pattern(self):
        # I SET 0 then I SET I+1 inside a loop — classic AP counter
        src = """\
I   SET  0
    DO   5
I   SET  I+1
    FIN
"""
        sym = run_def(src)
        assert sym.lookup('I').value.int_val == 5

    def test_equ_with_symbol_elements(self):
        src = """\
A   EQU  5
B   EQU  6
SUM EQU  A,B,A+B
    DATA  SUM(1),SUM(2),SUM(3)
"""
        _, obj, _ = assemble(src)
        raw = sec_bytes(obj)
        assert raw == (b'\x00\x00\x00\x05' +
                       b'\x00\x00\x00\x06' +
                       b'\x00\x00\x00\x0B')

    def test_list_and_scalar_mixed(self):
        # Using a list symbol alongside scalars
        src = """\
OFFSETS  EQU  0,4,8,12
BASE     EQU  X'100'
         DATA  BASE+OFFSETS(3)
"""
        _, obj, _ = assemble(src)
        # BASE + OFFSETS(3) = 0x100 + 8 = 0x108
        assert sec_bytes(obj) == b'\x00\x00\x01\x08'

    def test_do_over_list_building_table(self):
        # Build a table of squares: 1,4,9,16
        src = """\
I      SET  0
       DO   4
I      SET  I+1
       DATA  I*I
       FIN
"""
        _, obj, _ = assemble(src)
        raw = sec_bytes(obj)
        assert raw == (b'\x00\x00\x00\x01' +
                       b'\x00\x00\x00\x04' +
                       b'\x00\x00\x00\x09' +
                       b'\x00\x00\x00\x10')

    def test_paren_list_equ_then_subscript(self):
        src = "PAIR  EQU  (X'AA',X'BB')\n  DATA  PAIR(1),PAIR(2)\n"
        _, obj, _ = assemble(src)
        raw = sec_bytes(obj)
        assert raw == b'\x00\x00\x00\xAA' + b'\x00\x00\x00\xBB'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
