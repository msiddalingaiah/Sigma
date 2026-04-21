"""
tests/test_procedure.py — Tests for the AP procedure engine.

Covers:
  1. CNAME definition and storage (ProcedureBody)
  2. Argument access: AF(n), CF(n), LF, NAME
  3. Intrinsics: NUM(AF), S:S, SCOR, META, P#
  4. Procedure call mechanics (body runs, PEND pops frame)
  5. Nested CNAME calls
  6. DO loops inside procedure bodies
  7. LF label substitution at call site
  8. GenPass byte emission through procedures
  9. Two-pass LC consistency

Run with:  python -m pytest tests/test_procedure.py -v
"""

import pytest
from ap_assembler.lexer import tokenize_text
from ap_assembler.symbol_table import SymbolTable
from ap_assembler.def_pass import DefPass
from ap_assembler.gen_pass import GenPass
from ap_assembler.object_writer import ObjectWriter
from ap_assembler.listing_writer import ListingWriter
from ap_assembler.procedure import ProcedureBody, CallFrame
from ap_assembler.value import Value, ValueKind


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_def(source):
    stmts = list(tokenize_text(source))
    sym = SymbolTable()
    DefPass(stmts, sym).run()
    return sym, stmts


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
    return e.value if e else None


# ---------------------------------------------------------------------------
# 1. CNAME definition: ProcedureBody stored correctly
# ---------------------------------------------------------------------------

class TestCnameDefinition:
    def test_cname_stores_proc_body(self):
        sym, _ = run_def("""\
EMIT     CNAME    0
         PROC
LF       DATA,8   AF(1)
         PEND
""")
        e = sym.lookup('EMIT')
        assert e is not None
        assert e.proc_body is not None
        assert isinstance(e.proc_body, ProcedureBody)

    def test_cname_stores_name_value(self):
        sym, _ = run_def("""\
OP       CNAME    X'3C'
         PROC
         PEND
""")
        e = sym.lookup('OP')
        assert e.proc_body.name_value.int_val == 0x3C

    def test_fname_is_fname_flag(self):
        sym, _ = run_def("""\
DBL      FNAME    0
         PROC
         PEND     AF(1)*2
""")
        e = sym.lookup('DBL')
        assert e.proc_body is not None
        assert e.proc_body.is_fname is True

    def test_cname_is_not_fname(self):
        sym, _ = run_def("""\
EMIT     CNAME    0
         PROC
         PEND
""")
        e = sym.lookup('EMIT')
        assert e.proc_body.is_fname is False

    def test_cname_body_indices(self):
        # body_start should point to the line after PROC
        # pend_index should point to PEND
        sym, stmts = run_def("""\
EMIT     CNAME    0
         PROC
LF       DATA,8   AF(1)
         PEND
""")
        body = sym.lookup('EMIT').proc_body
        assert stmts[body.body_start].command.startswith('DATA')
        assert stmts[body.pend_index].command == 'PEND'

    def test_two_cnames_independent(self):
        sym, _ = run_def("""\
A        CNAME    1
         PROC
         PEND
B        CNAME    2
         PROC
         PEND
""")
        assert sym.lookup('A').proc_body.name_value.int_val == 1
        assert sym.lookup('B').proc_body.name_value.int_val == 2

    def test_cname_without_proc_is_forward_decl(self):
        # CNAME without immediately following PROC = forward declaration
        sym, _ = run_def("FORWARD  CNAME    0\n")
        e = sym.lookup('FORWARD')
        assert e is not None
        # No body stored — just a zero placeholder
        assert e.proc_body is None


# ---------------------------------------------------------------------------
# 2. AF argument access
# ---------------------------------------------------------------------------

