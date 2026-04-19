"""
tests/test_def_pass.py — Tests for the Phase 2 DEF pass.

Exercises directive handlers, location counter management, DO/FIN flow
control, external linkage declarations, and end-to-end parsing of
representative snippets from testtese.txt.

Run with:  python -m pytest tests/test_def_pass.py -v
"""

import pytest
from ap_assembler.def_pass import DefPass
from ap_assembler.do_control import find_else_fin, find_pend, find_label
from ap_assembler.lexer import tokenize_text, Statement
from ap_assembler.symbol_table import SymbolTable, CsectKind, PASS_DEF
from ap_assembler.value import Value, ValueKind, Resolution


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(source: str) -> SymbolTable:
    """Tokenise *source*, run the DEF pass, and return the SymbolTable."""
    stmts = list(tokenize_text(source))
    sym   = SymbolTable()
    DefPass(stmts, sym).run()
    return sym


def run_with_errors(source: str):
    """Run and return (sym, errors)."""
    stmts  = list(tokenize_text(source))
    sym    = SymbolTable()
    dp     = DefPass(stmts, sym)
    errors = dp.run()
    return sym, errors


def val(sym: SymbolTable, name: str) -> Value:
    """Retrieve the value of a symbol (assertion-friendly)."""
    e = sym.lookup(name)
    assert e is not None, f"Symbol {name!r} not found"
    return e.value


def ival(sym: SymbolTable, name: str) -> int:
    """Integer value of an absolute symbol."""
    v = val(sym, name)
    assert v.kind == ValueKind.ABSOLUTE, \
        f"{name}: expected ABSOLUTE, got {v.kind.name}"
    return v.int_val


def lc(sym: SymbolTable, name: str) -> int:
    """Byte offset of a relocatable symbol."""
    v = val(sym, name)
    assert v.kind == ValueKind.RELOCATABLE, \
        f"{name}: expected RELOCATABLE, got {v.kind.name}"
    return v.int_val


# ---------------------------------------------------------------------------
# 1. EQU / SET
# ---------------------------------------------------------------------------

class TestEquSet:
    def test_equ_integer(self):
        sym = run("A1  EQU  5\n")
        assert ival(sym, 'A1') == 5

    def test_equ_hex(self):
        sym = run("F1  EQU  X'FF'\n")
        assert ival(sym, 'F1') == 255

    def test_equ_expression(self):
        sym = run("A   EQU  3+4\n")
        assert ival(sym, 'A') == 7

    def test_equ_chain(self):
        sym = run("A  EQU  5\nB  EQU  A+1\n")
        assert ival(sym, 'B') == 6

    def test_set_redefinable(self):
        sym = run("X  SET  1\nX  SET  2\n")
        assert ival(sym, 'X') == 2

    def test_set_in_context(self):
        sym = run("I  SET  0\nI  SET  I+1\nI  SET  I+1\n")
        assert ival(sym, 'I') == 2

    def test_equ_negative(self):
        sym = run("N  EQU  -185\n")
        assert ival(sym, 'N') == -185

    def test_equ_scale(self):
        # 1**128 in 32-bit wraps: 1 << 128 truncated to 32 bits = 0
        sym = run("M  EQU  1**7\n")
        assert ival(sym, 'M') == 128

    def test_equ_bitwise(self):
        sym = run("M  EQU  X'F0'&X'FF'\n")
        assert ival(sym, 'M') == 0xF0

    def test_equ_comparison(self):
        sym = run("T  EQU  5=5\n")
        assert ival(sym, 'T') == -1   # AP: true = -1

    def test_set_no_label_no_error(self):
        # SET without a label is legal (just evaluates the expression)
        _, errors = run_with_errors("     SET  42\n")
        assert len(errors) == 0


# ---------------------------------------------------------------------------
# 2. RES
# ---------------------------------------------------------------------------

