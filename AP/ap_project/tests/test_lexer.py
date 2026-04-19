"""
tests/test_lexer.py  —  Unit tests for ap_assembler/lexer.py

Each test targets a specific aspect of the Phase-1 tokenizer, verified
against the known behaviour of the original APNCD module and the test
programs in testtese.txt.

Run with:
    pip install -e .
    python -m pytest
"""

from typing import List

import pytest

from ap_assembler.lexer import (
    TT, Token, Statement, Tokenizer, ArgTokenizer, tokenize_text
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def stmts(source: str):
    """Parse source text and return a list of non-comment Statements."""
    return [s for s in tokenize_text(source) if not s.is_comment]


def tokens_flat(args):
    """Flatten a list-of-lists of tokens into a single list."""
    return [tok for arg in args for tok in arg]


def arg_types(args):
    """Return token types for all args, flattened."""
    return [tok.type for tok in tokens_flat(args)]


def first_arg_val(stmt):
    """Shortcut: value of the first token in the first argument."""
    return stmt.args[0][0].value


# ---------------------------------------------------------------------------
# 1. Comment lines
# ---------------------------------------------------------------------------

class TestCommentLines:
    def test_star_comment(self):
        s = list(tokenize_text("* This is a comment\n"))
        assert len(s) == 1
        assert s[0].is_comment
        assert s[0].command is None
        assert s[0].label is None

    def test_multiple_stars(self):
        src = "***** HEADING *****\n"
        s = list(tokenize_text(src))
        assert s[0].is_comment

    def test_non_comment_not_flagged(self):
        src = "         NOP\n"
        s = stmts(src)
        assert not s[0].is_comment


# ---------------------------------------------------------------------------
# 2. Label field
# ---------------------------------------------------------------------------

class TestLabelField:
    def test_blank_label(self):
        src = "         DATA     42\n"
        s = stmts(src)
        assert s[0].label is None

    def test_present_label(self):
        src = "ALPHA    EQU      5\n"
        s = stmts(src)
        assert s[0].label == 'ALPHA'

    def test_label_uppercased(self):
        src = "myLabel  EQU   1\n"
        s = stmts(src)
        assert s[0].label == 'MYLABEL'

    def test_label_with_special_chars(self):
        src = "M:READ   EQU   0\n"
        s = stmts(src)
        assert s[0].label == 'M:READ'

    def test_dollar_label(self):
        src = "$FLAG    EQU   1\n"
        s = stmts(src)
        assert s[0].label == '$FLAG'


# ---------------------------------------------------------------------------
# 3. Command field
# ---------------------------------------------------------------------------

class TestCommandField:
    def test_simple_command(self):
        src = "         DATA     42\n"
        s = stmts(src)
        assert s[0].command == 'DATA'

    def test_command_with_subfield(self):
        src = "         RES,4    2\n"
        s = stmts(src)
        assert s[0].command == 'RES,4'

    def test_command_uppercased(self):
        src = "         equ      5\n"
        s = stmts(src)
        assert s[0].command == 'EQU'

    def test_no_command(self):
        src = "\n"
        s = stmts(src)
        assert len(s) == 0   # blank line skipped


# ---------------------------------------------------------------------------
# 4. Decimal integer constants
# ---------------------------------------------------------------------------

class TestDecimalIntegers:
    def test_simple_int(self):
        src = "         DATA     42\n"
        s = stmts(src)
        tok = s[0].args[0][0]
        assert tok.type  == TT.INT
        assert tok.value == 42

    def test_large_int(self):
        src = "         DATA     2147483647\n"
        s = stmts(src)
        assert first_arg_val(s[0]) == 2147483647

    def test_zero(self):
        src = "         DATA     0\n"
        s = stmts(src)
        assert first_arg_val(s[0]) == 0

    def test_multi_int_args(self):
        src = "         DATA     1,2,3\n"
        s = stmts(src)
        assert len(s[0].args) == 3
        vals = [a[0].value for a in s[0].args]
        assert vals == [1, 2, 3]


# ---------------------------------------------------------------------------
# 5. Hexadecimal constants  X'...'
# ---------------------------------------------------------------------------

class TestHexConstants:
    def test_simple_hex(self):
        src = "         DATA     X'1A2B'\n"
        s = stmts(src)
        tok = s[0].args[0][0]
        assert tok.type  == TT.HEX
        assert tok.value == 0x1A2B

    def test_hex_uppercase(self):
        src = "         DATA     X'ABCDEF'\n"
        s = stmts(src)
        assert s[0].args[0][0].value == 0xABCDEF

    def test_hex_max(self):
        src = "         DATA     X'FFFFFFFF'\n"
        s = stmts(src)
        assert s[0].args[0][0].value == 0xFFFFFFFF

    def test_multi_hex(self):
        src = "         DATA     X'12345678',X'ABCDEF',X'FFFFFFFF'\n"
        s = stmts(src)
        assert len(s[0].args) == 3
        assert s[0].args[0][0].value == 0x12345678
        assert s[0].args[1][0].value == 0xABCDEF
        assert s[0].args[2][0].value == 0xFFFFFFFF


# ---------------------------------------------------------------------------
# 6. Octal constants  O'...'
# ---------------------------------------------------------------------------

class TestOctalConstants:
    def test_simple_octal(self):
        src = "         DATA     O'1234'\n"
        s = stmts(src)
        tok = s[0].args[0][0]
        assert tok.type  == TT.OCT
        assert tok.value == 0o1234

    def test_octal_large(self):
        src = "         DATA     O'7654321'\n"
        s = stmts(src)
        assert s[0].args[0][0].value == 0o7654321


# ---------------------------------------------------------------------------
# 7. Packed decimal constants  D'...'
# ---------------------------------------------------------------------------

class TestPackedDecimal:
    def test_unsigned(self):
        src = "         DATA     D'99'\n"
        s = stmts(src)
        tok = s[0].args[0][0]
        assert tok.type  == TT.PKDEC
        assert tok.value == '99'

    def test_plus_sign(self):
        src = "         DATA     D'+99'\n"
        s = stmts(src)
        assert s[0].args[0][0].value == '+99'

    def test_minus_sign(self):
        src = "         DATA     D'-99'\n"
        s = stmts(src)
        assert s[0].args[0][0].value == '-99'

    def test_large_value(self):
        src = "         DATA     D'+1234567'\n"
        s = stmts(src)
        assert s[0].args[0][0].value == '+1234567'


# ---------------------------------------------------------------------------
# 8. Float constants  FX / FS / FL
# ---------------------------------------------------------------------------

class TestFloatConstants:
    def test_fs_simple(self):
        src = "         DATA     FS'5.5E-3'\n"
        s = stmts(src)
        tok = s[0].args[0][0]
        assert tok.type  == TT.FS
        assert tok.value == '5.5E-3'

    def test_fl_simple(self):
        src = "         DATA     FL'1.0'\n"
        s = stmts(src)
        assert s[0].args[0][0].type == TT.FL

    def test_fx_simple(self):
        src = "         DATA     FX'3.75B4'\n"
        s = stmts(src)
        assert s[0].args[0][0].type == TT.FX
        assert s[0].args[0][0].value == '3.75B4'

    def test_fx_complex(self):
        src = "         DATA     FX'3.69E-2B2'\n"
        s = stmts(src)
        assert s[0].args[0][0].value == '3.69E-2B2'

    def test_multiple_float_args(self):
        src = "         DATA     FS'5.5E-3',FS'1',FS'1.',FS'-1',FS'0'\n"
        s = stmts(src)
        assert len(s[0].args) == 5
        for arg in s[0].args:
            assert arg[0].type == TT.FS


# ---------------------------------------------------------------------------
# 9. Character string constants
# ---------------------------------------------------------------------------

class TestCharString:
    def test_c_prefix(self):
        src = "         DATA     C'ABCD'\n"
        s = stmts(src)
        tok = s[0].args[0][0]
        assert tok.type  == TT.CHARSTR
        assert tok.value == 'ABCD'

    def test_no_prefix(self):
        src = "         DATA     'ABCD'\n"
        s = stmts(src)
        tok = s[0].args[0][0]
        assert tok.type  == TT.CHARSTR
        assert tok.value == 'ABCD'

    def test_single_char(self):
        src = "         DATA     C'1'\n"
        s = stmts(src)
        assert s[0].args[0][0].value == '1'

    def test_embedded_quote(self):
        src = "         DATA     C'AB''C'\n"
        s = stmts(src)
        assert s[0].args[0][0].value == "AB'C"

    def test_long_string(self):
        src = "         DATA     C'ABCDEFGHIJKLMNOP'\n"
        s = stmts(src)
        assert s[0].args[0][0].value == 'ABCDEFGHIJKLMNOP'


# ---------------------------------------------------------------------------
# 10. Symbols
# ---------------------------------------------------------------------------

class TestSymbols:
    def test_simple_symbol(self):
        src = "ALPHA    EQU      5\n"
        s = stmts(src)
        assert s[0].label   == 'ALPHA'
        assert s[0].command == 'EQU'
        assert s[0].args[0][0].type == TT.INT

    def test_symbol_in_arg(self):
        src = "         DATA     MYVAL\n"
        s = stmts(src)
        tok = s[0].args[0][0]
        assert tok.type  == TT.SYMBOL
        assert tok.value == 'MYVAL'

    def test_colon_in_symbol(self):
        src = "         REF      M:LO\n"
        s = stmts(src)
        assert s[0].args[0][0].value == 'M:LO'

    def test_dollar_prefix(self):
        src = "         DATA     %\n"
        s = stmts(src)
        tok = s[0].args[0][0]
        assert tok.type == TT.SYMBOL


# ---------------------------------------------------------------------------
# 11. Operators
# ---------------------------------------------------------------------------

class TestOperators:
    def test_addition(self):
        src = "         DATA     A1+A2\n"
        s = stmts(src)
        assert TT.PLUS in arg_types(s[0].args)

    def test_subtraction(self):
        src = "         DATA     R1-A1\n"
        s = stmts(src)
        assert TT.MINUS in arg_types(s[0].args)

    def test_multiply(self):
        src = "         DATA     A1*A2\n"
        s = stmts(src)
        assert TT.MULTIPLY in arg_types(s[0].args)

    def test_divide(self):
        src = "         DATA     A1/A2\n"
        s = stmts(src)
        assert TT.DIVIDE in arg_types(s[0].args)

    def test_covered_divide(self):
        src = "         DATA     A1//A2\n"
        s = stmts(src)
        assert TT.COVDIV in arg_types(s[0].args)

    def test_scale(self):
        src = "         DATA     1**128\n"
        s = stmts(src)
        assert TT.SCALE in arg_types(s[0].args)

    def test_bitwise_and(self):
        src = "         DATA     A1&A2\n"
        s = stmts(src)
        assert TT.AND_OP in arg_types(s[0].args)

    def test_bitwise_or(self):
        src = "         DATA     A1|A2\n"
        s = stmts(src)
        assert TT.OR_OP in arg_types(s[0].args)

    def test_bitwise_xor(self):
        src = "         DATA     A1||A2\n"
        s = stmts(src)
        assert TT.XOR_OP in arg_types(s[0].args)

    def test_complement(self):
        src = "         DATA     ~A1\n"
        s = stmts(src)
        assert TT.COMPLEMENT in arg_types(s[0].args)

    def test_equality(self):
        src = "         DO       A=B\n"
        s = stmts(src)
        assert TT.EQ_OP in arg_types(s[0].args)

    def test_not_equal(self):
        src = "         DO       A~=B\n"
        s = stmts(src)
        assert TT.NEQ_OP in arg_types(s[0].args)

    def test_greater_equal(self):
        src = "         DO       A>=B\n"
        s = stmts(src)
        assert TT.GTE_OP in arg_types(s[0].args)

    def test_less_than(self):
        src = "         DO       A<B\n"
        s = stmts(src)
        assert TT.LT_OP in arg_types(s[0].args)


# ---------------------------------------------------------------------------
# 12. Unary operators
# ---------------------------------------------------------------------------

class TestUnaryOps:
    def test_unary_minus(self):
        src = "         DATA     -185\n"
        s = stmts(src)
        types = arg_types(s[0].args)
        assert TT.MINUS in types
        assert TT.INT   in types

    def test_unary_plus(self):
        src = "         DATA     +42\n"
        s = stmts(src)
        types = arg_types(s[0].args)
        assert TT.PLUS in types
        assert TT.INT  in types


# ---------------------------------------------------------------------------
# 13. Literal expressions  L(...)  and  =expr
# ---------------------------------------------------------------------------

class TestLiterals:
    def test_literal_l_form(self):
        src = "         LW,1     L(-185)\n"
        s = stmts(src)
        assert TT.LIT_L in arg_types(s[0].args)

    def test_literal_eq_form(self):
        src = "         LW,1     =-185\n"
        s = stmts(src)
        assert TT.LIT_EQ in arg_types(s[0].args)

    def test_literal_with_hex(self):
        src = "         LW,1     L(X'5DF')\n"
        s = stmts(src)
        types = arg_types(s[0].args)
        assert TT.LIT_L in types
        assert TT.HEX   in types

    def test_literal_with_symbol(self):
        src = "         LW,1     =AB\n"
        s = stmts(src)
        types = arg_types(s[0].args)
        assert TT.LIT_EQ in types
        assert TT.SYMBOL in types


# ---------------------------------------------------------------------------
# 14. Indirect addressing  *expr
# ---------------------------------------------------------------------------

class TestIndirect:
    def test_indirect_symbol(self):
        src = "         LW,1     *BUFPTR\n"
        s = stmts(src)
        types = arg_types(s[0].args)
        assert TT.INDIRECT in types
        assert TT.SYMBOL   in types

    def test_indirect_register(self):
        src = "         LW,1     *RL\n"
        s = stmts(src)
        assert TT.INDIRECT in arg_types(s[0].args)


# ---------------------------------------------------------------------------
# 15. Parenthesised expressions
# ---------------------------------------------------------------------------

class TestParens:
    def test_simple_parens(self):
        src = "         DATA     (A+B)\n"
        s = stmts(src)
        types = arg_types(s[0].args)
        assert TT.LPAREN in types
        assert TT.RPAREN in types

    def test_nested_parens(self):
        src = "         DATA     (A+(B*C))\n"
        s = stmts(src)
        types = arg_types(s[0].args)
        assert types.count(TT.LPAREN) == 2
        assert types.count(TT.RPAREN) == 2


# ---------------------------------------------------------------------------
# 16. Multiple arguments
# ---------------------------------------------------------------------------

class TestMultipleArgs:
    def test_two_args(self):
        src = "         DATA     1,2\n"
        s = stmts(src)
        assert len(s[0].args) == 2

    def test_five_args(self):
        src = "         DATA     A,B,C,D,E\n"
        s = stmts(src)
        assert len(s[0].args) == 5

    def test_blank_arg_between_commas(self):
        src = "         GEN,8,24 X'14',M:LO\n"
        s = stmts(src)
        assert len(s[0].args) == 2


# ---------------------------------------------------------------------------
# 17. Subscripted symbols  SYMBOL(args)
# ---------------------------------------------------------------------------

class TestSubscript:
    def test_af_function(self):
        src = "         DATA     AF(1)\n"
        s = stmts(src)
        types = arg_types(s[0].args)
        assert TT.SYMBOL in types
        assert TT.LPAREN in types
        assert TT.INT    in types
        assert TT.RPAREN in types

    def test_ba_function(self):
        src = "         DATA     BA(ADRS)\n"
        s = stmts(src)
        assert TT.SYMBOL in arg_types(s[0].args)

    def test_nested_subscript(self):
        src = "         DATA     BA(HA(L(5)))\n"
        s = stmts(src)
        assert TT.LIT_L in arg_types(s[0].args)


# ---------------------------------------------------------------------------
# 18. Line continuation
# ---------------------------------------------------------------------------

class TestContinuation:
    def test_semicolon_continuation(self):
        src = (
            "         REF      M:SI,M:CI,M:CO,;\n"
            "                  M:BO\n"
        )
        s = stmts(src)
        assert len(s[0].args) >= 4

    def test_def_continuation(self):
        src = (
            "         DEF      ABORT,MPX1,CLRLSTBF,SYSNAME,;\n"
            "                  BO%SIZE\n"
        )
        s = stmts(src)
        assert len(s[0].args) >= 5


# ---------------------------------------------------------------------------
# 19. Full statement round-trip from testtese.txt examples
# ---------------------------------------------------------------------------

class TestFullStatements:
    TESTTESE = """\
*****
***** TEST OF SIGMA 5-9 XEROX ASSEMBLY PROGRAM.
*****
         REF      M:LO
         SYSTEM   SIG9P
* CONSTANTS
*  X: HEXADECIMAL
         DATA     X'12345678',X'ABCDEF',X'FFFFFFFF'
*  O: OCTAL
         DATA     O'1234',O'7654321'
*  INTEGER
         DATA     2147483647
*  D: DECIMAL
         DATA     D'99',D'+99',D'-99',D'+1234567'
*  FX: FIXED POINT DECIMAL
         DATA     FX'1B1',FX'1B4',FX'-1B1',FX'-1B4'
*  FS: FLOATING POINT SHORT
         DATA     FS'5.5E-3',FS'1',FS'1.',FS'-1',FS'0'
*  C: CHARACTER STRING
         DATA     C'1',C'ABCD','1','ABCD',C'AB''C'
* LITERALS
AB       LW,1     L(-185)
         LW,1     L(X'5DF')
         LW,1     =AB
* ADDRESSING FUNCTIONS
ADRS     EQU      BA(%)+1
         LI,1     WA(ADRS)
A1       EQU      5
A2       EQU      6
R1       DATA     1
         DATA     R1+A1,R1-A1
         DATA     A1+A2,A1-A2
"""

    def test_parses_without_error(self):
        all_stmts = list(tokenize_text(self.TESTTESE))
        non_comment = [s for s in all_stmts if not s.is_comment]
        assert len(non_comment) > 10

    def test_ref_statement(self):
        s = stmts(self.TESTTESE)
        ref = next(x for x in s if x.command == 'REF')
        assert ref.args[0][0].value == 'M:LO'

    def test_system_statement(self):
        s = stmts(self.TESTTESE)
        sys_stmt = next(x for x in s if x.command == 'SYSTEM')
        assert sys_stmt.args[0][0].value == 'SIG9P'

    def test_hex_data(self):
        s = stmts(self.TESTTESE)
        data_hex = next(
            x for x in s
            if x.command and 'DATA' in x.command
            and x.args and x.args[0][0].type == TT.HEX
        )
        assert data_hex.args[0][0].value == 0x12345678
        assert data_hex.args[2][0].value == 0xFFFFFFFF

    def test_equ_with_expression(self):
        s = stmts(self.TESTTESE)
        equ = next(x for x in s if x.command == 'EQU' and x.label == 'ADRS')
        types = arg_types(equ.args)
        assert TT.SYMBOL in types
        assert TT.PLUS   in types
        assert TT.INT    in types

    def test_data_with_add(self):
        s = stmts(self.TESTTESE)
        data = next(
            x for x in s
            if x.command and 'DATA' in x.command
            and len(x.args) == 2
            and any(tok.type == TT.PLUS for tok in tokens_flat(x.args))
        )
        assert data is not None

    def test_literal_l(self):
        s = stmts(self.TESTTESE)
        lw = next(
            x for x in s
            if x.command == 'LW,1'
            and any(tok.type == TT.LIT_L for tok in tokens_flat(x.args))
        )
        assert lw is not None

    def test_literal_eq(self):
        s = stmts(self.TESTTESE)
        lw = next(
            x for x in s
            if x.command == 'LW,1'
            and any(tok.type == TT.LIT_EQ for tok in tokens_flat(x.args))
        )
        assert lw is not None

    def test_char_with_embedded_quote(self):
        s = stmts(self.TESTTESE)
        data = next(
            x for x in s
            if x.command and 'DATA' in x.command
            and any(
                tok.type == TT.CHARSTR and "'" in (tok.value or '')
                for tok in tokens_flat(x.args)
            )
        )
        embedded = next(
            tok for tok in tokens_flat(data.args)
            if tok.type == TT.CHARSTR and "'" in tok.value
        )
        assert embedded.value == "AB'C"


# ---------------------------------------------------------------------------
# 20. ArgTokenizer unit tests
# ---------------------------------------------------------------------------

class TestArgTokenizer:
    def _tok(self, text: str) -> List[List[Token]]:
        return ArgTokenizer(text, line_no=1, start_col=9).tokenize()

    def test_empty(self):
        assert self._tok('') == []

    def test_single_int(self):
        args = self._tok('42')
        assert len(args) == 1
        assert args[0][0].type  == TT.INT
        assert args[0][0].value == 42

    def test_two_ints(self):
        args = self._tok('1,2')
        assert len(args) == 2

    def test_blank_arg(self):
        args = self._tok(',42')
        assert len(args) == 2
        assert args[0][0].type == TT.BLANK_ARG
        assert args[1][0].value == 42

    def test_hex(self):
        args = self._tok("X'FF'")
        assert args[0][0].type  == TT.HEX
        assert args[0][0].value == 255

    def test_oct(self):
        args = self._tok("O'17'")
        assert args[0][0].type  == TT.OCT
        assert args[0][0].value == 0o17

    def test_char(self):
        args = self._tok("'ABC'")
        assert args[0][0].type  == TT.CHARSTR
        assert args[0][0].value == 'ABC'

    def test_c_char(self):
        args = self._tok("C'ABC'")
        assert args[0][0].type  == TT.CHARSTR
        assert args[0][0].value == 'ABC'

    def test_expr_add(self):
        args = self._tok('A+1')
        types = [t.type for t in args[0]]
        assert TT.SYMBOL in types
        assert TT.PLUS   in types
        assert TT.INT    in types

    def test_expr_complex(self):
        args = self._tok('BA(ADRS)+1')
        types = [t.type for t in args[0]]
        assert TT.SYMBOL in types
        assert TT.LPAREN in types
        assert TT.RPAREN in types
        assert TT.PLUS   in types
        assert TT.INT    in types

    def test_indirect(self):
        args = self._tok('*RL')
        assert args[0][0].type == TT.INDIRECT

    def test_literal_l(self):
        args = self._tok('L(42)')
        assert args[0][0].type == TT.LIT_L

    def test_literal_eq(self):
        args = self._tok('=42')
        assert args[0][0].type == TT.LIT_EQ

    def test_unary_minus(self):
        args = self._tok('-185')
        types = [t.type for t in args[0]]
        assert TT.MINUS in types
        assert TT.INT   in types

    def test_scale_op(self):
        args = self._tok('1**128')
        types = [t.type for t in args[0]]
        assert TT.SCALE in types

    def test_pkdec(self):
        args = self._tok("D'+99'")
        assert args[0][0].type  == TT.PKDEC
        assert args[0][0].value == '+99'

    def test_fs_const(self):
        args = self._tok("FS'5.5E-3'")
        assert args[0][0].type  == TT.FS
        assert args[0][0].value == '5.5E-3'

    def test_fl_const(self):
        args = self._tok("FL'1.0'")
        assert args[0][0].type == TT.FL

    def test_fx_const(self):
        args = self._tok("FX'3.75B4'")
        assert args[0][0].type  == TT.FX
        assert args[0][0].value == '3.75B4'
