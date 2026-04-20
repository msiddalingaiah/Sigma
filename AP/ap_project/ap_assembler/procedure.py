"""
ap_assembler/procedure.py — Procedure engine data structures.

Defines the two core dataclasses used by the procedure engine:

  ProcedureBody  — the stored definition of a CNAME or FNAME procedure.
  CallFrame      — one entry on the procedure call stack (one active call).

These are kept in a separate module so they can be imported by both
def_pass.py and expression.py without circular dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from .lexer import Statement, Token
    from .symbol_table import SymbolEntry
    from .value import Value
    from .do_control import DoFrame


# ---------------------------------------------------------------------------
# ProcedureBody — stored at definition time
# ---------------------------------------------------------------------------

@dataclass
class ProcedureBody:
    """
    The compiled body of a CNAME or FNAME procedure.

    Stored as the ``raw`` field of the ``SymbolEntry`` for the procedure name.

    Attributes
    ----------
    stmts : List[Statement]
        The full statement list that contains the body.  This is the same
        list the passes walk — we store a reference, not a copy.
    body_start : int
        Index of the first statement inside the body (the line after PROC).
    pend_index : int
        Index of the matching PEND statement.
    name_value : Value
        The value of the CNAME/FNAME operand expression (e.g. the opcode
        constant X'32' for LW).  ``Value.blank()`` if the operand was absent.
    is_fname : bool
        True for FNAME (function procedure whose PEND returns a value).
    """
    stmts:       list           # List[Statement] — shared reference
    body_start:  int
    pend_index:  int
    name_value:  object         # Value
    is_fname:    bool = False


# ---------------------------------------------------------------------------
# CallFrame — one entry on the call stack
# ---------------------------------------------------------------------------

@dataclass
class CallFrame:
    """
    State for one active procedure call.

    The call stack (``DefPass._call_stack``) holds one frame per active
    procedure invocation.  ``len(call_stack)`` is ``PROCREF`` in the
    original assembler.

    Call-site argument lists
    ------------------------
    All three argument lists hold ``List[List[Token]]`` — the raw token
    lists exactly as produced by ``ArgTokenizer`` and stored in
    ``Statement.args`` / parsed from the command and label fields.

    Evaluation is *lazy*: ``AF(n)`` in the body expression evaluator
    tokenises and evaluates ``oprnd_args[n-1]`` on demand, using the
    symbol table as it stands at evaluation time.

    Attributes
    ----------
    body : ProcedureBody
        The procedure being executed.
    body_pos : int
        Current index within ``body.stmts`` (advances as the body runs).
    return_stmts : list
        The caller's statement list (to resume after PEND).
    return_pos : int
        The index in ``return_stmts`` to resume at.
    label_args : List[List[Token]]
        LF — the label field of the call site, split into argument positions.
        Typically a single one-element list ``[[label_token]]``, or ``[]``.
    cmd_args : List[List[Token]]
        CF — the command-field modifier of the call site, tokenised.
        E.g. for ``LW,1`` the modifier is ``'1'`` → ``[[INT(1)]]``.
    oprnd_args : List[List[Token]]
        AF — the operand-field arguments of the call site.
        E.g. for ``LW,1  ADDR,X'3C'`` → ``[[ADDR tokens], [INT(0x3C)]]``.
    fname_result : Value or None
        For FNAME calls: the value returned by the ``PEND`` expression.
        ``None`` while the body is still executing.
    do_stack : List[DoFrame]
        DO loop stack local to this procedure call.
    """
    body:           ProcedureBody
    body_pos:       int

    return_stmts:   list        # List[Statement]
    return_pos:     int

    label_args:     list        # List[List[Token]]
    cmd_args:       list        # List[List[Token]]
    oprnd_args:     list        # List[List[Token]]

    fname_result:   object = None   # Optional[Value]
    do_stack:       list = field(default_factory=list)   # List[DoFrame]

    # ------------------------------------------------------------------
    # Argument access helpers
    # ------------------------------------------------------------------

    def get_af(self, n: int) -> list:
        """
        Return the token list for the nth operand argument (1-based).
        Returns an empty list if n is out of range.
        """
        if 1 <= n <= len(self.oprnd_args):
            return self.oprnd_args[n - 1]
        return []

    def get_cf(self, n: int) -> list:
        """Return the token list for the nth command-field argument (1-based)."""
        if 1 <= n <= len(self.cmd_args):
            return self.cmd_args[n - 1]
        return []

    def get_lf(self, n: int) -> list:
        """Return the token list for the nth label-field argument (1-based)."""
        if 1 <= n <= len(self.label_args):
            return self.label_args[n - 1]
        return []

    def num_af(self) -> int:
        """Number of operand arguments (AF count)."""
        return len(self.oprnd_args)

    def num_cf(self) -> int:
        """Number of command-field arguments (CF count)."""
        return len(self.cmd_args)