class TestRes:
    def test_res_default_unit(self):
        # RES 2 → 2 words = 8 bytes
        sym = run("A  RES  2\n")
        assert lc(sym, 'A') == 0
        assert sym.exec_lc() == 8

    def test_res_byte_unit(self):
        # RES,1 80 → 80 bytes
        sym = run("B  RES,1  80\n")
        assert lc(sym, 'B') == 0
        assert sym.exec_lc() == 80

    def test_res_halfword_unit(self):
        # RES,2 4 → 8 bytes
        sym = run("C  RES,2  4\n")
        assert sym.exec_lc() == 8

    def test_res_doubleword_unit(self):
        # RES,8 2 → 16 bytes
        sym = run("D  RES,8  2\n")
        assert sym.exec_lc() == 16

    def test_res_zero(self):
        sym = run("E  RES  0\n")
        assert lc(sym, 'E') == 0
        assert sym.exec_lc() == 0

    def test_res_sequential(self):
        # Two RES directives: second label should be at first's end
        sym = run("A  RES  2\nB  RES  3\n")
        assert lc(sym, 'A') == 0
        assert lc(sym, 'B') == 8     # 2 words = 8 bytes
        assert sym.exec_lc() == 20   # 8 + 3*4 = 20

    def test_res_expression_count(self):
        sym = run("N  EQU  3\nA  RES  N+1\n")
        assert sym.exec_lc() == 16   # 4 words = 16 bytes


# ---------------------------------------------------------------------------
# 3. DATA
# ---------------------------------------------------------------------------

class TestData:
    def test_data_default(self):
        # DATA 42 → 4 bytes (32 bits default)
        sym = run("A  DATA  42\n")
        assert lc(sym, 'A') == 0
        assert sym.exec_lc() == 4

    def test_data_multi_arg(self):
        # DATA 1,2,3 → 3 × 4 = 12 bytes
        sym = run("A  DATA  1,2,3\n")
        assert sym.exec_lc() == 12

    def test_data_8bit(self):
        # DATA,8 X'FF' → 1 byte
        sym = run("A  DATA,8  X'FF'\n")
        assert sym.exec_lc() == 1

    def test_data_16bit(self):
        # DATA,16 → 2 bytes per arg
        sym = run("A  DATA,16  1,2,3\n")
        assert sym.exec_lc() == 6

    def test_data_hex(self):
        sym = run("A  DATA  X'12345678'\n")
        assert lc(sym, 'A') == 0
        assert sym.exec_lc() == 4

    def test_data_label_at_start(self):
        sym = run("     DATA  1\nB    DATA  2\n")
        assert lc(sym, 'B') == 4


# ---------------------------------------------------------------------------
# 4. TEXT / TEXTC
# ---------------------------------------------------------------------------

class TestText:
    def test_text_4_chars(self):
        # 'ABCD' → exactly 4 bytes (one word)
        sym = run("T  TEXT  'ABCD'\n")
        assert sym.exec_lc() == 4

    def test_text_5_chars(self):
        # 5 chars → rounded to 8 bytes (2 words)
        sym = run("T  TEXT  'ABCDE'\n")
        assert sym.exec_lc() == 8

    def test_text_1_char(self):
        # 1 char → rounded to 4 bytes
        sym = run("T  TEXT  'A'\n")
        assert sym.exec_lc() == 4

    def test_textc_4_chars(self):
        # TEXTC 'ABCD' → 1 count byte + 4 chars = 5 bytes → rounded to 8
        sym = run("T  TEXTC  'ABCD'\n")
        assert sym.exec_lc() == 8

    def test_textc_3_chars(self):
        # TEXTC 'ABC' → 1 + 3 = 4 → 4 bytes
        sym = run("T  TEXTC  'ABC'\n")
        assert sym.exec_lc() == 4

    def test_text_label(self):
        sym = run("MSG  TEXT  'HELLO'\n")
        assert lc(sym, 'MSG') == 0


# ---------------------------------------------------------------------------
# 5. BOUND
# ---------------------------------------------------------------------------

