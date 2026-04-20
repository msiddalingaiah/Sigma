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


def _subscript(v: Value, indices: list) -> Value:
    """
    Navigate a (possibly nested) list value using a sequence of 1-based indices.

    AP rule (from source ENDSSYM7 / SCBLNK):
      - If v is a LIST and 1 <= idx <= len(v.items): recurse into that element.
      - If v is a LIST and idx > len(v.items):       return Value.blank().
      - If v is a scalar and len(indices)==1 and idx==1: return v (scalar).
      - Any other combination on a non-list:          return Value.blank().
    """
    result = v
    for depth, idx_val in enumerate(indices):
        idx = idx_val.int_val if idx_val.kind == ValueKind.ABSOLUTE else 1
        if result.kind == ValueKind.LIST:
            if 1 <= idx <= len(result.items):
                result = result.items[idx - 1]
            else:
                return Value.blank()
        else:
            # Scalar: only X(1) with a single subscript returns the scalar itself
            if idx == 1 and depth == len(indices) - 1:
                return result
            return Value.blank()
    return result
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

    def __init__(self, tokens: List[Token], sym: SymbolTable, line_no: int = 0,
                 call_frame=None):
        self._tokens  = tokens
        self._pos     = 0
        self._sym     = sym
        self._line_no = line_no
        self._errors:  List[str] = []
        self._frame   = call_frame   # Optional[CallFrame] — current proc frame

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
            first = self._parse_or()
            # If a COMMA follows, this is a parenthesised list literal: (a, b, c)
            if self._peek() is not None and self._peek().type == TT.COMMA:
                items = [first]
                while self._peek() is not None and self._peek().type == TT.COMMA:
                    self._consume()   # eat COMMA
                    items.append(self._parse_or())
                self._expect(TT.RPAREN)
                return Value.list_val(items)
            self._expect(TT.RPAREN)
            return first

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
            if name == 'META':
                # META EQU 1**128 — evaluates to 0 in 32-bit arithmetic
                return Value.absolute(0)
            if name == 'P#':
                # P# = pass number: 1 for DEF pass, 2 for GEN pass
                return Value.absolute(self._sym._pass)
            if name == 'NAME' and self._frame is not None:
                # NAME = the CNAME/FNAME operand value (e.g. the opcode constant)
                return self._frame.body.name_value

            # Regular symbol lookup
            entry = self._sym.lookup_or_create(name)
            return entry.value

        # Anything else — return blank / unknown
        self._consume()
        return Value.blank()

    def _parse_function_or_subscript(self, name: str) -> Value:
        """
        Parse NAME(arg1, arg2, ...) — addressing function, intrinsic, or
        subscripted symbol reference.
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

        # --- S:UFV() — evaluate suppressing UNDEFINED errors ---------------
        if upper == 'S:UFV':
            arg = self._parse_or()
            self._expect(TT.RPAREN)
            # If the result is UNDEFINED, treat as 0 (forward-value semantics)
            if arg.kind == ValueKind.UNDEFINED:
                return Value.absolute(0)
            return arg

        # --- NUM() — argument count ----------------------------------------
        if upper == 'NUM':
            return self._eval_num()

        # --- SCOR(x, k1, k2, ...) — index of matching keyword ------------
        if upper == 'SCOR':
            return self._eval_scor()

        # --- TCOR — type correspondence (deferred stub) -------------------
        if upper == 'TCOR':
            self._skip_to_rparen()
            return Value.absolute(0)

        # --- S:S(cond, true_val, false_val) — conditional select -----------
        if upper == 'S:S':
            return self._eval_ss()

        # --- AF / CF / LF / AFA / NAME — procedure argument intrinsics ----
        if upper in ('AF', 'CF', 'LF', 'AFA'):
            return self._eval_arg_intrinsic(upper)

        if upper == 'NAME':
            self._skip_to_rparen()
            if self._frame is not None:
                return self._frame.body.name_value
            return Value.blank()

        # --- Other proc-only intrinsics (stub: undefined outside proc) ----
        if upper in ('S:KEYS', 'S:NUMC', 'S:PT', 'S:UT', 'S:IFR',
                      'S:LFR', 'S:AAD', 'S:RAD', 'S:EXT', 'S:SUM',
                      'S:LIST', 'S:D', 'S:C', 'S:INT', 'S:FS', 'S:FL',
                      'S:FX', 'S:FR', 'S:DPI'):
            self._skip_to_rparen()
            return Value.undefined()

        # --- Subscripted symbol: SYMBOL(i) or SYMBOL(i, j, ...) ----------
        indices = [self._parse_or()]
        while self._peek() is not None and self._peek().type == TT.COMMA:
            self._consume()
            indices.append(self._parse_or())
        self._expect(TT.RPAREN)

        entry = self._sym.lookup(name)
        if entry is None:
            self._sym.lookup_or_create(name)
            return Value.undefined()

        return _subscript(entry.value, indices)

    # ------------------------------------------------------------------
    # Procedure intrinsic helpers
    # ------------------------------------------------------------------

    def _eval_arg_toks(self, tok_lists: list) -> Value:
        """Evaluate a List[List[Token]] argument list and return its Value."""
        if not tok_lists:
            return Value.blank()
        v, _ = evaluate_arg(tok_lists[0], self._sym,
                             line_no=self._line_no, call_frame=self._frame)
        return v

    def _eval_arg_intrinsic(self, upper: str) -> Value:
        """
        Evaluate AF(n), CF(n), LF(n), or AFA.

        Outside a procedure frame these return Value.undefined().
        """
        # Collect the subscript index if present
        idx_val = self._parse_or()
        # Handle optional second subscript for AF(n) within NUM-count forms
        while self._peek() is not None and self._peek().type == TT.COMMA:
            self._consume()
            self._parse_or()   # discard extra subscripts for now
        self._expect(TT.RPAREN)

        if self._frame is None:
            return Value.undefined()

        if idx_val.kind == ValueKind.BLANK:
            # AF with no index: evaluate all args as a list
            if upper == 'AF':
                items = [self._eval_arg_toks([a])
                         for a in self._frame.oprnd_args]
                return Value.list_val(items) if items else Value.blank()
            return Value.blank()

        n = idx_val.int_val if idx_val.kind == ValueKind.ABSOLUTE else 1

        if upper in ('AF', 'AFA'):
            toks = self._frame.get_af(n)
        elif upper == 'CF':
            toks = self._frame.get_cf(n)
        else:  # LF
            toks = self._frame.get_lf(n)

        if not toks:
            return Value.blank()
        v, _ = evaluate_arg(toks, self._sym,
                             line_no=self._line_no, call_frame=self._frame)
        return v

    def _eval_num(self) -> Value:
        """
        NUM(expr)     → length of a list value, or 1 for a scalar.
        NUM(AF)       → count of operand args in current frame.
        NUM(CF)       → count of command-field args.
        NUM(AF(n))    → count of items in the nth arg (if it is a list).
        Works at source level for list-valued symbols (e.g. NUM(A) where A
        is an EQU/SET list); procedure-arg forms require an active frame.
        """
        # Peek: is the argument a bare AF / CF / LF (no subscript)?
        # These are frame-specific; outside a procedure they return 0.
        if self._frame is not None:
            tok = self._peek()
            if tok is not None and tok.type == TT.SYMBOL:
                upper = tok.value.upper()
                next_tok = self._tokens[self._pos + 1]                     if self._pos + 1 < len(self._tokens) else None
                if upper in ('AF', 'AFA') and (
                        next_tok is None or next_tok.type == TT.RPAREN):
                    self._consume()
                    self._expect(TT.RPAREN)
                    return Value.absolute(self._frame.num_af())
                if upper == 'CF' and (
                        next_tok is None or next_tok.type == TT.RPAREN):
                    self._consume()
                    self._expect(TT.RPAREN)
                    return Value.absolute(self._frame.num_cf())
                if upper == 'LF' and (
                        next_tok is None or next_tok.type == TT.RPAREN):
                    self._consume()
                    self._expect(TT.RPAREN)
                    return Value.absolute(len(self._frame.label_args))

        # General case: evaluate the inner expression
        inner = self._parse_or()
        while self._peek() is not None and self._peek().type == TT.COMMA:
            self._consume()
            self._parse_or()
        self._expect(TT.RPAREN)

        if inner.kind == ValueKind.LIST:
            return Value.absolute(len(inner.items))
        if inner.kind in (ValueKind.BLANK, ValueKind.UNDEFINED):
            # Bare AF with no frame: 0; with frame: argument count
            if self._frame is not None:
                return Value.absolute(self._frame.num_af())
            return Value.absolute(0)
        if inner.kind == ValueKind.ABSOLUTE:
            return Value.absolute(1)   # scalar = 1 element
        return Value.absolute(0)

    def _eval_scor(self) -> Value:
        """
        SCOR(x, k1, k2, ..., kn)
        Returns i (1-based) if x equals ki, else 0.
        Blank ki entries (consecutive commas) are skipped (never match).
        """
        first = self._parse_or()   # the value to search for
        matches = []
        while self._peek() is not None and self._peek().type == TT.COMMA:
            self._consume()   # eat the comma
            # A blank argument is two consecutive commas — peek ahead
            nxt = self._peek()
            if nxt is not None and nxt.type in (TT.COMMA, TT.RPAREN):
                matches.append(Value.blank())
            else:
                matches.append(self._parse_or())
        self._expect(TT.RPAREN)

        if first.kind not in (ValueKind.ABSOLUTE, ValueKind.CHARSTR):
            return Value.absolute(0)

        for i, candidate in enumerate(matches, start=1):
            if candidate.kind == ValueKind.BLANK:
                continue
            if candidate.kind == first.kind and candidate.int_val == first.int_val:
                return Value.absolute(i)
            # Also match CHARSTR vs raw symbol name comparisons
            if (candidate.kind == ValueKind.CHARSTR
                    and first.kind == ValueKind.CHARSTR
                    and candidate.raw == first.raw):
                return Value.absolute(i)
        return Value.absolute(0)

    def _eval_ss(self) -> Value:
        """
        S:S(cond, true_val, false_val)
        If cond is non-zero (and not BLANK/UNDEFINED) return true_val,
        else return false_val.
        Missing/blank args are treated as zero / BLANK.
        """
        args = []
        # First arg
        args.append(self._parse_or())
        while self._peek() is not None and self._peek().type == TT.COMMA:
            self._consume()
            args.append(self._parse_or())
        self._expect(TT.RPAREN)

        # Pad to 3
        while len(args) < 3:
            args.append(Value.blank())

        cond, true_val, false_val = args[0], args[1], args[2]

        # Condition is true if non-zero absolute, or RELOCATABLE/EXTERNAL
        if cond.kind == ValueKind.ABSOLUTE:
            return true_val if cond.int_val != 0 else false_val
        if cond.kind in (ValueKind.BLANK, ValueKind.UNDEFINED):
            return false_val
        return true_val   # RELOCATABLE etc. treated as true

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
                 line_no: int = 0,
                 call_frame=None) -> Tuple[Value, List[str]]:
    """
    Evaluate a single argument-position token list.

    *call_frame* is an optional ``CallFrame`` providing AF/CF/LF context
    when evaluating inside a procedure body.

    Returns (value, error_list).  error_list is empty on success.
    """
    ev = ExpressionEvaluator(tokens, sym, line_no, call_frame=call_frame)
    try:
        v = ev.evaluate()
    except AssemblerError as exc:
        return Value.undefined(), [str(exc)]
    return v, ev.errors