class TestAFAccess:
    def test_af1_single_arg(self):
        _, obj, _ = assemble("""\
EMIT     CNAME    0
         PROC
LF       DATA,8   AF(1)
         PEND
         EMIT     X'AA'
""")
        assert sec_bytes(obj) == bytes([0xAA])

    def test_af1_af2(self):
        _, obj, _ = assemble("""\
PAIR     CNAME    0
         PROC
LF       DATA,8   AF(1)
         DATA,8   AF(2)
         PEND
         PAIR     X'11',X'22'
""")
        assert sec_bytes(obj) == bytes([0x11, 0x22])

    def test_af_multiple_calls(self):
        _, obj, _ = assemble("""\
EMIT     CNAME    0
         PROC
LF       DATA,8   AF(1)
         PEND
         EMIT     X'AA'
         EMIT     X'BB'
         EMIT     X'CC'
""")
        assert sec_bytes(obj) == bytes([0xAA, 0xBB, 0xCC])

    def test_af_arithmetic(self):
        _, obj, _ = assemble("""\
PLUS1    CNAME    0
         PROC
LF       DATA,8   AF(1)+1
         PEND
         PLUS1    X'09'
""")
        assert sec_bytes(obj) == bytes([0x0A])

    def test_af_out_of_range_is_blank(self):
        # AF(5) where only 1 arg provided → BLANK → 0
        _, obj, _ = assemble("""\
EMIT5    CNAME    0
         PROC
LF       DATA,8   AF(5)
         PEND
         EMIT5    X'AA'
""")
        assert sec_bytes(obj) == bytes([0x00])


# ---------------------------------------------------------------------------
# 3. CF argument access
# ---------------------------------------------------------------------------

class TestCFAccess:
    def test_cf1_is_command_name(self):
        # CF(1) = the command name itself
        sym, _ = run_def("""\
GETCMD   CNAME    0
         PROC
LF       EQU      CF(1)
         PEND
         GETCMD
""")
        # CF(1) is the symbol 'GETCMD' — but we store it as a SYMBOL token
        # and evaluate it... which gives UNDEFINED (not in sym table as a value).
        # The main use of CF(1) is for NAME-comparison, not as a data value.
        # Just verify no crash.
        assert sym.lookup('GETCMD') is not None

    def test_cf2_modifier(self):
        _, obj, _ = assemble("""\
MOV      CNAME    0
         PROC
LF       DATA,8   CF(2)
         PEND
         MOV,X'42'
""")
        assert sec_bytes(obj) == bytes([0x42])

    def test_cf2_in_gen_field(self):
        # The real Sigma instruction pattern: GEN,8,4,20 NAME,CF(2),AF(1)
        _, obj, _ = assemble("""\
LW       CNAME    X'32'
         PROC
LF       GEN,8,4,20  NAME,CF(2),AF(1)
         PEND
         LW,1    X'100'
""")
        # 0x32 << 24 | 1 << 20 | 0x100
        assert sec_bytes(obj) == bytes([0x32, 0x10, 0x01, 0x00])

    def test_cf2_multi_instructions(self):
        _, obj, _ = assemble("""\
LW       CNAME    X'32'
         PROC
LF       GEN,8,4,20  NAME,CF(2),AF(1)
         PEND
         LW,2    X'200'
         LW,3    X'300'
""")
        raw = sec_bytes(obj)
        assert raw[0:4] == bytes([0x32, 0x20, 0x02, 0x00])
        assert raw[4:8] == bytes([0x32, 0x30, 0x03, 0x00])


# ---------------------------------------------------------------------------
# 4. NAME intrinsic
# ---------------------------------------------------------------------------

class TestNAME:
    def test_name_value_in_data(self):
        _, obj, _ = assemble("""\
MNEM     CNAME    X'3C'
         PROC
LF       DATA,8   NAME
         PEND
         MNEM
""")
        assert sec_bytes(obj) == bytes([0x3C])

    def test_name_in_gen(self):
        _, obj, _ = assemble("""\
OP       CNAME    X'10'
         PROC
LF       GEN,8,24  NAME,AF(1)
         PEND
         OP      X'AABBCC'
""")
        assert sec_bytes(obj) == bytes([0x10, 0xAA, 0xBB, 0xCC])

    def test_name_arithmetic(self):
        _, obj, _ = assemble("""\
INC      CNAME    X'30'
         PROC
LF       DATA,8   NAME+X'02'
         PEND
         INC
""")
        assert sec_bytes(obj) == bytes([0x32])


# ---------------------------------------------------------------------------
# 5. LF label substitution
# ---------------------------------------------------------------------------