class TestBound:
    def test_bound_already_aligned(self):
        sym = run("     RES  2\n     BOUND  4\n")
        # 2 words = 8 bytes → already on 4-byte boundary
        assert sym.exec_lc() == 8

    def test_bound_needs_padding(self):
        # Advance to 5 bytes, then BOUND 4 → pads to 8
        sym = run("     RES,1  5\n     BOUND  4\n")
        assert sym.exec_lc() == 8

    def test_bound_8(self):
        sym = run("     RES,1  3\n     BOUND  8\n")
        assert sym.exec_lc() == 8

    def test_bound_label(self):
        # BOUND with a label: label defined at the *after-alignment* LC
        # But BOUND doesn't define a label — the original uses DEFHEXLBL
        # which is called *before* alignment. Align first, then label.
        # Actually in AP, BOUND has no label field. Let's just check LC.
        sym = run("     RES,1  3\n     BOUND  4\nA    RES  0\n")
        assert lc(sym, 'A') == 4


# ---------------------------------------------------------------------------
# 6. ORG / LOC
# ---------------------------------------------------------------------------

class TestOrgLoc:
    def test_org_absolute(self):
        sym = run("     ORG  100\n")
        assert sym.exec_lc() == 100

    def test_org_to_zero(self):
        sym = run("     RES  5\n     ORG  0\n")
        assert sym.exec_lc() == 0

    def test_org_label_defined_after(self):
        # After ORG, next label should be at the new LC
        sym = run("     ORG  100\nA    RES  0\n")
        assert lc(sym, 'A') == 100

    def test_loc_only_exec(self):
        # LOC sets exec LC only; load LC should remain at advance position
        sym = run("     RES  4\n     LOC  0\n")
        # exec_lc is reset to 0; load_lc is unchanged at 16
        assert sym.exec_lc() == 0
        assert sym.current_section.load_lc == 16


# ---------------------------------------------------------------------------
# 7. Section directives
# ---------------------------------------------------------------------------

class TestSections:
    def test_csect_new(self):
        sym = run("CODE  CSECT\n")
        assert sym.lookup('CODE') is not None
        assert sym.current_section.kind == CsectKind.CSECT

    def test_csect_reenter(self):
        src = "CODE  CSECT\n      RES   2\nDATA  CSECT\n      RES   1\nCODE  USECT CODE\n"
        sym = run(src)
        # After re-entering CODE, LC should resume at 8 (2 words)
        assert sym.exec_lc() == 8

    def test_asect_switches_to_zero(self):
        sym = run("      ASECT\n")
        assert sym.current_section.number == 0

    def test_dsect_defines_label(self):
        sym = run("MYDS  DSECT\n")
        e = sym.lookup('MYDS')
        assert e is not None
        assert e.is_def

    def test_multiple_sections(self):
        src = "CODE  CSECT\n      RES   3\nDATA  CSECT\n      RES   5\n"
        sym = run(src)
        # DATA section: 5 words = 20 bytes
        assert sym.exec_lc() == 20
        code_cs = sym.get_section(2)   # CODE was section 2
        assert code_cs.exec_lc == 12   # 3 words

    def test_psect(self):
        sym = run("PS  PSECT\n")
        assert sym.current_section.kind == CsectKind.PSECT


# ---------------------------------------------------------------------------
# 8. External linkage
# ---------------------------------------------------------------------------

class TestExternalLinkage:
    def test_def(self):
        sym = run("      DEF  MYFUNC\n")
        assert sym.lookup('MYFUNC').is_def

    def test_ref(self):
        sym = run("      REF  M:LO\n")
        e = sym.lookup('M:LO')
        assert e is not None and e.is_ref

    def test_sref(self):
        sym = run("      SREF  MYMOD\n")
        assert sym.lookup('MYMOD').is_ref

    def test_multi_def(self):
        sym = run("      DEF  A,B,C\n")
        for name in ('A', 'B', 'C'):
            assert sym.lookup(name).is_def

    def test_ref_creates_external_value(self):
        sym = run("      REF  M:LO\n")
        v = val(sym, 'M:LO')
        assert v.kind == ValueKind.EXTERNAL

    def test_def_then_define(self):
        sym = run("START  EQU  0\n       DEF  START\n")
        assert sym.lookup('START').is_def


