"""
ap_assembler/expression.py — Expression evaluator.

Takes a list of Token objects (from the argument-field tokenizer) and
evaluates them into a Value.

The AP expression grammar is a standard arithmetic grammar with these
additions:

  - Addressing functions: BA(expr), HA(expr), WA(expr), DA(expr), ABSVAL(expr)
  - Literal references:   L(expr)  or  =expr
  - Indirect addressing:  *expr
  - The current location: % (execution LC) or %% (load LC)
  - Symbol references:    looked up in the SymbolTable

The token list produced by ArgTokenizer is in infix order with explicit
precedence represented by operator tokens, so this evaluator is a simple
recursive-descent parser over the flat token list.

Operator precedence (lowest to highest, matching the original):
  1. | ||        (OR, XOR)
  2. &            (AND)
  3. = ~= >= <= > < (comparison)
  4. + -          (additive)
  5. * / //       (multiplicative)
  6. **           (scale / shift)
  7. ~ unary-     (complement, negate)
  8. primary      (constants, symbols, parenthesised)
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .lexer import TT, Token
from .value import (
    Value, ValueKind, Resolution,
    AssemblerError,
    _add_values, _negate, _complement, _int_binop,
    apply_address_function,
)
from .symbol_table import SymbolTable


# Addressing functions that receive one argument
_ADDR_FUNCS = frozenset({'BA', 'HA', 'WA', 'DA', 'ABSVAL'})


# ---------------------------------------------------------------------------
# Expression evaluator
# ---------------------------------------------------------------------------

class ExpressionEvaluator:
    """
    Evaluates a flat list of Tokens (one argument position from ArgTokenizer)
    into a Value.

    Usage::

        ev = ExpressionEvaluator(tokens, sym_table, line_no)
        value = ev.evaluate()

    The evaluator modifies no state except reading from the symbol table.
    Forward references (undefined symbols) produce Value.undefined(), which
    will be resolved in later passes.
    """

    def __init__(self, tokens: List[Token], sym: SymbolTable, line_no: int = 0):
        self._tokens  = tokens
        self._pos     = 0
        self._sym     = sym
        self._line_no = line_no
        self._errors:  List[str] = []

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def evaluate(self) -> Value:
        """Evaluate the token list and return the resulting Value."""
        if not self._tokens:
            return Value.blank()

        # Handle top-level markers
        first = self._peek()
        if first is None:
            return Value.blank()
        if first.type == TT.BLANK_ARG:
            return Value.blank()
        if first.type == TT.INDIRECT:
            self._consume()   # drop INDIRECT marker; indirect is handled at
            return self._parse_or()   # the instruction level, not here

        if first.type == TT.LIT_EQ:
            self._consume()
            inner = self._parse_or()
            return Value(kind=ValueKind.ABSOLUTE,
                         int_val=0,
                         raw=('literal', inner))  # placeholder; real literal handling in gen pass

        if first.type == TT.LIT_L:
            self._consume()   # consume L(
            inner = self._parse_or()
            self._expect(TT.RPAREN)
            return Value(kind=ValueKind.ABSOLUTE,
                         int_val=0,
                         raw=('literal', inner))

        return self._parse_or()

    @property
    def errors(self) -> List[str]:
        return list(self._errors)

    # ------------------------------------------------------------------
    # Token stream helpers
    # ------------------------------------------------------------------

    def _peek(self, offset: int = 0) -> Optional[Token]:
        idx = self._pos + offset
        return self._tokens[idx] if idx < len(self._tokens) else None

    def _consume(self) -> Optional[Token]:
        tok = self._peek()
        self._pos += 1
        return tok

    def _expect(self, tt: TT) -> Optional[Token]:
        tok = self._peek()
        if tok is not None and tok.type == tt:
            self._pos += 1
            return tok
        # Silently recover — missing close paren etc.
        return None

    # ------------------------------------------------------------------
    # Recursive-descent grammar
    # ------------------------------------------------------------------

    def _parse_or(self) -> Value:
        """OR-level:  expr | expr   and   expr || expr"""
        lhs = self._parse_and()
        while True:
            tok = self._peek()
            if tok is None:
                break
            if tok.type == TT.XOR_OP:
                self._consume()
                rhs = self._parse_and()
                lhs = _int_binop('||', lhs, rhs)
            elif tok.type == TT.OR_OP:
                self._consume()
                rhs = self._parse_and()
                lhs = _int_binop('|', lhs, rhs)
            else:
                break
        return lhs

    def _parse_and(self) -> Value:
        """AND-level:  expr & expr"""
        lhs = self._parse_compare()
        while True:
            tok = self._peek()
            if tok is not None and tok.type == TT.AND_OP:
                self._consume()
                rhs = self._parse_compare()
                lhs = _int_binop('&', lhs, rhs)
            else:
                break
        return lhs

    def _parse_compare(self) -> Value:
        """Comparison:  = ~= >= <= > <"""
        lhs = self._parse_add()
        while True:
            tok = self._peek()
            if tok is None:
                break
            op_map = {
                TT.EQ_OP:  '=',
                TT.NEQ_OP: '~=',
                TT.GTE_OP: '>=',
                TT.LTE_OP: '<=',
                TT.GT_OP:  '>',
                TT.LT_OP:  '<',
            }
            if tok.type in op_map:
                op = op_map[tok.type]
                self._consume()
                rhs = self._parse_add()
                # AP comparison on addresses: produce integer result
                lhs = _int_binop(op, lhs, rhs)
            else:
                break
        return lhs

    def _parse_add(self) -> Value:
        """Additive:  + -"""
        lhs = self._parse_mul()
        while True:
            tok = self._peek()
            if tok is None:
                break
            if tok.type == TT.PLUS:
                self._consume()
                # Check if this is a unary + (nothing on left yet is handled
                # by _parse_unary); here it is binary
                rhs = self._parse_mul()
                lhs = _add_values(lhs, rhs, +1)
            elif tok.type == TT.MINUS:
                self._consume()
                rhs = self._parse_mul()
                lhs = _add_values(lhs, rhs, -1)
            else:
                break
        return lhs

    def _parse_mul(self) -> Value:
        """Multiplicative:  * / // **"""
        lhs = self._parse_unary()
        while True:
            tok = self._peek()
            if tok is None:
                break
            if tok.type == TT.SCALE:
                self._consume()
                rhs = self._parse_unary()
                lhs = _int_binop('**', lhs, rhs)
            elif tok.type == TT.MULTIPLY:
                self._consume()
                rhs = self._parse_unary()
                lhs = _int_binop('*', lhs, rhs)
            elif tok.type == TT.COVDIV:
                self._consume()
                rhs = self._parse_unary()
                lhs = _int_binop('//', lhs, rhs)
            elif tok.type == TT.DIVIDE:
                self._consume()
                rhs = self._parse_unary()
                lhs = _int_binop('/', lhs, rhs)
            else:
                break
        return lhs

    def _parse_unary(self) -> Value:
        """Unary:  -expr  ~expr  +expr"""
        tok = self._peek()
        if tok is None:
            return Value.blank()
        if tok.type == TT.MINUS:
            self._consume()
            operand = self._parse_unary()
            return _negate(operand)
        if tok.type == TT.COMPLEMENT:
            self._consume()
            operand = self._parse_unary()
            return _complement(operand)
        if tok.type == TT.PLUS:
            self._consume()
            return self._parse_unary()
        return self._parse_primary()

    def _parse_primary(self) -> Value:
        """
        Primary expressions:
          integer / hex / octal / packed-decimal constant
          FX / FS / FL constant
          character string constant
          symbol reference
          addressing function call: BA(x), HA(x), WA(x), DA(x), ABSVAL(x)
          L(expr) literal reference
          % / %% location counter
          (expr) parenthesised sub-expression
        """
        tok = self._peek()
        if tok is None:
            return Value.blank()

        # --- Integer constants -------------------------------------------
        if tok.type == TT.INT:
            self._consume()
            return Value.absolute(tok.value)

        if tok.type == TT.HEX:
            self._consume()
            return Value.absolute(tok.value)

        if tok.type == TT.OCT:
            self._consume()
            return Value.absolute(tok.value)

        # --- Typed constants (evaluated lazily — return typed Value) ------
        if tok.type == TT.PKDEC:
            self._consume()
            return Value.pkdec(tok.value)

        if tok.type == TT.CHARSTR:
            self._consume()
            return Value.charstr(tok.value)

        if tok.type == TT.FX:
            self._consume()
            return Value.fx(tok.value)

        if tok.type == TT.FS:
            self._consume()
            return Value.fs(tok.value)

        if tok.type == TT.FL:
            self._consume()
            return Value.fl(tok.value)

        # --- Parenthesised expression -------------------------------------
        if tok.type == TT.LPAREN:
            self._consume()
            inner = self._parse_or()
            self._expect(TT.RPAREN)
            return inner

        # --- Literal references -------------------------------------------
        if tok.type == TT.LIT_L:
            self._consume()          # consume L(
            inner = self._parse_or()
            self._expect(TT.RPAREN)
            # Return a placeholder; the literal pool is built in the gen pass
            return Value(kind=ValueKind.ABSOLUTE, int_val=0,
                         raw=('literal', inner))

        if tok.type == TT.LIT_EQ:
            self._consume()
            inner = self._parse_or()
            return Value(kind=ValueKind.ABSOLUTE, int_val=0,
                         raw=('literal', inner))

        # --- Symbol reference (includes addressing functions and % / %%) --
        if tok.type == TT.SYMBOL:
            name = tok.value
            self._consume()

            # Check for subscript / function call: NAME(...)
            next_tok = self._peek()
            if next_tok is not None and next_tok.type == TT.LPAREN:
                return self._parse_function_or_subscript(name)

            # Special symbols
            if name == '%':
                return self._sym.dollar_value()
            if name == '%%':
                return self._sym.dollar_dollar_value()

            # Regular symbol lookup
            entry = self._sym.lookup_or_create(name)
            return entry.value

        # Anything else — return blank / unknown
        self._consume()
        return Value.blank()

    def _parse_function_or_subscript(self, name: str) -> Value:
        """
        Parse NAME(arg1, arg2, ...) — either an addressing function call
        or a subscripted symbol reference.

        Addressing functions: BA, HA, WA, DA, ABSVAL, L, CS, NUM, ...
        """
        upper = name.upper()
        self._consume()  # consume LPAREN

        # --- Simple one-argument addressing functions ----------------------
        if upper in _ADDR_FUNCS:
            arg = self._parse_or()
            self._expect(TT.RPAREN)
            return apply_address_function(upper, arg)

        # --- CS() — returns control section number of argument -----------
        if upper == 'CS':
            arg = self._parse_or()
            self._expect(TT.RPAREN)
            if arg.kind == ValueKind.RELOCATABLE:
                return Value.absolute(arg.csect)
            return Value.absolute(0)

        # --- NUM() — number of elements (procedure arg count) -----------
        # NUM() is only meaningful inside a procedure; return 0 at top level
        if upper == 'NUM':
            # Consume arguments without evaluating
            self._skip_to_rparen()
            return Value.absolute(0)

        # --- S:UFV() — use forward value; evaluate arg ignoring fwd refs --
        if upper == 'S:UFV':
            arg = self._parse_or()
            self._expect(TT.RPAREN)
            return arg   # same as regular evaluation here

        # --- SCOR() / TCOR() — symbol/type correspondence (proc only) ----
        if upper in ('SCOR', 'TCOR'):
            self._skip_to_rparen()
            return Value.absolute(0)   # deferred to procedure engine

        # --- AF() CF() LF() — argument field intrinsics (proc only) ------
        if upper in ('AF', 'CF', 'LF', 'AFA', 'NAME', 'S:KEYS',
                      'S:NUMC', 'S:PT', 'S:UT', 'S:IFR', 'S:LFR',
                      'S:AAD', 'S:RAD', 'S:EXT', 'S:SUM', 'S:LIST',
                      'S:D', 'S:C', 'S:INT', 'S:FS', 'S:FL', 'S:FX',
                      'S:FR', 'S:DPI'):
            # These are only meaningful inside a procedure body; return a
            # placeholder value when encountered outside one.
            self._skip_to_rparen()
            return Value.undefined()

        # --- Subscripted symbol: SYMBOL(index) ---------------------------
        # Evaluate the subscript and use it to index a list-typed symbol.
        arg = self._parse_or()
        self._expect(TT.RPAREN)

        entry = self._sym.lookup(name)
        if entry is None:
            self._sym.lookup_or_create(name)
            return Value.undefined()

        # List subscript evaluation is deferred to the code generator
        # (the list structure lives in the symbol table as a Value with
        # kind=COMPLEX_SUM or similar).  Return the symbol's value for now.
        return entry.value

    def _skip_to_rparen(self) -> None:
        """Consume tokens up to and including the matching RPAREN."""
        depth = 1
        while depth > 0 and self._pos < len(self._tokens):
            tok = self._consume()
            if tok is None:
                break
            if tok.type == TT.LPAREN:
                depth += 1
            elif tok.type == TT.RPAREN:
                depth -= 1


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def evaluate_arg(tokens: List[Token], sym: SymbolTable,
                 line_no: int = 0) -> Tuple[Value, List[str]]:
    """
    Evaluate a single argument-position token list.

    Returns (value, error_list).  error_list is empty on success.
    """
    ev = ExpressionEvaluator(tokens, sym, line_no)
    try:
        v = ev.evaluate()
    except AssemblerError as exc:
        return Value.undefined(), [str(exc)]
    return v, ev.errors