class TestLFLabel:
    def test_lf_defines_call_site_label(self):
        sym, _, _ = assemble("""\
EMIT     CNAME    0
         PROC
LF       DATA,8   AF(1)
         PEND
TARGET   EMIT     X'AA'
""")
        target = sym.lookup('TARGET')
        assert target is not None
        assert target.value.int_val == 0   # LC at start of section

    def test_lf_no_label_ok(self):
        # Call without a label — body's LF silently skips definition
        _, obj, _ = assemble("""\
EMIT     CNAME    0
         PROC
LF       DATA,8   AF(1)
         PEND
         EMIT     X'BB'
""")
        assert sec_bytes(obj) == bytes([0xBB])

    def test_lf_multiple_calls_label_each(self):
        sym, obj, _ = assemble("""\
EMIT     CNAME    0
         PROC
LF       DATA,8   AF(1)
         PEND
A        EMIT     X'11'
B        EMIT     X'22'
""")
        assert sec_bytes(obj) == bytes([0x11, 0x22])
        assert sym.lookup('A').value.int_val == 0
        assert sym.lookup('B').value.int_val == 1


# ---------------------------------------------------------------------------
# 6. Intrinsics: NUM, S:S, SCOR, META, P#
# ---------------------------------------------------------------------------

class TestIntrinsics:
    def test_num_af_count(self):
        sym, _ = run_def("""\
CNT      CNAME    0
         PROC
LF       EQU      NUM(AF)
         PEND
A        CNT      1,2,3
""")
        assert sym_val(sym, 'A').int_val == 3

    def test_num_af_single(self):
        sym, _ = run_def("""\
CNT      CNAME    0
         PROC
LF       EQU      NUM(AF)
         PEND
A        CNT      99
""")
        assert sym_val(sym, 'A').int_val == 1

    def test_num_af_zero_args(self):
        sym, _ = run_def("""\
CNT      CNAME    0
         PROC
LF       EQU      NUM(AF)
         PEND
A        CNT
""")
        assert sym_val(sym, 'A').int_val == 0

    def test_ss_true(self):
        sym, _ = run_def("V  EQU  S:S(1,X'AA',X'BB')\n")
        assert sym_val(sym, 'V').int_val == 0xAA

    def test_ss_false(self):
        sym, _ = run_def("V  EQU  S:S(0,X'AA',X'BB')\n")
        assert sym_val(sym, 'V').int_val == 0xBB

    def test_ss_nonzero_is_true(self):
        sym, _ = run_def("V  EQU  S:S(42,X'AA',X'BB')\n")
        assert sym_val(sym, 'V').int_val == 0xAA

    def test_ss_negative_is_true(self):
        sym, _ = run_def("V  EQU  S:S(-1,X'AA',X'BB')\n")
        assert sym_val(sym, 'V').int_val == 0xAA

    def test_ss_missing_false_branch_blank(self):
        sym, _ = run_def("V  EQU  S:S(0,X'AA')\n")
        v = sym_val(sym, 'V')
        assert v.kind == ValueKind.BLANK

    def test_ss_in_cname(self):
        sym, _ = run_def("""\
PICK     CNAME    0
         PROC
LF       EQU      S:S(AF(1),AF(2),AF(3))
         PEND
A        PICK     1,X'AA',X'BB'
B        PICK     0,X'AA',X'BB'
""")
        assert sym_val(sym, 'A').int_val == 0xAA
        assert sym_val(sym, 'B').int_val == 0xBB

    def test_scor_found(self):
        sym, _ = run_def("K  EQU  SCOR(2,10,2,30)\n")
        assert sym_val(sym, 'K').int_val == 2   # 2 is at position 2

    def test_scor_not_found(self):
        sym, _ = run_def("K  EQU  SCOR(99,10,20,30)\n")
        assert sym_val(sym, 'K').int_val == 0

    def test_scor_first(self):
        sym, _ = run_def("K  EQU  SCOR(10,10,20,30)\n")
        assert sym_val(sym, 'K').int_val == 1

    def test_scor_last(self):
        sym, _ = run_def("K  EQU  SCOR(30,10,20,30)\n")
        assert sym_val(sym, 'K').int_val == 3

    def test_scor_blank_entries_skipped(self):
        # Blank entries are skipped (never match), but positions still count from 1.
        # SCOR(0, blank, 0, 30): search for 0.
        # SCOR(0, blank, 0, 30): search for 0.
        # blank at pos 1 is skipped; INT(0) at pos 2 matches → returns 2.
        sym, _ = run_def("K  EQU  SCOR(0,,0,30)\n")
        assert sym_val(sym, 'K').int_val == 2

    def test_meta_is_zero(self):
        sym, _ = run_def("V  EQU  0+META\n")
        assert sym_val(sym, 'V').int_val == 0

    def test_meta_arithmetic(self):
        # META + 1 = 0 + 1 = 1
        sym, _ = run_def("V  EQU  META+1\n")
        assert sym_val(sym, 'V').int_val == 1

    def test_inl_meta_pattern(self):
        # From ap-ilnotese: INL SET 0+META — standard IF/FI initialisation
        sym, _ = run_def("INL  SET  0+META\n")
        assert sym_val(sym, 'INL').int_val == 0


