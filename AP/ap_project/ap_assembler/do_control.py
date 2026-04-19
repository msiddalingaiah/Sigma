"""
ap_assembler/do_control.py — Assembly-time flow control.

Implements the DO / DO1 / ELSE / FIN / GOTO directives that control which
statements are processed during the DEF and GEN passes.

AP DO semantics (from the APDG source comments):

  LBL  DO   N         - if N <= 0: skip body to ELSE (or FIN), execute ELSE
                         section once; if N > 0: execute body N times then
                         skip ELSE section.
  LBL  DO1  N         - if N < 1:  skip the very next statement;
                         if N == 1: execute it once (normal);
                         if N > 1:  execute it N times.
       ELSE            - within DO: loop-back point; also separates the
                         body from the optional "else section".
       FIN             - terminates a DO block; loops back if count not done.
       GOTO[,k] L1,... - jump to statement labelled Lk (1-based default k=1).

The label on a DO is a SET symbol that holds the current iteration count
(0 if the body was skipped, 1 on first pass, 2 on second, …).

The label on DO1 is defined normally (EQU to current LC) and is not updated
on each repeat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .lexer import Statement


# ---------------------------------------------------------------------------
# DoFrame — one entry on the DO control stack
# ---------------------------------------------------------------------------

@dataclass
class DoFrame:
    """
    State for one active DO block.

    body_start  : index of the first Statement inside the body (line after DO)
    target      : total number of times to execute the body (DOI in the original)
    current     : current iteration number, 1-based (DOC in the original)
    label       : name of the DO label (updated on each iteration), or None
    else_idx    : statement index of the matching ELSE line (-1 if absent)
    fin_idx     : statement index of the matching FIN line
    """
    body_start: int
    target:     int
    current:    int              = 1
    label:      Optional[str]   = None
    else_idx:   int             = -1
    fin_idx:    int             = -1

    @property
    def done(self) -> bool:
        """True when all iterations have been completed."""
        return self.current >= self.target

    def next_iteration(self) -> None:
        self.current += 1


# ---------------------------------------------------------------------------
# Helpers: scan forward to find ELSE / FIN
# ---------------------------------------------------------------------------

def find_else_fin(stmts: List[Statement], start: int) -> Tuple[int, int]:
    """
    Scan forward from *start* to find the matching ELSE and FIN for the DO
    on the line just before *start*.

    Returns ``(else_idx, fin_idx)`` where ``else_idx == -1`` if no ELSE was
    found.  ``fin_idx`` is the index of the matching FIN, or
    ``len(stmts) - 1`` if the source ended without one (malformed input).

    Handles nesting: inner DO/FIN pairs are counted and skipped.
    """
    depth    = 0          # nesting depth of inner DO blocks
    else_idx = -1

    for i in range(start, len(stmts)):
        stmt = stmts[i]
        if stmt.is_comment or stmt.command is None:
            continue
        base = stmt.command.split(',')[0].upper()

        if base == 'DO':
            depth += 1
        elif base == 'ELSE' and depth == 0:
            if else_idx == -1:        # record only the first ELSE at this level
                else_idx = i
        elif base == 'FIN':
            if depth == 0:
                return else_idx, i    # found the matching FIN
            depth -= 1

    # Malformed source: no FIN found — return end of list
    return else_idx, max(start, len(stmts) - 1)


def find_pend(stmts: List[Statement], start: int) -> int:
    """
    Scan forward from *start* to find the matching PEND for a PROC/CNAME/FNAME.
    Returns the index of the PEND statement.

    Depth tracking: each PROC/CNAME/FNAME encountered increments depth; each
    PEND decrements it.  The matching PEND is the one that brings depth to 0.
    """
    depth = 0
    for i in range(start, len(stmts)):
        stmt = stmts[i]
        if stmt.is_comment or stmt.command is None:
            continue
        base = stmt.command.split(',')[0].upper()
        if base in ('PROC', 'CNAME', 'FNAME'):
            depth += 1
        elif base == 'PEND':
            if depth == 0:
                return i          # no nesting: this is the target
            depth -= 1
            if depth == 0:
                return i          # just closed the outermost opener
    return max(start, len(stmts) - 1)


def find_label(stmts: List[Statement], name: str, start: int = 0) -> int:
    """
    Find the statement with label *name*, searching from *start*.
    Wraps around once.  Returns the statement index or -1 if not found.
    """
    upper = name.upper()
    n = len(stmts)
    for delta in range(n):
        i = (start + delta) % n
        if stmts[i].label == upper:
            return i
    return -1
