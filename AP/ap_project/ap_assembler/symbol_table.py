"""
ap_assembler/symbol_table.py — Symbol table and control section management.

The AP assembler's symbol table stores the value of every symbol in the
program.  In the original, this was a balanced AVL tree of packed-bitfield
entries in a fixed memory area.  Here we use Python dicts and dataclasses.

Key concepts:

  SymbolEntry   — one row in the table: name → value + metadata
  ControlSection — tracks the two location counters (exec LC and load LC)
                   and the maximum load LC seen (for sizing the section).
  SymbolTable   — the top-level container; manages global and local scopes.

Location counters (``$`` / ``%`` and ``$$`` / ``%%`` in AP):

  AP maintains two location counters per control section:
    % / $   — execution LC (where code runs)
    %% / $$ — load LC     (where it is loaded; usually equals % unless
               ORG is used to reset the execution counter independently)

  Both counters are stored in *byte* resolution internally; the Resolution
  attribute describes the *intrinsic* resolution of the current section
  (default WORD = 4 bytes).

Passes:

  PASS_DEF = 1  — definition pass: build symbol table, allocate storage
  PASS_GEN = 2  — generation pass: emit object code
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional

from .value import Value, ValueKind, Resolution, _s32


# ---------------------------------------------------------------------------
# Pass constants
# ---------------------------------------------------------------------------

PASS_DEF = 1
PASS_GEN = 2


# ---------------------------------------------------------------------------
# Control section types
# ---------------------------------------------------------------------------

class CsectKind(Enum):
    ASECT = 'ASECT'   # absolute section (section 0, non-relocatable)
    CSECT = 'CSECT'   # normal code/data section
    DSECT = 'DSECT'   # dummy section (defines layout, no object output)
    PSECT = 'PSECT'   # protected section
    USECT = 'USECT'   # unnamed section (re-enters a named section by name)
    SSECT = 'SSECT'   # structured section (rarely used)


# ---------------------------------------------------------------------------
# ControlSection
# ---------------------------------------------------------------------------

@dataclass
class ControlSection:
    """
    State for one AP control section.

    number      : section number (0 = ASECT, 1+ = CSECT/DSECT/PSECT)
    kind        : CsectKind
    name        : section name (label on the CSECT/DSECT directive)
    resolution  : intrinsic resolution (default WORD)
    exec_lc     : execution location counter ($ / %)  in bytes
    load_lc     : load location counter    ($$ / %%) in bytes
    max_load_lc : high-water mark for load_lc (used to size the section)
    protection  : protection type 0-3
    """
    number:       int
    kind:         CsectKind
    name:         str             = ''
    resolution:   Resolution      = Resolution.WORD
    exec_lc:      int             = 0    # byte offset of execution LC
    load_lc:      int             = 0    # byte offset of load LC
    max_load_lc:  int             = 0    # maximum load LC seen
    protection:   int             = 0

    def advance(self, nbytes: int) -> None:
        """Advance both location counters by nbytes."""
        self.exec_lc += nbytes
        self.load_lc += nbytes
        if self.load_lc > self.max_load_lc:
            self.max_load_lc = self.load_lc

    def align(self, boundary: int) -> int:
        """
        Advance both LCs to the next multiple of *boundary* bytes.
        Returns the number of padding bytes inserted.
        """
        rem = self.exec_lc % boundary
        if rem == 0:
            return 0
        pad = boundary - rem
        self.advance(pad)
        return pad

    def current_value(self) -> Value:
        """Return the current execution LC as a Value."""
        return Value.relocatable(self.number, self.exec_lc, self.resolution)

    def current_load_value(self) -> Value:
        """Return the current load LC as a Value."""
        return Value.relocatable(self.number, self.load_lc, self.resolution)


# ---------------------------------------------------------------------------
# SymbolEntry
# ---------------------------------------------------------------------------

@dataclass
class SymbolEntry:
    """
    One entry in the AP symbol table.

    name          : symbol name (always uppercase)
    value         : the symbol's current Value
    is_set        : True if SET (re-definable), False if EQU/label
    is_local      : True for LOCAL-declared symbols
    external_type : '' | 'def' | 'ref' | 'sref'
    defined_pass  : 0 = not yet defined, 1 = defined in DEF pass,
                    2 = defined in GEN pass
    appeared_as_cmd : True if this symbol appeared in a command field (CF1)
    decl_num      : loader declaration number (assigned during DEF pass end)
    """
    name:             str
    value:            Value                = field(default_factory=Value.undefined)
    is_set:           bool                 = False
    is_local:         bool                 = False
    external_type:    str                  = ''    # '' | 'def' | 'ref' | 'sref'
    defined_pass:     int                  = 0
    appeared_as_cmd:  bool                 = False
    decl_num:         int                  = 0

    @property
    def is_defined(self) -> bool:
        return self.defined_pass > 0

    @property
    def is_external(self) -> bool:
        return self.external_type in ('def', 'ref', 'sref')

    @property
    def is_def(self) -> bool:
        return self.external_type == 'def'

    @property
    def is_ref(self) -> bool:
        return self.external_type in ('ref', 'sref')


# ---------------------------------------------------------------------------
# SymbolTable
# ---------------------------------------------------------------------------

class SymbolTable:
    """
    The global symbol table for an AP assembly.

    Internally keeps:
      _globals  : name → SymbolEntry  (global / non-local symbols)
      _locals   : list of dict frames for LOCAL scope stacks
      _sections : list of ControlSection objects (index = section number)
      _current_section : index of the active control section
      _pass     : current assembly pass (PASS_DEF or PASS_GEN)

    Control section 0 is ASECT (absolute).
    Control section 1 is the default CSECT opened at assembly start.
    """

    def __init__(self) -> None:
        self._globals:  Dict[str, SymbolEntry] = {}
        self._locals:   List[Dict[str, SymbolEntry]] = [{}]  # scope stack
        self._sections: List[ControlSection] = [
            ControlSection(0, CsectKind.ASECT, 'ASECT', Resolution.WORD),
            ControlSection(1, CsectKind.CSECT, '',      Resolution.WORD),
        ]
        self._current:  int  = 1    # active control section number
        self._pass:     int  = PASS_DEF

    # ------------------------------------------------------------------
    # Pass management
    # ------------------------------------------------------------------

    @property
    def current_pass(self) -> int:
        return self._pass

    def begin_gen_pass(self) -> None:
        """Reset location counters and switch to the generation pass."""
        self._pass = PASS_GEN
        for cs in self._sections:
            cs.exec_lc = 0
            cs.load_lc = 0
        self._current = 1

    # ------------------------------------------------------------------
    # Control section management
    # ------------------------------------------------------------------

    @property
    def current_section(self) -> ControlSection:
        return self._sections[self._current]

    def get_section(self, number: int) -> Optional[ControlSection]:
        if 0 <= number < len(self._sections):
            return self._sections[number]
        return None

    def open_section(self, kind: CsectKind, name: str = '',
                     resolution: Resolution = Resolution.WORD,
                     protection: int = 0) -> ControlSection:
        """
        Open a new control section, or re-enter an existing one by name.
        Returns the ControlSection object and makes it the active section.
        """
        # USECT re-enters an existing named section
        if kind == CsectKind.USECT and name:
            for cs in self._sections:
                if cs.name == name:
                    self._current = cs.number
                    return cs

        # Check if we have seen this name as a CSECT/PSECT before
        if name:
            for cs in self._sections:
                if cs.name == name and cs.kind == kind:
                    self._current = cs.number
                    return cs

        # Brand-new section
        num = len(self._sections)
        cs = ControlSection(num, kind, name, resolution, protection=protection)
        self._sections.append(cs)
        self._current = num
        return cs

    def switch_to_section(self, number: int) -> ControlSection:
        """Switch the active section to the given number."""
        if 0 <= number < len(self._sections):
            self._current = number
            return self._sections[number]
        raise KeyError(f"No control section {number}")

    # ------------------------------------------------------------------
    # Location counter operations
    # ------------------------------------------------------------------

    def exec_lc(self) -> int:
        """Current execution location counter (% / $), in bytes."""
        return self._sections[self._current].exec_lc

    def load_lc(self) -> int:
        """Current load location counter (%% / $$), in bytes."""
        return self._sections[self._current].load_lc

    def advance_lc(self, nbytes: int) -> None:
        """Advance both location counters by nbytes."""
        self._sections[self._current].advance(nbytes)

    def align_lc(self, boundary: int) -> int:
        """Advance both LCs to the next multiple of *boundary* bytes."""
        return self._sections[self._current].align(boundary)

    def set_exec_lc(self, byte_offset: int, csect: int = -1) -> None:
        """
        Set the execution LC to *byte_offset* (used by ORG / LOC).
        If csect >= 0, also switch the current section.
        """
        if csect >= 0:
            self._current = csect
        self._sections[self._current].exec_lc = byte_offset

    def dollar_value(self) -> Value:
        """Return the current value of $ (execution LC)."""
        cs = self._sections[self._current]
        return Value.relocatable(cs.number, cs.exec_lc, cs.resolution)

    def dollar_dollar_value(self) -> Value:
        """Return the current value of $$ (load LC)."""
        cs = self._sections[self._current]
        return Value.relocatable(cs.number, cs.load_lc, cs.resolution)

    # ------------------------------------------------------------------
    # Symbol lookup and definition
    # ------------------------------------------------------------------

    def lookup(self, name: str) -> Optional[SymbolEntry]:
        """
        Look up a symbol.  Searches the local scope stack first, then globals.
        Returns None if not found.
        """
        uname = name.upper()
        # Search local scopes from innermost outward
        for scope in reversed(self._locals):
            if uname in scope:
                return scope[uname]
        return self._globals.get(uname)

    def lookup_or_create(self, name: str, is_local: bool = False) -> SymbolEntry:
        """
        Look up a symbol, creating an UNDEFINED entry if not present.
        """
        entry = self.lookup(name)
        if entry is not None:
            return entry
        uname = name.upper()
        entry = SymbolEntry(name=uname, value=Value.undefined())
        entry.is_local = is_local
        if is_local and self._locals:
            self._locals[-1][uname] = entry
        else:
            self._globals[uname] = entry
        return entry

    def define(self, name: str, value: Value,
               is_set: bool = False,
               is_local: bool = False) -> SymbolEntry:
        """
        Define a symbol.

        If is_local=True the definition always goes into the innermost local
        scope, creating a shadow of any existing global with the same name.

        If the symbol already exists in the target scope:
          - SET symbols can be redefined at any time.
          - EQU/label symbols can only be defined once (duplicate flagged in
            a full implementation; silently allowed here in the GEN pass).

        Returns the SymbolEntry.
        """
        uname = name.upper()

        if is_local and self._locals:
            # Always write into the innermost local scope (shadow globals)
            entry = self._locals[-1].get(uname)
            if entry is None:
                entry = SymbolEntry(name=uname)
                self._locals[-1][uname] = entry
        else:
            entry = self._globals.get(uname)
            if entry is None:
                entry = SymbolEntry(name=uname)
                self._globals[uname] = entry

        entry.value        = value
        entry.is_set       = is_set
        entry.is_local     = is_local
        entry.defined_pass = self._pass
        return entry

    def mark_external(self, name: str, ext_type: str) -> SymbolEntry:
        """
        Mark a symbol as external (DEF, REF, or SREF).
        Creates the entry if it doesn't exist.
        """
        uname = name.upper()
        entry = self.lookup_or_create(uname)
        if ext_type == 'def':
            entry.external_type = 'def'
        elif ext_type in ('ref', 'sref') and entry.external_type != 'def':
            entry.external_type = ext_type
            if entry.value.kind == ValueKind.UNDEFINED:
                entry.value = Value.external(uname)
        return entry

    # ------------------------------------------------------------------
    # Local scope management
    # ------------------------------------------------------------------

    def push_local_scope(self) -> None:
        """Push a new local scope frame (entered at PROC)."""
        self._locals.append({})

    def pop_local_scope(self) -> None:
        """Pop the innermost local scope (at PEND)."""
        if len(self._locals) > 1:
            self._locals.pop()

    def declare_local(self, name: str) -> SymbolEntry:
        """
        Declare a symbol as LOCAL.  It will shadow any global with the same
        name within the current local scope.
        """
        uname = name.upper()
        # Save any existing global temporarily by creating a local shadow
        entry = SymbolEntry(name=uname, value=Value.undefined(), is_local=True)
        if self._locals:
            self._locals[-1][uname] = entry
        return entry

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def all_globals(self) -> Dict[str, SymbolEntry]:
        """Return a view of all global symbol entries."""
        return dict(self._globals)

    def section_count(self) -> int:
        return len(self._sections)

    def all_sections(self) -> List[ControlSection]:
        return list(self._sections)

    def __repr__(self) -> str:
        return (f"SymbolTable({len(self._globals)} globals, "
                f"{len(self._sections)} sections, "
                f"pass={self._pass})")