# ---------------------------------------------------------------------------
# 7. Nested CNAME calls
# ---------------------------------------------------------------------------

class TestNestedCname:
    def test_two_level_nesting(self):
        _, obj, _ = assemble("""\
BYTE     CNAME    0
         PROC
LF       DATA,8   AF(1)
         PEND
WORD     CNAME    0
         PROC
LF       BYTE     AF(1)
         BYTE     AF(2)
         BYTE     AF(3)
         BYTE     AF(4)
         PEND
         WORD     X'11',X'22',X'33',X'44'
""")
        assert sec_bytes(obj) == bytes([0x11, 0x22, 0x33, 0x44])

    def test_nested_with_gen(self):
        _, obj, _ = assemble("""\
BYTE     CNAME    0
         PROC
LF       DATA,8   AF(1)
         PEND
PAIR     CNAME    0
         PROC
LF       BYTE     AF(1)
         BYTE     AF(2)
         PEND
         PAIR     X'AB',X'CD'
         PAIR     X'EF',X'01'
""")
        assert sec_bytes(obj) == bytes([0xAB, 0xCD, 0xEF, 0x01])

    def test_three_level_nesting(self):
        _, obj, _ = assemble("""\
B1       CNAME    0
         PROC
LF       DATA,8   AF(1)
         PEND
B2       CNAME    0
         PROC
LF       B1       AF(1)
         B1       AF(1)
         PEND
B3       CNAME    0
         PROC
LF       B2       AF(1)
         PEND
         B3       X'AA'
""")
        assert sec_bytes(obj) == bytes([0xAA, 0xAA])


# ---------------------------------------------------------------------------
# 8. DO loops inside procedure bodies
# ---------------------------------------------------------------------------

class TestDoInProc:
    def test_do_loop_in_body(self):
        _, obj, _ = assemble("""\
REPEAT   CNAME    0
         PROC
LF       DO       AF(1)
         DATA,8   AF(2)
         FIN
         PEND
         REPEAT   3,X'AB'
""")
        assert sec_bytes(obj) == bytes([0xAB, 0xAB, 0xAB])

    def test_do_loop_different_counts(self):
        _, obj, _ = assemble("""\
FILL     CNAME    0
         PROC
LF       DO       AF(1)
         DATA,8   AF(2)
         FIN
         PEND
         FILL     2,X'11'
         FILL     3,X'22'
""")
        assert sec_bytes(obj) == bytes([0x11, 0x11, 0x22, 0x22, 0x22])

    def test_do_with_counter_in_body(self):
        # Build a counter inside the body using SET
        _, obj, _ = assemble("""\
RAMP     CNAME    0
         PROC
LF       DO       AF(1)
         DATA,8   AF(2)
         FIN
         PEND
         RAMP     4,X'07'
""")
        # Each iteration emits X'07' 4 times
        assert sec_bytes(obj) == bytes([7, 7, 7, 7])


# ---------------------------------------------------------------------------
# 9. Two-pass LC consistency
# ---------------------------------------------------------------------------