# ---------------------------------------------------------------------------
# 9. DO / ELSE / FIN flow control
# ---------------------------------------------------------------------------

class TestDo:
    def test_do_positive_repeats(self):
        # DO 3: body executes 3 times; each iteration reserves 1 word
        src = "     DO   3\n     RES  1\n     FIN\n"
        sym = run(src)
        assert sym.exec_lc() == 12   # 3 × 4 bytes

    def test_do_one(self):
        # DO 1: body executes once
        src = "     DO   1\n     RES  1\n     FIN\n"
        sym = run(src)
        assert sym.exec_lc() == 4

    def test_do_zero_skips_body(self):
        # DO 0: body is skipped
        src = "     DO   0\n     RES  1\n     FIN\n"
        sym = run(src)
        assert sym.exec_lc() == 0

    def test_do_negative_skips_body(self):
        src = "     DO   -1\n     RES  1\n     FIN\n"
        sym = run(src)
        assert sym.exec_lc() == 0

    def test_do_else_positive(self):
        # DO 2 ... ELSE ... FIN: body runs twice; ELSE section skipped
        src = "     DO   2\n     RES  1\n     ELSE\n     RES  5\n     FIN\n"
        sym = run(src)
        # 2 × 4 = 8 bytes (ELSE section skipped)
        assert sym.exec_lc() == 8

    def test_do_else_zero(self):
        # DO 0 ... ELSE ... FIN: body skipped; ELSE section runs once
        src = "     DO   0\n     RES  1\n     ELSE\n     RES  2\n     FIN\n"
        sym = run(src)
        # 2 × 4 = 8 bytes (only ELSE section runs)
        assert sym.exec_lc() == 8

    def test_do_label_set(self):
        # The DO label is set to the iteration count
        src = "I    DO   3\n     FIN\n"
        sym = run(src)
        # After the loop, I should be 3 (last iteration)
        assert ival(sym, 'I') == 3

    def test_do_label_zero_on_skip(self):
        src = "I    DO   0\n     RES  1\n     FIN\n"
        sym = run(src)
        assert ival(sym, 'I') == 0

    def test_do_nested(self):
        # Outer DO 2, inner DO 3: total 2×3 = 6 iterations of RES 1
        src = "     DO   2\n     DO   3\n     RES  1\n     FIN\n     FIN\n"
        sym = run(src)
        assert sym.exec_lc() == 24   # 6 × 4 bytes

    def test_do_with_expression(self):
        src = "N    EQU   4\n     DO   N\n     RES  1\n     FIN\n"
        sym = run(src)
        assert sym.exec_lc() == 16   # 4 × 4

    def test_do_body_with_equ(self):
        # EQU inside DO: each iteration overrides the previous value
        # (SET behaviour from SETLABEL)
        src = "N  SET  0\n   DO  3\nN  SET  N+1\n   FIN\n"
        sym = run(src)
        assert ival(sym, 'N') == 3


# ---------------------------------------------------------------------------
# 10. DO1
# ---------------------------------------------------------------------------

class TestDo1:
    def test_do1_one(self):
        # DO1 1: execute next statement once (normal)
        sym = run("     DO1  1\n     RES  1\n")
        assert sym.exec_lc() == 4

    def test_do1_zero_skips(self):
        # DO1 0: skip the next statement
        sym = run("     DO1  0\n     RES  3\n")
        assert sym.exec_lc() == 0

    def test_do1_three_repeats(self):
        # DO1 3: next statement runs 3 times
        sym = run("     DO1  3\n     RES  1\n")
        assert sym.exec_lc() == 12   # 3 × 4

    def test_do1_label_defined(self):
        # DO1 with a label: label is defined at current LC
        sym = run("L    DO1  2\n     RES  1\n")
        assert lc(sym, 'L') == 0


