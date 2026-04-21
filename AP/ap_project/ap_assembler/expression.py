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

AP source correspondence
------------------------
The original AP expression evaluator is a **stack machine** implemented in
``SCAN`` (apdgctt.txt, label ``SCAN`` ~line 4561).  It walks a pre-encoded
text stream (produced by the Phase-1 name collector) and maintains two
parallel evaluation stacks: the Expression Control Table (ECT, indexed by
register XS) and the Expression Value Table (EVT).  Operators are dispatched
via a jump table at ``SC4%JUMP`` (~line 6420).

This Python module replaces the stack machine with **recursive descent**:
the Python call stack plays the role of the ECT/EVT, and each
``_parse_*`` method corresponds to a level of the operator-precedence
hierarchy.  The semantic results are identical; the structural difference
is noted in each method below.
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

    AP: ``SCENDSSYM`` (apdgctt.txt ~line 5219) handles end-of-subscripted-symbol
    in the SCAN loop.  When the subscript exceeds the list length, execution
    falls through to ``SCBLNK`` (~line 4780, via checks at ~5268/5286), producing
    a blank result rather than an error.  ``SCBLNKSYM`` (~line 4780) handles the
    case where an implicit blank is needed for a missing subscript.

    Rules (ENDSSYM7 / SCBLNK):
      - LIST, 1 <= idx <= len(items): recurse into that element.
      - LIST, idx > len(items):        return Value.blank().
      - scalar, single subscript idx==1: return scalar unchanged.
      - any other combination on non-list: return Value.blank().
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

    AP: ``SCAN`` / ``EV%CLN%OPRND`` (apdgctt.txt ~line 4557).
    ``EV%CLN%OPRND`` is the directive-level entry point that loads the operand
    field index (XW) before falling into ``SCAN``.  Both entry points share the
    same evaluation loop ``SCLOOP`` (~line 4575), which dispatches on encoded
    item type via ``SC1%JUMP`` (~line 4597).  Operators are handled later via
    ``V%OPERATOR`` / ``SC4%JUMP`` (~lines 6300, 6420).
    """

    def __init__(self, tokens: List[Token], sym: SymbolTable, line_no: int = 0,
                 call_frame=None, executor=None):
        self._tokens   = tokens
        self._pos      = 0
        self._sym      = sym
        self._line_no  = line_no
        self._errors:  List[str] = []
        self._frame    = call_frame   # Optional[CallFrame] — current proc frame
        self._executor = executor     # Optional[DefPass] — for FNAME calls

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def evaluate(self) -> Value:
        """Evaluate the token list and return the resulting Value.

        AP: entry point for ``SCAN`` (apdgctt.txt ~line 4561).  The original
        has two entry points: ``SCAN1`` for a single expression (``1ARG=1``)
        and ``SCAN`` for a series of expressions (``1ARG=0``).  We always
        evaluate one argument position, corresponding to ``SCAN1``.

        Blank arguments (``SCBLNK``, ~line 4612), indirect-address markers, and
        literal-pool tokens (``SCLITF``, ~line 4994) are handled here before
        the recursive-descent grammar begins.
        """
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
        """OR-level:  ``expr | expr``   and   ``expr || expr``.

        AP: ``SCOPOR`` (apdgctt.txt ~line 6438) and ``SCOPEOR`` (~line 6442)
        in the ``SC4%JUMP`` binary-operator dispatch table.  Bitwise OR and
        bitwise XOR (exclusive-OR) on 32-bit integers.  In SCAN these are
        evaluated after both operands are on the stack; here they are the
        lowest-precedence level in the recursive-descent grammar.
        """
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
        """AND-level:  ``expr & expr``.

        AP: ``SCOPAND`` (apdgctt.txt ~line 6446) in ``SC4%JUMP``.
        Bitwise AND on 32-bit integers.
        """
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
        """Comparison operators:  ``= ~= >= <= > <``.

        AP: ``SCOPEQ`` (~6450), ``SCOPNE`` (~6456), ``SCOPGE`` (~6460),
        ``SCOPLE`` (~6464), ``SCOPG`` (~6468), ``SCOPL`` (~6472) in ``SC4%JUMP``.
        All comparison operators use the ``CD`` (Compare Double) instruction and
        branch to ``SCOPTRUE`` (sets result to ``DBLONE`` = -1) or ``SCOP6``
        (sets result to ``ZERO`` = 0).  AP boolean convention: -1 = true, 0 = false.
        ``DO``-loop semantics depend on this: ``DO -1`` (true condition) skips
        the body (executes ELSE), because the count -1 ≤ 0.
        """
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
        """Additive:  ``+ -``.

        AP: ``SCOPPLS`` (apdgctt.txt ~line 6481) and ``SCOPMNS`` (~6476) in
        ``SC4%JUMP``.  Addition uses ``AD`` (Add Double), subtraction uses
        ``SD`` (Subtract Double).  Both trap overflow and call ``TERR``.
        Address arithmetic (RELOCATABLE + offset) is handled separately via
        ``SCADDSUM`` / ``SCCMPSUM`` — our Python equivalent is ``_add_values``
        in value.py, which preserves the RELOCATABLE kind.
        """
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
        """Multiplicative:  ``* / // **``.

        AP: ``SCOPMLT`` (~6496), ``SCOPDVD`` (~6489), ``SCOPCQ`` (~6483),
        ``SCOPSHFT`` (~6501) in ``SC4%JUMP``.

        - ``*``  → ``SCOPMLT``: ``MW`` (Multiply Word) — lower 32 bits of product.
        - ``/``  → ``SCOPDVD``: ``DW`` (Divide Word) — quotient (sign-extended).
        - ``//`` → ``SCOPCQ``: covered quotient — ``AD`` then ``SD`` by 1; rounds
          toward zero like C integer division.
        - ``**`` → ``SCOPSHFT``: ``SLD`` (Shift Left Double) by shift count.
          Shift counts ≥ 64 produce zero (``SCOP6`` path).  Our Python
          implementation caps at 32 bits (shifts ≥ 32 → 0) since AP values
          are 32-bit.
        """
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
        """Unary:  ``-expr``  ``~expr``  ``+expr``.

        AP: Unary minus is handled in the ``V%OPERATOR`` framework
        (apdgctt.txt ~line 6300) via the ``LCD`` (Load Complement Double)
        instruction at ~line 6333.  Bitwise complement (~) is not a separate
        AP operator; it is equivalent to ``EOR`` with all-ones (our ``_complement``
        in value.py computes ``~x & 0xFFFFFFFF``).
        Unary plus is a no-op in both AP and here.
        """
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
        """Parse a primary: constant, symbol, function call, or parenthesised expr.

        AP: ``SC1%JUMP`` (apdgctt.txt ~line 4597) dispatches on encoded item type:

        ============  ===================  ============================
        AP label      Our token type       Description
        ============  ===================  ============================
        ``SCBLNK``    BLANK_ARG            Blank expression → blank value
        ``SCSINT``    INT (small)          Small integer constant (~4662)
        ``SCINT``     INT / HEX / OCT      Larger integer / hex / octal (~4853)
        ``SCGSYM``    SYMBOL               Global symbol lookup (~4674)
        ``SCLSYM``    SYMBOL (local)       Local symbol lookup (~4695)
        ``SCGSSYM``   SYMBOL + LPAREN      Global subscripted symbol (~4619)
        ``SCLSSYM``   SYMBOL + LPAREN      Local subscripted symbol (~4646)
        ``SCLITF``    LIT_EQ / LIT_L       Literal pool reference (~4994)
        ============  ===================  ============================

        The AP distinction between global/local symbols and small/large integers
        is encoded in the pre-tokenised text; our lexer produces uniform token
        types so we treat them identically here.

        Parenthesised list literals ``(a, b, c)`` are a Python-side extension:
        the AP encoder represents lists via a separate list-building mechanism;
        we detect the comma after the first element and build a LIST Value.

        Special symbols handled here: ``%`` / ``%%`` (location counters),
        ``META`` (evaluates to 0 — identity for OR chains), ``NAME`` (CNAME
        operand value in a procedure body).
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
            # P# is an ordinary SET symbol in ap-ilnotese that accumulates
            # via  P# SET S:UFV(P#)+1 — handled by normal symbol lookup.
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
        """Parse ``NAME(args)`` — FNAME call, intrinsic, or subscripted symbol.

        AP: Subscripted symbols are handled by ``SCGSSYM`` / ``SCLSSYM``
        (apdgctt.txt ~lines 4619/4646) which push a subscript-symbol control
        word, then evaluate the subscript expression, then dispatch via
        ``SCENDSSYM`` (~line 5219) when the closing paren is reached.

        Intrinsic functions (NUM, SCOR, S:UFV, CS, BA/HA/WA/DA etc.) are
        encoded as special symbol numbers; ``SC7%JUMP`` (~line 5291) dispatches
        on the intrinsic number extracted from the encoded item.  The relevant
        AP labels for each intrinsic are noted in the individual ``_eval_*``
        methods below.

        FNAME calls: in the original AP, procedure-call dispatch happens at the
        directive level, not inside the expression evaluator.  FNAMEs are a
        special class: they are invoked inline during operand evaluation via the
        ``PARTIC`` module (appartt.txt).  We replicate this by checking for an
        FNAME body before all other cases and calling ``_exec_fname`` if one is
        found and an ``executor`` is available.

        Important ordering: the FNAME check must precede all hardcoded stubs so
        that once ``S:S``, ``BC``, ``NXTIN`` etc. are defined as FNAMEs in the
        source, the real body executes rather than any simplified fallback.
        """
        upper = name.upper()
        self._consume()  # consume LPAREN

        # --- FNAME check: if symbol has an FNAME body and executor available,
        #     use the real body BEFORE any hardcoded stubs. This ensures that
        #     once S:S, BC, NXTIN etc. are defined as FNAMEs, the real body
        #     runs rather than a simplified approximation. ----------------
        if self._executor is not None:
            _entry = self._sym.lookup(name)
            if (_entry is not None
                    and _entry.proc_body is not None
                    and _entry.proc_body.is_fname):
                _arg_lists = []
                while True:
                    if self._peek() is not None and self._peek().type == TT.RPAREN:
                        break
                    _arg_lists.append(self._collect_arg_tokens())
                    if self._peek() is not None and self._peek().type == TT.COMMA:
                        self._consume()
                self._expect(TT.RPAREN)
                return self._executor._exec_fname(
                    _entry.proc_body, _arg_lists, self._frame, self._line_no)

        # --- Simple one-argument addressing functions ----------------------
        # AP: BA/HA/WA/DA/ABSVAL dispatched via ``SC7%JUMP`` (~line 5291).
        # BA=byte address (*4), HA=halfword (*2), WA=word (×1), DA=doubleword (×½),
        # ABSVAL=absolute value.  Each scales the argument by the appropriate factor.
        if upper in _ADDR_FUNCS:
            arg = self._parse_or()
            self._expect(TT.RPAREN)
            return apply_address_function(upper, arg)

        # --- CS() — returns control section number of argument -----------
        # AP: ``V%E`` / ``SCCS`` (apdgctt.txt ~line 5348), dispatched via SC7%JUMP.
        # Extracts the CSECT number from a relocatable value's type field.
        if upper == 'CS':
            arg = self._parse_or()
            self._expect(TT.RPAREN)
            if arg.kind == ValueKind.RELOCATABLE:
                return Value.absolute(arg.csect)
            return Value.absolute(0)

        # --- S:UFV() — evaluate suppressing UNDEFINED errors ---------------
        # AP: ``UFVINTRINSIC`` (apdgctt.txt ~line 5590), dispatched via SC7%JUMP.
        # "UFV" = Undefined-to-Forward-Value.  The routine strips the undefined
        # marker from ECT/EVT entries, replacing them with the pass-definition
        # field so downstream code sees a blank/zero instead of an error.
        # Used in patterns like ``S:UFV(P#)+1`` to safely read a symbol that
        # may not yet be defined.  We simply return 0 for undefined operands.
        if upper == 'S:UFV':
            arg = self._parse_or()
            self._expect(TT.RPAREN)
            # If the result is UNDEFINED, treat as 0 (forward-value semantics)
            if arg.kind == ValueKind.UNDEFINED:
                return Value.absolute(0)
            return arg

        # --- NUM() — argument count ----------------------------------------
        # AP: ``NUMINTRINSIC`` (apdgctt.txt ~line 5308), dispatched via SC7%JUMP.
        if upper == 'NUM':
            return self._eval_num()

        # --- SCOR(x, k1, k2, ...) — index of matching keyword ------------
        # AP: ``SCSCOR`` (apdgctt.txt ~line 5001), dispatched via SC7%JUMP.
        if upper == 'SCOR':
            return self._eval_scor()

        # --- TCOR — type correspondence (deferred stub) -------------------
        # AP: ``TCOR`` dispatched via SC7%JUMP (~line 5291); similar to SCOR but
        # matches on VALUE TYPE rather than value equality.  Not yet implemented.
        if upper == 'TCOR':
            self._skip_to_rparen()
            return Value.absolute(0)

        # --- S:S — conditional select (fallback stub) --------------------
        # AP: S:S is defined as an FNAME in ap-ilnotese.txt (line 26) with
        # body ``PEND AF(AF(1)+2)``.  The executor-based FNAME path above handles
        # it when ap-ilnotese has been loaded; this stub fires only when the FNAME
        # body is unavailable (e.g. in tests that don't load ap-ilnotese).
        # NOTE: ``_eval_ss`` has DIFFERENT semantics from the FNAME body — it
        # treats arg1 as a boolean (nonzero→arg2, zero→arg3), whereas the real
        # FNAME body uses arg1 as a 0-based numeric index (arg1+2 selects the
        # argument).  Use the FNAME path whenever possible.
        if upper == 'S:S':
            return self._eval_ss()

        # --- AF / CF / LF / AFA — procedure argument access ---------------
        # AP: these are special encoded symbols processed by the ``PARTIC``
        # module (appartt.txt).  During procedure body execution, ``PARTIC``
        # substitutes the actual argument tokens in place of the encoded
        # placeholder.  Our equivalent evaluates the corresponding token list
        # from the active CallFrame.  AF=operand args, CF=command-field args,
        # LF=label-field args, AFA=all operand args as a list.
        if upper in ('AF', 'CF', 'LF', 'AFA'):
            return self._eval_arg_intrinsic(upper)

        if upper == 'NAME':
            self._skip_to_rparen()
            if self._frame is not None:
                return self._frame.body.name_value
            return Value.blank()

        # --- Other proc-only intrinsics (stubs) ----------------------------
        # AP: S:NUMC (~line 5332), S:PT/S:UT (~5659/~5629), S:IFR (~5590,
        # same handler as S:UFV), S:AAD/S:RAD (address arithmetic), S:EXT
        # (external reference), S:SUM/S:LIST (structure builders), S:D/S:C/S:INT
        # (type coercions), S:FS/S:FL/S:FX/S:FR/S:DPI (float conversions).
        # All dispatched via SC7%JUMP (~line 5291).  Not yet implemented.
        if upper in ('S:KEYS', 'S:NUMC', 'S:PT', 'S:UT', 'S:IFR',
                      'S:LFR', 'S:AAD', 'S:RAD', 'S:EXT', 'S:SUM',
                      'S:LIST', 'S:D', 'S:C', 'S:INT', 'S:FS', 'S:FL',
                      'S:FX', 'S:FR', 'S:DPI'):
            self._skip_to_rparen()
            return Value.undefined()

        # --- FNAME call: SYMBOL(args) where SYMBOL is a function procedure ---
        # Collect the argument token lists (comma-separated inside the parens).
        arg_lists = []
        while True:
            if self._peek() is not None and self._peek().type == TT.RPAREN:
                break
            # Collect one argument — everything up to the next top-level comma
            # or RPAREN.
            arg_toks = self._collect_arg_tokens()
            arg_lists.append(arg_toks)
            if self._peek() is not None and self._peek().type == TT.COMMA:
                self._consume()
        self._expect(TT.RPAREN)

        entry = self._sym.lookup(name)
        if entry is None:
            self._sym.lookup_or_create(name)
            return Value.undefined()

        # If this is an FNAME with a body and we have an executor, call it.
        if (entry.proc_body is not None and entry.proc_body.is_fname
                and self._executor is not None):
            return self._executor._exec_fname(entry.proc_body, arg_lists,
                                              self._frame, self._line_no)

        # Otherwise fall back to list subscript navigation.
        indices = [evaluate_arg(a, self._sym, self._line_no, self._frame)[0]
                   for a in arg_lists]
        return _subscript(entry.value, indices)

    # ------------------------------------------------------------------
    # Procedure intrinsic helpers
    # ------------------------------------------------------------------

    def _eval_arg_toks(self, tok_lists: list) -> Value:
        """Evaluate the first token list in *tok_lists* and return its Value.

        Helper used internally when AF/AFA returns a list of argument token
        lists and we need to reduce one to a Value.
        """
        if not tok_lists:
            return Value.blank()
        v, _ = evaluate_arg(tok_lists[0], self._sym,
                             line_no=self._line_no, call_frame=self._frame)
        return v

    def _eval_arg_intrinsic(self, upper: str) -> Value:
        """Evaluate ``AF(n)``, ``CF(n)``, ``LF(n)``, or bare ``AFA``.

        AP: Handled by the ``PARTIC`` module (appartt.txt), which scans the
        encoded procedure body and replaces AF/CF/LF placeholders with the
        actual argument token sequences from the call site.  In the original,
        this substitution happens at the encoded-text level before SCAN even
        runs; here we evaluate the corresponding token list from the active
        ``CallFrame`` at expression-evaluation time.

        - ``AF(n)`` — n-th operand argument (1-based).  Blank if n > num_args.
        - ``CF(n)`` — n-th command-field argument: CF(1)=base command name,
          CF(2)=first modifier token, etc.
        - ``LF(n)`` — n-th label-field argument (usually only LF(1) is used).
        - ``AFA``   — bare (no subscript); returns all operand args as a LIST.

        Outside an active procedure frame all forms return ``Value.undefined()``.
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
        """``NUM(expr)`` — count the items in an expression.

        AP: ``NUMINTRINSIC`` (apdgctt.txt ~line 5308), dispatched via
        ``SC7%JUMP`` (~line 5291).  The original counts the ECT entries
        consumed by evaluating the argument; LIST items contribute their
        element count.  Bare ``NUM(AF)`` / ``NUM(CF)`` / ``NUM(LF)`` count
        the argument slots in the call frame.

        Forms:
          - ``NUM(list_symbol)`` → number of elements in the list.
          - ``NUM(scalar)``      → 1.
          - ``NUM(AF)``          → number of operand args in current frame (0 outside).
          - ``NUM(CF)``          → number of command-field args in current frame.
          - ``NUM(AF(n))``       → element count of the n-th operand arg.

        The frame-specific forms (bare ``AF``/``CF``/``LF``) are detected by
        peeking ahead for a symbol token not followed by ``(``.  This matches
        the AP encoding where ``AF`` alone is a special encoded token, not a
        symbol+subscript pair.
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
        """``SCOR(x, k1, k2, ..., kn)`` — search list, return 1-based position.

        AP: ``SCSCOR`` (apdgctt.txt ~line 5001), dispatched via ``SC7%JUMP``.
        Iterates over ``k1..kn`` comparing each to ``x``; returns the 1-based
        position of the first match, or 0 if not found.

        Blank arguments (consecutive commas → empty ECT entries) are skipped
        and never match.  Our Python implementation detects blank arguments by
        peeking for a COMMA or RPAREN immediately after consuming a COMMA
        (two consecutive commas = blank entry).

        Used in ``BC`` procedure body to look up condition codes:
        ``SCOR(AF(2), GE, LE, EQ, AZ, ..., L, G, NE, ANZ, ...)``
        returns the index of the condition-code keyword, which then becomes
        the bit-field value OR'd into the branch instruction word.
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
        """Fallback stub for ``S:S`` when no FNAME body is available.

        AP: ``S:S`` is defined as an FNAME in ap-ilnotese.txt (label ``S:S``,
        line 26) with body ``PEND AF(AF(1)+2)``.  This stub is used only when
        that FNAME has not yet been loaded (e.g. isolated unit tests).

        **Warning — semantics differ from the real FNAME body.**  This stub
        treats ``S:S(cond, t, f)`` as a ternary: ``cond != 0`` → ``t``,
        ``cond == 0`` → ``f``.  The real body does numeric index selection:
        ``S:S(n, v0, v1, ...)`` selects ``AF(n+2)``, so ``S:S(0,a,b)=a``,
        ``S:S(1,a,b)=b``.  The stub is correct for boolean-convention usage
        (where ``cond`` is 0 or -1) only when the caller follows the pattern
        ``S:S(bool, t, f)`` — which happens to agree with the FNAME body for
        ``cond=-1`` (true: FNAME gives ``AF(1)=-1``, not ``t``; but for typical
        use ``t`` is the desired true-branch value at position 2 when cond=0).
        In practice, always prefer the FNAME path by loading ap-ilnotese first.
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
        """Consume tokens up to and including the matching RPAREN.

        Used to skip over unimplemented or stubbed intrinsics
        (TCOR, S:NUMC, S:PT, etc.) without leaving the token stream in an
        inconsistent state.  No AP equivalent — utility method.
        """
        depth = 1
        while depth > 0 and self._pos < len(self._tokens):
            tok = self._consume()
            if tok is None:
                break
            if tok.type == TT.LPAREN:
                depth += 1
            elif tok.type == TT.RPAREN:
                depth -= 1

    def _collect_arg_tokens(self) -> List[Token]:
        """Collect tokens for one FNAME argument, respecting paren depth.

        Stops (without consuming) at a top-level COMMA or RPAREN, so a
        series of calls collects the comma-separated arguments inside a
        function call.

        AP: No direct equivalent.  The original AP receives pre-tokenised
        encoded text; argument boundaries are marked by the encoder (Phase 1).
        This method is needed because Python receives a flat token list and
        must re-discover argument boundaries when invoking FNAME bodies inline
        from within expression evaluation.
        """
        toks: List[Token] = []
        depth = 0
        while self._pos < len(self._tokens):
            tok = self._peek()
            if tok is None:
                break
            if tok.type == TT.RPAREN and depth == 0:
                break
            if tok.type == TT.COMMA and depth == 0:
                break
            self._consume()
            toks.append(tok)
            if tok.type == TT.LPAREN:
                depth += 1
            elif tok.type == TT.RPAREN:
                depth -= 1
        return toks


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def evaluate_arg(tokens: List[Token], sym: SymbolTable,
                 line_no: int = 0,
                 call_frame=None,
                 executor=None) -> Tuple[Value, List[str]]:
    """Evaluate a single argument-position token list.

    Top-level convenience wrapper around ``ExpressionEvaluator``.

    AP: corresponds to calling ``EV1OPRNDEXP`` or ``EV%CLN%OPRND``
    (apdgctt.txt ~line 4557) for a single expression.

    *call_frame* — optional ``CallFrame``; provides AF/CF/LF/NAME context
    when evaluating inside a procedure body.

    *executor* — optional ``DefPass``/``GenPass`` instance; enables FNAME
    bodies to be called inline during expression evaluation (the
    ``_exec_fname`` mechanism).

    Returns ``(value, error_list)``.  ``error_list`` is empty on success;
    assembler errors (division by zero, truncation) are returned as strings
    rather than raised, so partial results can still be used.
    """
    ev = ExpressionEvaluator(tokens, sym, line_no, call_frame=call_frame,
                             executor=executor)
    try:
        v = ev.evaluate()
    except AssemblerError as exc:
        return Value.undefined(), [str(exc)]
    return v, ev.errors