class TestTwoPassConsistency:
    def test_simple_lc(self):
        src = """\
EMIT     CNAME    0
         PROC
LF       DATA,8   AF(1)
         PEND
         EMIT     X'AA'
         EMIT     X'BB'
         EMIT     X'CC'
"""
        stmts = list(tokenize_text(src))
        sym1 = SymbolTable(); DefPass(stmts, sym1).run()
        lc1 = sym1.exec_lc()

        sym2 = SymbolTable(); DefPass(stmts, sym2).run()
        obj = ObjectWriter(); lst = ListingWriter()
        GenPass(stmts, sym2, obj, lst).run()
        lc2 = sym2.exec_lc()

        assert lc1 == lc2 == 3

    def test_nested_cname_lc(self):
        src = """\
BYTE     CNAME    0
         PROC
LF       DATA,8   AF(1)
         PEND
WORD     CNAME    0
         PROC
LF       BYTE     AF(1)
         BYTE     AF(2)
         BYTE     AF(3)
         BYTE     AF(4)
         PEND
         WORD     X'11',X'22',X'33',X'44'
"""
        stmts = list(tokenize_text(src))
        sym1 = SymbolTable(); DefPass(stmts, sym1).run()
        lc1 = sym1.exec_lc()

        sym2 = SymbolTable(); DefPass(stmts, sym2).run()
        obj = ObjectWriter(); lst = ListingWriter()
        GenPass(stmts, sym2, obj, lst).run()

        assert lc1 == sym2.exec_lc() == 4

    def test_label_at_proc_result(self):
        # The label defined at the CNAME call site should match the LC
        src = """\
EMIT     CNAME    0
         PROC
LF       DATA,8   AF(1)
         PEND
         EMIT     X'11'
HERE     EMIT     X'22'
         EMIT     X'33'
"""
        sym, _, _ = assemble(src)
        assert sym.lookup('HERE').value.int_val == 1  # LC=1 byte in


# ---------------------------------------------------------------------------
# 10. ProcedureBody and CallFrame dataclasses
# ---------------------------------------------------------------------------

class TestDataclasses:
    def test_procedure_body_fields(self):
        body = ProcedureBody(
            stmts=[],
            body_start=2,
            pend_index=5,
            name_value=Value.absolute(0x3C),
            is_fname=False,
        )
        assert body.body_start == 2
        assert body.pend_index == 5
        assert body.name_value.int_val == 0x3C
        assert body.is_fname is False

    def test_call_frame_get_af(self):
        from ap_assembler.lexer import Token, TT
        body = ProcedureBody([], 0, 0, Value.blank())
        frame = CallFrame(
            body=body, body_pos=0,
            return_stmts=[], return_pos=0,
            label_args=[],
            cmd_args=[[Token(TT.SYMBOL, 'MOV', 'MOV', 1, 0)]],
            oprnd_args=[
                [Token(TT.INT, 1, '1', 1, 0)],
                [Token(TT.INT, 2, '2', 1, 0)],
            ],
        )
        assert frame.get_af(1) == [Token(TT.INT, 1, '1', 1, 0)]
        assert frame.get_af(2) == [Token(TT.INT, 2, '2', 1, 0)]
        assert frame.get_af(3) == []
        assert frame.num_af() == 2
        assert frame.num_cf() == 1

    def test_call_frame_get_out_of_range(self):
        body = ProcedureBody([], 0, 0, Value.blank())
        frame = CallFrame(
            body=body, body_pos=0,
            return_stmts=[], return_pos=0,
            label_args=[], cmd_args=[], oprnd_args=[],
        )
        assert frame.get_af(1) == []
        assert frame.get_cf(1) == []
        assert frame.get_lf(1) == []


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


# ---------------------------------------------------------------------------
# 11. LOCAL / OPEN / CLOSE scoping
# ---------------------------------------------------------------------------