# ---------------------------------------------------------------------------
# 11. GOTO
# ---------------------------------------------------------------------------

class TestGoto:
    def test_goto_simple(self):
        # GOTO jumps to a label; statements between are skipped
        src = "     GOTO  TARGET\n     RES   5\nTARGET  RES  1\n"
        sym = run(src)
        # RES 5 is skipped; only TARGET's RES 1 runs
        assert sym.exec_lc() == 4

    def test_goto_with_k(self):
        # GOTO,2 L1,L2 → jump to L2
        src = (
            "N    EQU   2\n"
            "     GOTO,N  L1,L2\n"
            "L1   RES   5\n"
            "L2   RES   1\n"
        )
        sym = run(src)
        assert sym.exec_lc() == 4   # only L2's RES runs


# ---------------------------------------------------------------------------
# 12. Procedure stubs
# ---------------------------------------------------------------------------

class TestProcStubs:
    def test_proc_body_skipped(self):
        # PROC body should not allocate storage
        src = "MYFUNC  CNAME\n        PROC\n        RES  100\n        PEND\n"
        sym = run(src)
        assert sym.exec_lc() == 0   # RES inside PROC is skipped

    def test_cname_defines_label(self):
        src = "F  CNAME\n   PROC\n   PEND\n"
        sym = run(src)
        assert sym.lookup('F') is not None

    def test_proc_after_proc_not_nested(self):
        # Two consecutive procedures should both be processed
        src = (
            "P1  CNAME\n    PROC\n    RES  1\n    PEND\n"
            "P2  CNAME\n    PROC\n    RES  2\n    PEND\n"
            "    RES  3\n"
        )
        sym = run(src)
        # Only the final RES 3 = 12 bytes should be allocated
        assert sym.exec_lc() == 12


# ---------------------------------------------------------------------------
# 13. LOCAL / DEF / REF in combination
# ---------------------------------------------------------------------------

class TestScopeAndExternal:
    def test_local_then_global(self):
        src = "     LOCAL  TMP\nTMP  EQU  42\n"
        sym = run(src)
        # TMP may be a local; its value should be 42
        e = sym.lookup('TMP')
        assert e is not None

    def test_ref_and_use(self):
        sym = run("     REF  M:LO\nA    EQU  0\n")
        assert sym.lookup('M:LO').is_ref

    def test_def_after_define(self):
        # A symbol can be defined and then declared DEF
        sym = run("ENTRY  EQU  100\n       DEF  ENTRY\n")
        assert ival(sym, 'ENTRY') == 100
        assert sym.lookup('ENTRY').is_def


# ---------------------------------------------------------------------------
# 14. End directive
# ---------------------------------------------------------------------------

class TestEnd:
    def test_end_stops_processing(self):
        # Statements after END should not be processed
        sym = run("A  EQU  1\n   END\nB  EQU  2\n")
        assert sym.lookup('A') is not None
        assert sym.lookup('B') is None   # not processed

    def test_end_with_start_addr(self):
        sym = run("START  EQU  0\n       END  START\n")
        assert sym.lookup('START') is not None

    def test_end_unclosed_do_error(self):
        _, errors = run_with_errors("  DO  3\n  RES  1\n  END\n")
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# 15. Full round-trip from testtese.txt
# ---------------------------------------------------------------------------

