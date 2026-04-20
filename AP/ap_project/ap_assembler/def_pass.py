"""
ap_assembler/def_pass.py — Phase 2: Definition Pass.

Walks the Statement list produced by the lexer and builds the symbol table
by processing each directive.  This is the Python equivalent of the APDG
module's ``DEFGEN`` function operating in DEF (definition) mode.

The DEF pass does **not** emit any object code.  Its sole job is to determine
the value of every symbol so that the GEN pass can resolve all references.

Processing model
----------------
Statements are processed sequentially.  DO / DO1 / ELSE / FIN directives
alter which statements are skipped or repeated by manipulating ``self.pos``,
the index into the statement list.

Directive dispatch
------------------
The command field is split at the first comma:
  ``'GEN,8,24'``  →  base=``'GEN'``,  modifier=``'8,24'``

The base name is looked up in ``_HANDLERS`` and the corresponding method is
called with ``(stmt, modifier)``.  Unknown base names (instruction mnemonics,
procedure calls) are handled by ``_handle_instruction``.

Storage allocation (DEF pass)
------------------------------
For each storage-allocating directive the DEF pass:
  1. Defines the label at the current LC.
  2. Advances the LC by the number of bytes that directive will produce.

The GEN pass will later repeat these same operations and emit actual bytes.

Procedure stubs
---------------
PROC / PEND / CNAME / FNAME are currently stubbed: the procedure body is
skipped so that storage allocations inside the body are not counted at the
call site.  Full procedure expansion is deferred to a future ``procedure.py``
module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .do_control import DoFrame, find_else_fin, find_pend, find_label
from .expression import evaluate_arg
from .lexer import ArgTokenizer, Statement, TT, Token
from .procedure import ProcedureBody, CallFrame
from .symbol_table import CsectKind, SymbolTable, PASS_DEF
from .value import Value, ValueKind, Resolution, AssemblerError


# ---------------------------------------------------------------------------
# Label field helpers: subscripted label assignment
# ---------------------------------------------------------------------------

def _parse_subscript_label(label: str):
    """
    Parse a raw label string that may contain a subscript.

    Returns ``(name, [index_str, ...])`` if the label is subscripted, or
    ``None`` if it is a plain symbol name.

    Parenthesis depth is tracked so that nested subscripts like
    ``IAL(IAN(INL,:SC))`` correctly yield ``('IAL', ['IAN(INL,:SC)'])``
    rather than splitting at the inner comma.

    Examples::

        _parse_subscript_label('SIMPLE')            → None
        _parse_subscript_label('IAN(I,J)')          → ('IAN', ['I', 'J'])
        _parse_subscript_label('IAN(INL,:TY)')      → ('IAN', ['INL', ':TY'])
        _parse_subscript_label('IAL(IAN(INL,:SC))') → ('IAL', ['IAN(INL,:SC)'])
    """
    if '(' not in label:
        return None

    paren = label.index('(')
    name  = label[:paren].strip()
    inner = label[paren + 1:]

    # Strip the closing ')' (the outermost one)
    if inner.endswith(')'):
        inner = inner[:-1]

    # Split on commas at depth 0
    indices: list = []
    current: list = []
    depth = 0
    for ch in inner:
        if ch == '(':
            depth += 1
            current.append(ch)
        elif ch == ')':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            indices.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        indices.append(''.join(current).strip())

    if not name or not indices:
        return None
    return name, indices


def _set_subscript(root: 'Value', indices: list, value: 'Value') -> 'Value':
    """
    Return a new Value that is *root* with the element at *indices* replaced
    by *value*.  Never mutates *root*.

    *indices* is a list of 1-based integer indices, one per nesting level.

    Growth rules (matching DFNE14/DFNE21/DFNE22 in the original APDG source):

    When *root* is a LIST:
      - Index in range  → replace that element (others unchanged).
      - Index out of range → extend with BLANK pads to reach the position.

    When *root* is a scalar (non-list):
      - Index == 1 → replace the scalar directly.
      - Index > 1  → discard the scalar entirely, pad with BLANKs, then
                     place *value* at position *idx*.  This matches the
                     original's DFNE21/DFNE22 path where a SPINT (special
                     integer initialisation value) is replaced with BLANKs
                     rather than preserved as element 1.
    """
    if not indices:
        return value

    idx  = max(1, indices[0])   # 1-based; clamp negative/zero to 1
    rest = indices[1:]

    if root.kind == ValueKind.LIST:
        # List case: copy existing elements, replace target.
        items = list(root.items)
        # Extend with BLANKs if needed.
        while len(items) < idx:
            items.append(Value.blank())
        target       = items[idx - 1]
        items[idx - 1] = _set_subscript(target, rest, value) if rest else value
    else:
        # Scalar case.
        if idx == 1:
            # Replace the scalar directly (treat as 1-element list).
            inner = _set_subscript(root, rest, value) if rest else value
            items = [inner]
        else:
            # Discard the scalar; pad with BLANKs up to the target position.
            items = [Value.blank()] * (idx - 1)
            inner = _set_subscript(Value.blank(), rest, value) if rest else value
            items.append(inner)

    return Value.list_val(items)


# ---------------------------------------------------------------------------
# Error record
# ---------------------------------------------------------------------------

@dataclass
class AssemblyError:
    line_no:  int
    message:  str
    severity: int = 1    # 0 = commentary, 1 = warning, 2+ = error

    def __str__(self) -> str:
        tag = {0: '*', 1: 'W', 2: 'E'}.get(self.severity, 'E')
        return f"[{tag}] Line {self.line_no}: {self.message}"


# ---------------------------------------------------------------------------
# DefPass
# ---------------------------------------------------------------------------

class DefPass:
    """
    The AP assembler's definition (Phase 2) pass.

    Usage::

        stmts = list(tokenize_text(source))
        sym   = SymbolTable()
        dp    = DefPass(stmts, sym)
        errors = dp.run()
    """

    def __init__(self, stmts: List[Statement], sym: SymbolTable):
        self.stmts:    List[Statement]  = stmts
        self.sym:      SymbolTable      = sym
        self.errors:   List[AssemblyError] = []
        self.pos:      int              = 0       # current statement index
        self._do_stack: List[DoFrame]  = []       # active DO frames
        self._call_stack: List[CallFrame] = []    # procedure call stack

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> List[AssemblyError]:
        """
        Execute the DEF pass over all statements.

        Returns the list of errors/warnings encountered.
        """
        self.sym._pass = PASS_DEF
        self.pos = 0
        while self.pos < len(self.stmts):
            stmt = self.stmts[self.pos]
            if not stmt.is_comment and stmt.command is not None:
                self._dispatch(stmt)
            self.pos += 1
        return self.errors

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, stmt: Statement) -> None:
        """Parse the command field and call the appropriate handler."""
        cmd = stmt.command
        if not cmd:
            return

        # Split "CMD,modifier" → base="CMD", modifier="..."
        base, _, modifier = cmd.partition(',')
        base = base.upper()

        # Check for CNAME/FNAME procedure call BEFORE the handler map.
        # This check runs in both DefPass and GenPass (no override needed).
        if base not in _HANDLER_MAP:
            entry = self.sym.lookup(base)
            if entry is not None and entry.proc_body is not None:
                self._call_procedure(stmt, entry.proc_body)
                return

        # Look up the method name, then resolve it on *self* so that
        # subclass overrides (GenPass) are found through Python's MRO.
        method_name = _HANDLER_MAP.get(base)
        if method_name is not None:
            getattr(self, method_name)(stmt, modifier)
        else:
            self._handle_instruction(stmt)

    # ------------------------------------------------------------------
    # Expression evaluation helpers
    # ------------------------------------------------------------------

    def _eval(self, arg_tokens: List[Token]) -> Value:
        """Evaluate one argument-position token list."""
        frame = self._call_stack[-1] if self._call_stack else None
        v, errs = evaluate_arg(arg_tokens, self.sym, call_frame=frame)
        for msg in errs:
            self._err(0, msg)
        return v

    def _eval_arg(self, stmt: Statement, n: int,
                  default: Value = None) -> Value:
        """Return the value of argument position n (0-based)."""
        if n < len(stmt.args):
            return self._eval(stmt.args[n])
        if default is not None:
            return default
        return Value.blank()

    def _eval_modifier_expr(self, modifier: str,
                            line_no: int = 0) -> Optional[Value]:
        """
        Tokenise and evaluate *modifier* (a raw string from the command field)
        as a single expression.  Returns None if the string is empty or
        cannot be tokenised.
        """
        if not modifier:
            return None
        from .lexer import ArgTokenizer
        tok_lists = ArgTokenizer(modifier.strip(), line_no=line_no,
                                 start_col=0).tokenize()
        if not tok_lists:
            return None
        return self._eval(tok_lists[0])

    def _eval_index_str(self, raw: str, line_no: int = 0) -> int:
        """
        Tokenise and evaluate a raw subscript-index string.

        Used when parsing subscripted label assignments such as
        ``IAN(INL,:TY) SET value`` where ``INL`` and ``:TY`` are the
        raw index strings.

        Returns the 1-based integer index.  If the result is UNDEFINED
        (a forward reference during the DEF pass) or BLANK, returns 1 as
        a safe default so that the list is at least extended to that position.
        """
        from .lexer import ArgTokenizer
        tok_lists = ArgTokenizer(raw.strip(), line_no=line_no,
                                 start_col=0).tokenize()
        if not tok_lists:
            return 1
        v, _ = evaluate_arg(tok_lists[0], self.sym)
        if v.kind == ValueKind.ABSOLUTE:
            return max(1, v.int_val)
        return 1   # UNDEFINED / BLANK → safe default

    def _eval_modifier_int(self, modifier: str, default: int) -> int:
        """Parse a plain integer from a command-field modifier string."""
        if not modifier:
            return default
        # The modifier may itself be a comma-separated list (e.g., GEN,8,24)
        first = modifier.split(',')[0]
        try:
            return int(first)
        except ValueError:
            return default

    def _require_int(self, v: Value, stmt: Statement,
                     default: int = 0) -> int:
        """Extract an integer from a Value, reporting an error if not possible."""
        if v.kind == ValueKind.ABSOLUTE:
            return v.int_val
        if v.kind not in (ValueKind.BLANK, ValueKind.UNDEFINED):
            self._err(stmt.line_no, "Integer constant required")
        return default

    def _eval_all_args(self, stmt: Statement) -> Value:
        """
        Evaluate all argument positions of a statement.

        A single argument returns its scalar value.
        Multiple arguments (X EQU 1,2,3) return a LIST Value.
        A parenthesised multi-element argument (X EQU (1,2)) is already
        handled by the expression evaluator returning a LIST Value.
        """
        if not stmt.args:
            return Value.blank()
        if len(stmt.args) == 1:
            return self._eval(stmt.args[0])
        return Value.list_val([self._eval(a) for a in stmt.args])

    # ------------------------------------------------------------------
    # Label definition helper
    # ------------------------------------------------------------------

    def _define_label(self, stmt: Statement,
                      value: Value = None,
                      is_set: bool = False) -> None:
        """
        Define the label field of *stmt* to *value* (or the current $ if
        value is None).  No-ops if the label is absent.

        If the label contains a subscript (e.g. ``IAN(INL,:TY)``), performs
        a subscripted element replacement on the existing symbol value rather
        than a whole-symbol replacement.  The symbol is always stored with
        SET semantics (re-definable) when a subscript is used, matching the
        original assembler's behaviour (DFNE10/DFNE11 in apdgctt.txt).
        """
        if not stmt.label:
            return
        if value is None:
            value = self.sym.dollar_value()

        # Inside a procedure body, the special label 'LF' means "define
        # the call-site label at the current LC" — it uses the label from
        # the call site (frame.label_args[0]), not the literal symbol 'LF'.
        label = stmt.label
        if label == 'LF' and self._call_stack:
            frame = self._call_stack[-1]
            if frame.label_args:
                # Re-tokenise and extract the symbol name from the first label arg
                toks = frame.label_args[0]
                if toks and toks[0].type == TT.SYMBOL:
                    label = toks[0].value
                else:
                    return   # blank label at call site — no definition
            else:
                return   # no label at call site

        # Use the (possibly substituted) label for all further processing
        parsed = _parse_subscript_label(label)
        if parsed is None:
            self.sym.define(label, value, is_set=is_set)
            return
        name, index_strs = parsed
        indices = [self._eval_index_str(s, stmt.line_no) for s in index_strs]
        entry   = self.sym.lookup_or_create(name)
        new_root = _set_subscript(entry.value, indices, value)
        self.sym.define(name, new_root, is_set=True)
        return

        parsed = _parse_subscript_label(stmt.label)
        if parsed is None:
            # Plain label — existing path unchanged.
            self.sym.define(stmt.label, value, is_set=is_set)
            return

        # Subscripted label: navigate into the list and replace one element.
        name, index_strs = parsed
        indices = [self._eval_index_str(s, stmt.line_no) for s in index_strs]
        entry   = self.sym.lookup_or_create(name)
        new_root = _set_subscript(entry.value, indices, value)
        # Subscripted assignment always uses SET semantics.
        self.sym.define(name, new_root, is_set=True)

    # ------------------------------------------------------------------
    # Error helpers
    # ------------------------------------------------------------------

    def _err(self, line_no: int, msg: str, severity: int = 2) -> None:
        self.errors.append(AssemblyError(line_no, msg, severity))

    def _warn(self, line_no: int, msg: str) -> None:
        self._err(line_no, msg, severity=1)

    # ------------------------------------------------------------------
    # ----------------------------------------------------------------
    # Directive handlers
    # ----------------------------------------------------------------
    # ------------------------------------------------------------------

    # --- EQU / SET --------------------------------------------------

    def _handle_equ(self, stmt: Statement, modifier: str) -> None:
        """EQU: define label = expr, or a list if multiple args (not re-definable)."""
        v = self._eval_all_args(stmt)
        self._define_label(stmt, v, is_set=False)

    def _handle_set(self, stmt: Statement, modifier: str) -> None:
        """SET: define label = expr, or a list if multiple args (re-definable)."""
        v = self._eval_all_args(stmt)
        self._define_label(stmt, v, is_set=True)

    # --- RES --------------------------------------------------------

    def _handle_res(self, stmt: Statement, modifier: str) -> None:
        """
        RES[,unit] count

        Reserve  unit × count  bytes.
        Default unit = 4 (one word).  Label is defined at the current LC
        *before* the reservation.
        """
        self._define_label(stmt)
        unit  = self._eval_modifier_int(modifier, 4)
        if unit <= 0:
            self._err(stmt.line_no, f"RES: unit must be positive, got {unit}")
            unit = 4
        count_v = self._eval_arg(stmt, 0, Value.absolute(0))
        count   = self._require_int(count_v, stmt, 0)
        if count < 0:
            self._err(stmt.line_no, f"RES: count must be non-negative, got {count}")
            count = 0
        self.sym.advance_lc(unit * count)

    # --- DATA -------------------------------------------------------

    def _handle_data(self, stmt: Statement, modifier: str) -> None:
        """
        DATA[,bits] value, ...

        Generate one value per argument, each occupying *bits* bits (default
        32).  Label defined at the current LC before any values are emitted.
        """
        self._define_label(stmt)
        bits    = self._eval_modifier_int(modifier, 32)
        if bits <= 0 or bits > 64:
            self._err(stmt.line_no, f"DATA: bit width {bits} out of range")
            bits = 32
        nbytes = max(1, (bits + 7) // 8)

        for arg in stmt.args:
            self._eval(arg)                # for forward-reference tracking
            self.sym.advance_lc(nbytes)

    # --- TEXT / TEXTC -----------------------------------------------

    def _handle_text(self, stmt: Statement, modifier: str) -> None:
        """
        TEXT [,'f'] 'string'

        Store characters packed 4/word, left-adjusted, right-padded with
        nulls to a word boundary.  Label defined at the current LC.
        """
        self._define_label(stmt)
        for arg in stmt.args:
            if arg and arg[0].type == TT.CHARSTR:
                nchars  = len(arg[0].value)
                nbytes  = ((nchars + 3) // 4) * 4   # round to word
            else:
                nbytes = 4                            # unknown → one word
            self.sym.advance_lc(nbytes)

    def _handle_textc(self, stmt: Statement, modifier: str) -> None:
        """
        TEXTC 'string'

        Like TEXT but the first byte of the generated area is the count of
        *significant* characters (not counting trailing pads).
        """
        self._define_label(stmt)
        for arg in stmt.args:
            if arg and arg[0].type == TT.CHARSTR:
                nchars = len(arg[0].value)
                nbytes = ((nchars + 1 + 3) // 4) * 4   # +1 for count byte
            else:
                nbytes = 4
            self.sym.advance_lc(nbytes)

    # --- BOUND ------------------------------------------------------

    def _handle_bound(self, stmt: Statement, modifier: str) -> None:
        """
        BOUND n

        Advance LC to the next multiple of n bytes (n must be a positive
        power of 2, 1–2048).
        """
        v = self._eval_arg(stmt, 0, Value.absolute(4))
        n = self._require_int(v, stmt, 4)
        if n <= 0 or (n & (n - 1)) != 0 or n > 2048:
            self._err(stmt.line_no,
                      f"BOUND: {n} is not a positive power-of-2 ≤ 2048")
            n = 4
        self.sym.align_lc(n)

    # --- ORG / LOC --------------------------------------------------

    def _handle_org(self, stmt: Statement, modifier: str) -> None:
        """
        ORG[,res] [address]

        Set *both* location counters (exec and load) to the given address.
        If blank, both are set to 0.
        """
        self._do_org_or_loc(stmt, modifier, move_load=True)

    def _handle_loc(self, stmt: Statement, modifier: str) -> None:
        """
        LOC[,res] [address]

        Set the *execution* LC only; the load LC is unchanged.
        """
        self._do_org_or_loc(stmt, modifier, move_load=False)

    def _do_org_or_loc(self, stmt: Statement, modifier: str,
                       move_load: bool) -> None:
        v = self._eval_arg(stmt, 0, Value.absolute(0))
        if v.kind == ValueKind.RELOCATABLE:
            self.sym.set_exec_lc(v.int_val, v.csect)
        elif v.kind in (ValueKind.ABSOLUTE, ValueKind.BLANK):
            self.sym.set_exec_lc(v.int_val if v.kind == ValueKind.ABSOLUTE else 0)
        else:
            self._err(stmt.line_no, "ORG/LOC: address expression required")
        if move_load:
            cs = self.sym.current_section
            cs.load_lc = cs.exec_lc
        self._define_label(stmt)

    # --- GEN --------------------------------------------------------

    def _handle_gen(self, stmt: Statement, modifier: str) -> None:
        """
        GEN[,f1,f2,...] value, ...

        Generate packed bit-field data.  Each fi is a field width in bits;
        consecutive fields are packed into complete 32-bit words.
        In the DEF pass we only need to advance the LC by the total size.
        """
        self._define_label(stmt)
        if modifier:
            try:
                field_bits = [int(x) for x in modifier.split(',') if x]
                total_bits = sum(field_bits)
                # Round up to whole words
                nbytes = ((total_bits + 31) // 32) * 4
            except ValueError:
                nbytes = 4
        else:
            nbytes = 4
        self.sym.advance_lc(nbytes)

    # --- COM --------------------------------------------------------

    def _handle_com(self, stmt: Statement, modifier: str) -> None:
        """
        COM[,f1,f2,...] field_specs...

        Command definition directive.  In the DEF pass, just defines the label
        and advances the LC by 0 (COM generates a command template, not code).
        The actual command definition requires the full procedure engine.
        """
        # COM defines a command template with no storage allocation.
        if stmt.label:
            self.sym.define(stmt.label, Value.absolute(0))

    # --- S:SIN ------------------------------------------------------

    def _handle_ssin(self, stmt: Statement, modifier: str) -> None:
        """
        S:SIN[,type] opcode

        Standard instruction definition.  Defines the label as an instruction
        with the given opcode.  No storage is allocated (it's a definition,
        not emission).
        """
        if stmt.label:
            v = self._eval_arg(stmt, 0, Value.absolute(0))
            self.sym.define(stmt.label, v)

    # --- Section directives -----------------------------------------

    def _handle_csect(self, stmt: Statement, modifier: str) -> None:
        """CSECT: open a new (or re-enter an existing named) code section."""
        name = stmt.label or ''
        cs   = self.sym.open_section(CsectKind.CSECT, name)
        if stmt.label:
            self.sym.define(stmt.label,
                            Value.relocatable(cs.number, 0, Resolution.WORD))

    def _handle_dsect(self, stmt: Statement, modifier: str) -> None:
        """DSECT: dummy section (defines layout; no object output)."""
        if not stmt.label:
            self._err(stmt.line_no, "DSECT requires a label")
            return
        cs = self.sym.open_section(CsectKind.DSECT, stmt.label)
        self.sym.define(stmt.label,
                        Value.relocatable(cs.number, 0, Resolution.WORD))
        self.sym.mark_external(stmt.label, 'def')

    def _handle_asect(self, stmt: Statement, modifier: str) -> None:
        """ASECT: switch to the absolute section (section 0)."""
        self.sym.switch_to_section(0)
        if stmt.label:
            self.sym.define(stmt.label,
                            Value.relocatable(0, self.sym.exec_lc()))

    def _handle_psect(self, stmt: Statement, modifier: str) -> None:
        """PSECT: protected section (like CSECT but with access protection)."""
        name = stmt.label or ''
        cs   = self.sym.open_section(CsectKind.PSECT, name)
        if stmt.label:
            self.sym.define(stmt.label,
                            Value.relocatable(cs.number, 0, Resolution.WORD))

    def _handle_usect(self, stmt: Statement, modifier: str) -> None:
        """USECT name: re-enter a previously opened named section."""
        # The section name comes from the first argument token
        name = ''
        if stmt.args and stmt.args[0] and stmt.args[0][0].type == TT.SYMBOL:
            name = stmt.args[0][0].value
        self.sym.open_section(CsectKind.USECT, name)

    # --- External linkage -------------------------------------------

    def _handle_def(self, stmt: Statement, modifier: str) -> None:
        """DEF sym,...: declare symbols as public external definitions."""
        for arg in stmt.args:
            if arg and arg[0].type == TT.SYMBOL:
                self.sym.mark_external(arg[0].value, 'def')

    def _handle_ref(self, stmt: Statement, modifier: str) -> None:
        """REF sym,...: declare symbols as external references."""
        for arg in stmt.args:
            if arg and arg[0].type == TT.SYMBOL:
                self.sym.mark_external(arg[0].value, 'ref')

    def _handle_sref(self, stmt: Statement, modifier: str) -> None:
        """SREF sym,...: secondary external references."""
        for arg in stmt.args:
            if arg and arg[0].type == TT.SYMBOL:
                self.sym.mark_external(arg[0].value, 'sref')

    # --- Symbol scope -----------------------------------------------

    def _handle_local(self, stmt: Statement, modifier: str) -> None:
        """LOCAL sym,...: declare symbols as local to the current scope."""
        for arg in stmt.args:
            if arg and arg[0].type == TT.SYMBOL:
                self.sym.declare_local(arg[0].value)

    def _handle_open(self, stmt: Statement, modifier: str) -> None:
        """OPEN sym,...: make symbols visible beyond the current scope."""
        # Handled in Phase 1 (APNCD); no-op in Phase 2.
        pass

    def _handle_close(self, stmt: Statement, modifier: str) -> None:
        """CLOSE sym,...: limit symbol visibility to the current scope."""
        # Handled in Phase 1; no-op in Phase 2.
        pass

    # --- SYSTEM / listing directives --------------------------------

    def _handle_system(self, stmt: Statement, modifier: str) -> None:
        """SYSTEM name: include a system file (handled in Phase 1; no-op here)."""
        pass

    def _handle_title(self, stmt: Statement, modifier: str) -> None:
        pass   # listing only

    def _handle_space(self, stmt: Statement, modifier: str) -> None:
        pass   # listing only

    def _handle_page(self, stmt: Statement, modifier: str) -> None:
        pass   # listing only

    def _handle_pcc(self, stmt: Statement, modifier: str) -> None:
        pass   # listing only

    def _handle_psr(self, stmt: Statement, modifier: str) -> None:
        pass   # listing only

    def _handle_psys(self, stmt: Statement, modifier: str) -> None:
        pass   # listing only

    def _handle_list(self, stmt: Statement, modifier: str) -> None:
        pass   # listing only

    def _handle_disp(self, stmt: Statement, modifier: str) -> None:
        pass   # DISP is gen-pass only (values not yet known)

    def _handle_error(self, stmt: Statement, modifier: str) -> None:
        """ERROR[,level[,cond]] 'msg': record an assembly-time error message."""
        # Only emit in GEN pass; skip silently in DEF pass.
        pass

    def _handle_socw(self, stmt: Statement, modifier: str) -> None:
        """SOCW: structured object code word control (ignored in DEF pass)."""
        pass

    # --- Procedure stubs (full engine deferred) ----------------------

    def _handle_cname(self, stmt: Statement, modifier: str) -> None:
        """CNAME: define a command-name procedure (normal, non-returning)."""
        self._define_procedure(stmt, is_fname=False)

    def _handle_fname(self, stmt: Statement, modifier: str) -> None:
        """FNAME: define a function-name procedure (PEND returns a value)."""
        self._define_procedure(stmt, is_fname=True)

    def _define_procedure(self, stmt: Statement, is_fname: bool) -> None:
        """
        Common logic for CNAME and FNAME.

        Finds the matching PROC/PEND block (if present) and stores a
        ProcedureBody in the symbol table keyed on the label.
        If there is no matching PROC, stores Value.absolute(0) as a
        placeholder (e.g. for forward-declared procedures).
        """
        if not stmt.label:
            # No label → nothing to register; skip to PEND
            pend_idx = find_pend(self.stmts, self.pos + 1)
            self.pos = pend_idx
            return

        # Evaluate the CNAME operand (e.g. the opcode value X'32')
        name_value = self._eval_arg(stmt, 0, Value.blank())

        # Find the PROC line and the matching PEND
        proc_idx = None
        for i in range(self.pos + 1, len(self.stmts)):
            s = self.stmts[i]
            if s.is_comment or s.command is None:
                continue
            base = s.command.partition(',')[0].upper()
            if base == 'PROC':
                proc_idx = i
                break
            # Any other non-comment directive before PROC → no body
            break

        if proc_idx is None:
            # No PROC follows — forward declaration only
            self.sym.define(stmt.label, Value.absolute(0))
            # Do NOT skip ahead; the next PROC/PEND pair belongs elsewhere
            return

        pend_idx = find_pend(self.stmts, proc_idx + 1)
        body = ProcedureBody(
            stmts      = self.stmts,
            body_start = proc_idx + 1,   # first statement inside body
            pend_index = pend_idx,
            name_value = name_value,
            is_fname   = is_fname,
        )
        self.sym.define(stmt.label, Value.absolute(0), is_set=True)
        entry = self.sym.lookup(stmt.label)
        entry.proc_body = body            # attach body to the entry

        # Skip past the PEND — the main loop will +1 past it
        self.pos = pend_idx

    def _handle_proc(self, stmt: Statement, modifier: str) -> None:
        """
        PROC: begin a procedure body.

        Normally reached only when a PROC appears without a preceding
        CNAME/FNAME on the same definition sweep — i.e., on the source
        level (error) or when called recursively (shouldn't happen at
        source level).  During a CNAME definition, _define_procedure
        already advanced self.pos past the PEND, so PROC is never
        dispatched separately in that case.

        At source level, treat as: skip to matching PEND (error body).
        """
        end = find_pend(self.stmts, self.pos + 1)
        self.pos = end

    def _handle_pend(self, stmt: Statement, modifier: str) -> None:
        """
        PEND: end of a procedure body.

        During definition: reached only if PROC was skipped (source-level
        PROC without CNAME), so this is a no-op.

        During execution (procedure call): pop the call frame and resume
        the caller.  For FNAME, evaluate the PEND operand and store it
        as the frame's return value.
        """
        if not self._call_stack:
            return   # PEND at source level — ignore

        frame = self._call_stack[-1]

        # FNAME: evaluate PEND operand to get the return value
        if frame.body.is_fname and stmt.args:
            frame.fname_result = self._eval_arg(stmt, 0, Value.blank())

        # Pop the frame and restore the caller context
        self._call_stack.pop()
        self.stmts   = frame.return_stmts
        self.pos     = frame.return_pos    # will be +1'd by the outer loop
        self._do_stack = frame.do_stack

    # --- DO / DO1 / ELSE / FIN / GOTO -------------------------------

    def _handle_do(self, stmt: Statement, modifier: str) -> None:
        """
        DO expr

        If expr <= 0: skip body to ELSE (if present) or FIN; execute the
        ELSE section once.
        If expr > 0:  execute body expr times; skip ELSE section.

        The DO label (if any) is SET to 0 when skipped, or to the current
        iteration number (1-based) when executing.
        """
        v = self._eval_arg(stmt, 0, Value.absolute(0))
        n = self._require_int(v, stmt, 0)

        else_idx, fin_idx = find_else_fin(self.stmts, self.pos + 1)

        if n <= 0:
            # Skip body; jump to ELSE section (or past FIN if no ELSE)
            self._define_label(stmt, Value.absolute(0), is_set=True)
            if else_idx >= 0:
                # Push a frame so ELSE/FIN can terminate correctly
                frame = DoFrame(
                    body_start = else_idx + 1,
                    target     = 1,
                    current    = 1,
                    label      = stmt.label,
                    else_idx   = else_idx,
                    fin_idx    = fin_idx,
                )
                self._do_stack.append(frame)
                self.pos = else_idx   # process ELSE next; it will be a no-op
            else:
                self.pos = fin_idx    # jump to FIN; it will pop nothing (no frame)
        else:
            # Execute body n times
            self._define_label(stmt, Value.absolute(1), is_set=True)
            frame = DoFrame(
                body_start = self.pos + 1,
                target     = n,
                current    = 1,
                label      = stmt.label,
                else_idx   = else_idx,
                fin_idx    = fin_idx,
            )
            self._do_stack.append(frame)
            # Continue naturally into the body

    def _handle_do1(self, stmt: Statement, modifier: str) -> None:
        """
        DO1 expr

        Repeat the single statement that follows this one.
        expr < 1 → skip next statement.
        expr = 1 → execute it once (normal; DO1 is a no-op).
        expr > 1 → execute it expr times.
        """
        self._define_label(stmt)    # label defined normally (at current LC)
        v = self._eval_arg(stmt, 0, Value.absolute(0))
        n = self._require_int(v, stmt, 0)

        next_pos = self.pos + 1
        if n < 1:
            # Skip the next statement
            if next_pos < len(self.stmts):
                self.pos = next_pos   # loop will +1 again → skip it
        elif n == 1:
            pass   # normal execution, nothing special
        else:
            # Repeat next statement n times
            if next_pos < len(self.stmts):
                next_stmt = self.stmts[next_pos]
                if not next_stmt.is_comment and next_stmt.command is not None:
                    for _ in range(n):
                        self._dispatch(next_stmt)
                self.pos = next_pos  # loop +1 will skip past it

    def _handle_else(self, stmt: Statement, modifier: str) -> None:
        """
        ELSE

        Loop-back point and separator between the body and the else section.
        If there are remaining iterations, jump back to body_start.
        If iterations are exhausted, skip forward to FIN.
        """
        if not self._do_stack:
            self._err(stmt.line_no, "ELSE without matching DO")
            return

        frame = self._do_stack[-1]

        if not frame.done:
            # More iterations: loop back
            frame.next_iteration()
            if frame.label:
                self.sym.define(frame.label,
                                Value.absolute(frame.current), is_set=True)
            self.pos = frame.body_start - 1   # -1 because loop will +1
        else:
            # Exhausted: skip the ELSE section to FIN
            if frame.fin_idx >= 0:
                self.pos = frame.fin_idx - 1  # FIN will pop the frame
            self._do_stack.pop()

    def _handle_fin(self, stmt: Statement, modifier: str) -> None:
        """
        FIN

        If there are remaining iterations, loop back to body_start.
        Otherwise pop the DO frame and continue.
        """
        if not self._do_stack:
            self._err(stmt.line_no, "FIN without matching DO")
            return

        frame = self._do_stack[-1]

        if not frame.done:
            # More iterations
            frame.next_iteration()
            if frame.label:
                self.sym.define(frame.label,
                                Value.absolute(frame.current), is_set=True)
            self.pos = frame.body_start - 1   # -1 because loop will +1
        else:
            # Done
            self._do_stack.pop()

    def _handle_goto(self, stmt: Statement, modifier: str) -> None:
        """
        GOTO[,k] label1, label2, ...

        Jump to the k-th label (default k=1).  k may be a symbol or expression
        in the command field modifier.
        """
        k = 1
        if modifier:
            k_val = self._eval_modifier_expr(modifier, stmt.line_no)
            if k_val is not None and k_val.kind == ValueKind.ABSOLUTE:
                k = k_val.int_val

        k = max(1, k)
        idx = k - 1   # 0-based
        if idx < len(stmt.args) and stmt.args[idx]:
            tok = stmt.args[idx][0]
            if tok.type == TT.SYMBOL:
                target = find_label(self.stmts, tok.value, self.pos)
                if target >= 0:
                    self.pos = target - 1   # -1 because loop will +1
                    return
        self._err(stmt.line_no, f"GOTO: label not found in arg {k}")

    # --- END --------------------------------------------------------

    def _handle_end(self, stmt: Statement, modifier: str) -> None:
        """
        END [start_address]

        Marks the end of the source.  Evaluates the optional start address
        (stored for use by the GEN pass) and terminates the DEF pass.
        """
        if self._do_stack:
            self._err(stmt.line_no,
                      f"{len(self._do_stack)} unclosed DO block(s) at END")
        # Evaluate (and discard here) the optional start address
        if stmt.args:
            self._eval(stmt.args[0])
        # Terminate the pass
        self.pos = len(self.stmts)   # force exit from the while loop

    # --- Unknown command (instruction / procedure call) --------------

    def _handle_instruction(self, stmt: Statement) -> None:
        """
        Unknown command — standard 32-bit Sigma instruction placeholder.

        CNAME/FNAME detection is handled in _dispatch before this is called,
        so this method only runs for genuinely unknown commands.
        """
        self._define_label(stmt)
        self.sym.advance_lc(4)

    def _call_procedure(self, call_stmt: Statement,
                        body: 'ProcedureBody') -> None:
        """
        Push a CallFrame and redirect execution into the procedure body.

        Argument lists
        --------------
        oprnd_args (AF) : call_stmt.args  — the operand field
        cmd_args   (CF) : the command modifier tokenised into arg lists
        label_args (LF) : the label field re-tokenised, or []

        After pushing the frame, the main ``run()`` loop continues from
        body.body_start.  When PEND is reached, ``_handle_pend`` pops the
        frame and restores self.stmts / self.pos.
        """
        if len(self._call_stack) >= 31:
            self._err(call_stmt.line_no,
                      "Procedure nesting exceeds maximum depth (31)")
            return

        # Build CF arg lists: CF(1)=command base name, CF(2+)=modifier tokens.
        # In AP, the command field "LW,1" has CF(1)='LW' and CF(2)=1.
        base_cmd = call_stmt.command.partition(',')[0] if call_stmt.command else ''
        modifier  = call_stmt.command.partition(',')[2] if call_stmt.command else ''
        base_tok  = [Token(TT.SYMBOL, base_cmd.upper(), base_cmd,
                           call_stmt.line_no, 0)]
        mod_args  = ArgTokenizer(modifier, call_stmt.line_no, 0).tokenize()                     if modifier else []
        cmd_args  = [base_tok] + mod_args

        # Re-tokenise the label field into LF arg lists
        if call_stmt.label:
            label_args = ArgTokenizer(call_stmt.label,
                                      call_stmt.line_no, 0).tokenize()
        else:
            label_args = []

        # Eagerly evaluate argument lists using the CURRENT frame so that
        # AF/CF/LF references inside arguments are resolved at call time.
        # This prevents infinite recursion when nested CNAME calls pass
        # AF(n) expressions as arguments (e.g. BYTE AF(1) inside WORD).
        def eval_arg_toks(tok_list):
            """Evaluate one arg list, returning a pre-evaluated token list."""
            if not tok_list:
                return tok_list
            # Check if this arg contains any procedure-intrinsic references
            # that need resolving. If so, evaluate and return as INT constant.
            has_intrinsic = any(
                t.type == TT.SYMBOL and t.value in (
                    'AF', 'CF', 'LF', 'AFA', 'NAME', 'META', 'P#')
                for t in tok_list
            )
            if has_intrinsic and self._call_stack:
                v = self._eval(tok_list)
                # Return as a single constant token
                return [Token(TT.INT, v.int_val, str(v.int_val),
                              call_stmt.line_no, 0)]
            return tok_list

        eager_oprnd = [eval_arg_toks(a) for a in call_stmt.args]
        eager_cmd   = [eval_arg_toks(a) for a in cmd_args]
        eager_label = [eval_arg_toks(a) for a in label_args]

        frame = CallFrame(
            body         = body,
            body_pos     = body.body_start,
            return_stmts = self.stmts,
            return_pos   = self.pos,          # PEND will +1 past this
            label_args   = eager_label,
            cmd_args     = eager_cmd,
            oprnd_args   = eager_oprnd,
            do_stack     = self._do_stack,
        )
        self._call_stack.append(frame)
        self._do_stack = []

        # Redirect execution into the procedure body
        self.stmts = body.stmts
        self.pos   = body.body_start - 1     # -1 because run() will +1


# ---------------------------------------------------------------------------
# Handler dispatch table
# ---------------------------------------------------------------------------

# Maps uppercase base-command name → bound method name
_HANDLER_MAP: Dict[str, str] = {
    # Storage allocation
    'EQU':    '_handle_equ',
    'SET':    '_handle_set',
    'RES':    '_handle_res',
    'DATA':   '_handle_data',
    'TEXT':   '_handle_text',
    'TEXTC':  '_handle_textc',
    'BOUND':  '_handle_bound',
    'GEN':    '_handle_gen',
    'COM':    '_handle_com',
    'S:SIN':  '_handle_ssin',

    # Location counter control
    'ORG':    '_handle_org',
    'LOC':    '_handle_loc',

    # Control sections
    'CSECT':  '_handle_csect',
    'DSECT':  '_handle_dsect',
    'ASECT':  '_handle_asect',
    'PSECT':  '_handle_psect',
    'SSECT':  '_handle_csect',   # treat SSECT like CSECT for now
    'USECT':  '_handle_usect',

    # External linkage
    'DEF':    '_handle_def',
    'REF':    '_handle_ref',
    'SREF':   '_handle_sref',

    # Symbol scope
    'LOCAL':  '_handle_local',
    'OPEN':   '_handle_open',
    'CLOSE':  '_handle_close',

    # System / listing
    'SYSTEM': '_handle_system',
    'TITLE':  '_handle_title',
    'SPACE':  '_handle_space',
    'PAGE':   '_handle_page',
    'PCC':    '_handle_pcc',
    'PSR':    '_handle_psr',
    'PSYS':   '_handle_psys',
    'LIST':   '_handle_list',
    'DISP':   '_handle_disp',
    'ERROR':  '_handle_error',
    'SOCW':   '_handle_socw',

    # Procedures (stubbed)
    'PROC':   '_handle_proc',
    'PEND':   '_handle_pend',
    'CNAME':  '_handle_cname',
    'FNAME':  '_handle_fname',

    # Flow control
    'DO':     '_handle_do',
    'DO1':    '_handle_do1',
    'ELSE':   '_handle_else',
    'FIN':    '_handle_fin',
    'GOTO':   '_handle_goto',

    # End of source
    'END':    '_handle_end',
}

# _HANDLER_MAP is used directly by _dispatch() via getattr(self, method_name)
# so that subclass overrides are resolved through Python's MRO.