class TestLocalOpenClose:
    """LOCAL, OPEN, and CLOSE all work through the same mechanism:
    LOCAL/OPEN declare symbols in the innermost local scope frame;
    CLOSE is a no-op (cleanup happens at PEND via pop_local_scope).
    """

    def _asm(self, src):
        stmts = list(tokenize_text(src))
        sym = SymbolTable()
        DefPass(stmts, sym).run()
        obj = ObjectWriter(); lst = ListingWriter()
        GenPass(stmts, sym, obj, lst).run()
        return sym, sec_bytes(obj)

    def test_local_shadows_global_in_body(self):
        sym, raw = self._asm("""\
BT       EQU      0
P        CNAME    0
         PROC
         LOCAL    BT
BT       SET      1
LF       DATA     BT
         PEND
         P
""")
        assert raw == bytes([0, 0, 0, 1])

    def test_local_global_restored_after_pend(self):
        sym, _ = self._asm("""\
BT       EQU      0
P        CNAME    0
         PROC
         LOCAL    BT
BT       SET      1
         PEND
         P
AFTER    EQU      BT
""")
        assert sym_val(sym, 'BT').int_val == 0
        assert sym_val(sym, 'AFTER').int_val == 0

    def test_open_identical_to_local(self):
        sym, raw = self._asm("""\
BT       EQU      0
P        CNAME    0
         PROC
         OPEN     BT
BT       SET      7
LF       DATA     BT
         CLOSE    BT
         PEND
         P
AFTER    EQU      BT
""")
        assert raw == bytes([0, 0, 0, 7])
        assert sym_val(sym, 'BT').int_val == 0
        assert sym_val(sym, 'AFTER').int_val == 0

    def test_no_bleed_between_calls(self):
        sym, raw = self._asm("""\
X        EQU      0
P        CNAME    0
         PROC
         OPEN     X
X        SET      AF(1)
LF       DATA     X
         CLOSE    X
         PEND
         P        X'11'
         P        X'22'
         P        X'33'
AFTER    EQU      X
""")
        assert raw == bytes([0, 0, 0, 0x11, 0, 0, 0, 0x22, 0, 0, 0, 0x33])
        assert sym_val(sym, 'X').int_val == 0

    def test_open_multiple_symbols(self):
        sym, raw = self._asm("""\
A        EQU      1
B        EQU      2
P        CNAME    0
         PROC
         OPEN     A,B
A        SET      10
B        SET      20
LF       DATA     A
         DATA     B
         CLOSE    A,B
         PEND
         P
""")
        assert raw == bytes([0, 0, 0, 10, 0, 0, 0, 20])
        assert sym_val(sym, 'A').int_val == 1
        assert sym_val(sym, 'B').int_val == 2

    def test_p_hash_accumulates_across_passes(self):
        # P# SET S:UFV(P#)+1 as an OPEN interstitial must survive both
        # DEF and GEN passes without being reset by declare_local.
        src = """\
S:S      FNAME
         PROC
         PEND     AF(AF(1)+2)
         OPEN     P#
P#       SET      S:UFV(P#)+1
         CLOSE    P#
"""
        stmts = list(tokenize_text(src))
        sym = SymbolTable()
        DefPass(stmts, sym).run()
        assert sym_val(sym, 'P#').int_val == 1
        obj = ObjectWriter(); lst = ListingWriter()
        GenPass(stmts, sym, obj, lst).run()
        assert sym_val(sym, 'P#').int_val == 2

    def test_nested_procs_independent_scopes(self):
        sym, raw = self._asm("""\
X        EQU      0
INNER    CNAME    0
         PROC
         OPEN     X
X        SET      AF(1)
LF       DATA,8   X
         CLOSE    X
         PEND
OUTER    CNAME    0
         PROC
         OPEN     X
X        SET      X'FF'
         INNER    X'AB'
         INNER    X'CD'
         CLOSE    X
         PEND
         OUTER
AFTER    EQU      X
""")
        assert raw == bytes([0xAB, 0xCD])
        assert sym_val(sym, 'AFTER').int_val == 0

    def test_close_is_noop_cleanup_at_pend(self):
        # CLOSE before PEND is a no-op; the scope is cleaned up at PEND.
        # A symbol declared OPEN is still visible between CLOSE and PEND.
        sym, raw = self._asm("""\
Y        EQU      0
P        CNAME    0
         PROC
         OPEN     Y
Y        SET      X'42'
         CLOSE    Y
LF       DATA,8   Y
         PEND
         P
AFTER    EQU      Y
""")
        assert raw == bytes([0x42])   # Y still visible after CLOSE
        assert sym_val(sym, 'AFTER').int_val == 0

    def test_local_does_not_affect_outer_scope_globals(self):
        sym, _ = self._asm("""\
GVAR     EQU      55
P        CNAME    0
         PROC
         LOCAL    LVAR
LVAR     SET      99
         PEND
         P
RESULT   EQU      GVAR
""")
        assert sym_val(sym, 'GVAR').int_val == 55
        assert sym_val(sym, 'RESULT').int_val == 55