class TestRoundTrip:
    SNIPPET = """\
*  From testtese.txt — representative directives
         REF      M:LO
A1       EQU      5
A2       EQU      6
R1       DATA     1
R2       DATA     2
R3       DATA     3
         DATA     R1+A1,R1-A1
         DATA     A1+A2,A1-A2
NDOI     EQU      2
         DO1      NDOI+3
         RES      1
         BOUND    4
TEXT1    TEXT     'VALUE OF X'
TEXT2    TEXTC    'VALUE OF X'
         RES,1    2
         RES,5    2
         END
"""

    def test_parses_without_error(self):
        _, errors = run_with_errors(self.SNIPPET)
        assert len(errors) == 0

    def test_equ_values(self):
        sym = run(self.SNIPPET)
        assert ival(sym, 'A1') == 5
        assert ival(sym, 'A2') == 6
        assert ival(sym, 'NDOI') == 2

    def test_ref_marked(self):
        sym = run(self.SNIPPET)
        assert sym.lookup('M:LO').is_ref

    def test_data_advances_lc(self):
        sym = run(self.SNIPPET)
        # R1 at 0, R2 at 4, R3 at 8
        assert lc(sym, 'R1') == 0
        assert lc(sym, 'R2') == 4
        assert lc(sym, 'R3') == 8

    def test_do1_repeats(self):
        # DO1 NDOI+3 = DO1 5: next line (RES 1 = 4 bytes) repeats 5 times
        # Then BOUND 4 (already aligned after 20 bytes)
        # Then TEXT1 (10 chars → 12 bytes), TEXT2 (10+1=11 → 12 bytes)
        # Then RES,1 2 = 2 bytes, RES,5 2 = 10 bytes
        sym = run(self.SNIPPET)
        # Spot check: TEXT1 should be defined somewhere after the RES×5 block
        text1 = lc(sym, 'TEXT1')
        assert text1 > 0

    def test_text_sizes(self):
        sym = run(self.SNIPPET)
        t1 = lc(sym, 'TEXT1')
        t2 = lc(sym, 'TEXT2')
        # 'VALUE OF X' is 10 chars → TEXT rounds to 12 bytes
        assert t2 - t1 == 12


# ---------------------------------------------------------------------------
# 16. do_control helpers
# ---------------------------------------------------------------------------

class TestDoControlHelpers:
    def _make_stmts(self, source: str):
        return list(tokenize_text(source))

    def test_find_else_fin_no_else(self):
        stmts = self._make_stmts("  DO  1\n  RES  1\n  FIN\n")
        non_comment = [s for s in stmts if not s.is_comment]
        # DO is at index 0, body at 1, FIN at 2
        else_idx, fin_idx = find_else_fin(non_comment, 1)
        assert else_idx == -1
        assert non_comment[fin_idx].command == 'FIN'

    def test_find_else_fin_with_else(self):
        stmts = self._make_stmts("  DO  1\n  RES  1\n  ELSE\n  RES  2\n  FIN\n")
        non_comment = [s for s in stmts if not s.is_comment]
        else_idx, fin_idx = find_else_fin(non_comment, 1)
        assert non_comment[else_idx].command == 'ELSE'
        assert non_comment[fin_idx].command == 'FIN'

    def test_find_else_fin_nested(self):
        src = "  DO 1\n  DO 1\n  FIN\n  FIN\n"
        stmts = self._make_stmts(src)
        non_comment = [s for s in stmts if not s.is_comment]
        else_idx, fin_idx = find_else_fin(non_comment, 1)
        # The outer FIN is the last one
        assert non_comment[fin_idx].command == 'FIN'
        assert fin_idx == 3

    def test_find_pend(self):
        stmts = self._make_stmts("F  CNAME\n  PROC\n  RES 1\n  PEND\n")
        non_comment = [s for s in stmts if not s.is_comment]
        idx = find_pend(non_comment, 1)
        assert non_comment[idx].command == 'PEND'

    def test_find_label(self):
        stmts = self._make_stmts("A  EQU  1\nB  EQU  2\nC  EQU  3\n")
        non_comment = [s for s in stmts if not s.is_comment]
        idx = find_label(non_comment, 'B')
        assert non_comment[idx].label == 'B'

    def test_find_label_not_found(self):
        stmts = self._make_stmts("A  EQU  1\n")
        non_comment = [s for s in stmts if not s.is_comment]
        assert find_label(non_comment, 'Z') == -1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
