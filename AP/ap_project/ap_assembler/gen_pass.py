"""
ap_assembler/gen_pass.py — Phase 3: Generation Pass.

Inherits the full directive dispatcher from DefPass and re-runs the same
statement list a second time.  The key difference from the DEF pass:

  * The symbol table is already complete, so every expression evaluates to a
    known value.
  * Data-generating directives now call ``_emit()`` to produce actual bytes
    in the ``ObjectWriter`` and accumulate the hex value for the listing.
  * Every dispatched statement generates a ``ListingLine`` record.

Architecture
------------
GenPass subclasses DefPass and overrides:
  * ``run()``              – calls ``sym.begin_gen_pass()`` and adds listing hooks
  * ``_dispatch()``        – wraps the parent's dispatch with pre/post listing state
  * Data-emitting handlers – call ``self._emit()`` instead of advancing the LC directly

All flow-control handlers (DO/FIN/ELSE/GOTO) are inherited unchanged; they
still manipulate ``self.pos``.  When a DO loop repeats a statement, each
repetition produces its own listing line — matching the original behaviour.

Byte representation of values
------------------------------
* ABSOLUTE integer     → big-endian, sign-extended to ``nbytes``
* RELOCATABLE address  → raw byte offset as an integer (relocation deferred)
* CHARSTR 'text'       → ASCII bytes, left-justified, NUL-padded
* PKDEC / FX / FS / FL → placeholder zeros (full encoding deferred)
* UNDEFINED / BLANK    → zeros

GEN bit-field packing
---------------------
``GEN,f1,f2,...,fn v1,...`` packs values left-to-right into complete 32-bit
words.  The i-th value occupies fi bits, placed immediately left of the
preceding field, with the first field at the MSB of the first word.
"""

from __future__ import annotations

import struct
from typing import List, Optional

from .def_pass import DefPass, AssemblyError
from .do_control import find_else_fin, find_pend, find_label
from .expression import evaluate_arg
from .lexer import Statement, TT, Token
from .listing_writer import ListingWriter
from .object_writer import ObjectWriter
from .symbol_table import CsectKind, SymbolTable, PASS_GEN
from .value import Value, ValueKind, Resolution


class GenPass(DefPass):
    """
    The AP assembler's generation (Phase 3) pass.

    Usage::

        sym = SymbolTable()
        DefPass(stmts, sym).run()       # first run: build symbol table

        obj = ObjectWriter()
        lst = ListingWriter()
        errors = GenPass(stmts, sym, obj, lst).run()

        print(lst.render())
    """

    def __init__(self,
                 stmts:   List[Statement],
                 sym:     SymbolTable,
                 obj:     ObjectWriter,
                 lst:     ListingWriter) -> None:
        super().__init__(stmts, sym)
        self._obj: ObjectWriter  = obj
        self._lst: ListingWriter = lst

        # Per-statement accumulation (reset before each dispatch)
        self._gen_bytes:  bytearray       = bytearray()
        self._list_value: Optional[int]   = None   # for EQU/SET display

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> List[AssemblyError]:
        """
        Execute the GEN pass over all statements.

        The symbol table must already have been populated by a preceding
        ``DefPass.run()`` call.
        """
        self.sym.begin_gen_pass()
        self.pos = 0
        while self.pos < len(self.stmts):
            stmt = self.stmts[self.pos]
            if not stmt.is_comment and stmt.command is not None:
                self._dispatch(stmt)
            else:
                # Comment or blank: add to listing without hex/address
                self._lst.add_comment(stmt.line_no, stmt.source)
            self.pos += 1
        return self.errors

    # ------------------------------------------------------------------
    # Overridden dispatch — wraps parent with listing state capture
    # ------------------------------------------------------------------

    def _dispatch(self, stmt: Statement) -> None:
        """
        Execute one directive and generate its listing line.

        Saves the pre-dispatch address, resets accumulation, calls the
        parent dispatch, then records a listing line with whatever was
        generated.
        """
        # Save state before directive runs
        cs      = self.sym.current_section
        sec_pre = cs.number
        lc_pre  = cs.exec_lc

        # Reset per-statement accumulators
        self._gen_bytes  = bytearray()
        self._list_value = None

        # Execute (may modify self._gen_bytes / self._list_value)
        super()._dispatch(stmt)

        # Determine hex display value
        hex_val = self._listing_hex()

        # Attach any errors generated during this statement
        errs = [str(e) for e in self.errors
                if e.line_no == stmt.line_no]

        self._lst.add_line(
            line_no = stmt.line_no,
            hex_val = hex_val,
            section = sec_pre,
            offset  = lc_pre,
            source  = stmt.source,
            errors  = errs,
        )

    # ------------------------------------------------------------------
    # Core emission helper
    # ------------------------------------------------------------------

    def _emit(self, data: bytes) -> None:
        """
        Write *data* into the object for the current section at the current
        execution LC, advance the LC, and accumulate bytes for the listing.
        """
        cs = self.sym.current_section
        self._obj.emit(cs.number, cs.exec_lc, data, cs.name)
        self.sym.advance_lc(len(data))
        self._gen_bytes.extend(data)

    def _listing_hex(self) -> Optional[str]:
        """Return the 8-char hex string to display on the listing line."""
        if self._list_value is not None:
            return f'{self._list_value & 0xFFFF_FFFF:08X}'
        if self._gen_bytes:
            first4 = bytes(self._gen_bytes[:4]).ljust(4, b'\x00')
            return first4.hex().upper()
        return None

    # ------------------------------------------------------------------
    # Value → bytes conversion
    # ------------------------------------------------------------------

    def _value_to_bytes(self, v: Value, nbytes: int) -> bytes:
        """
        Convert a resolved Value to exactly *nbytes* bytes, big-endian.

        Relocatable values are stored as their raw byte offset; the linker
        applies the actual section base at link time.
        """
        if nbytes <= 0:
            return b''

        if v.kind == ValueKind.ABSOLUTE:
            n = v.int_val
            # Sign-extend to nbytes using two's complement
            if n < 0:
                n = n & ((1 << (nbytes * 8)) - 1)
            return n.to_bytes(nbytes, 'big', signed=False)[-nbytes:]

        if v.kind == ValueKind.RELOCATABLE:
            # Emit raw byte offset; full relocation deferred to linker
            n = v.int_val & 0xFFFF_FFFF
            return n.to_bytes(4, 'big')[-nbytes:]

        if v.kind == ValueKind.CHARSTR:
            raw = (v.raw or '').encode('ascii', errors='replace')
            raw = raw[:nbytes].ljust(nbytes, b'\x00')
            return bytes(raw)

        # PKDEC, FX, FS, FL, UNDEFINED, BLANK → zeros
        return b'\x00' * nbytes

    # ------------------------------------------------------------------
    # GEN bit-field packing
    # ------------------------------------------------------------------

    def _pack_gen_fields(self,
                         field_bits: List[int],
                         args:       list) -> bytes:
        """
        Pack values from *args* into bit fields described by *field_bits*.

        Fields are placed left-to-right (MSB first) into 32-bit words.
        Missing values are treated as zero; extra values are ignored.
        """
        total_bits  = sum(field_bits)
        total_words = max(1, (total_bits + 31) // 32)
        result = 0

        bit_cursor = total_words * 32   # bit 0 = MSB of first word

        for i, width in enumerate(field_bits):
            if width <= 0:
                continue
            if i < len(args) and args[i]:
                val = self._eval(args[i])
            else:
                val = Value.absolute(0)

            raw_int = (val.int_val if val.kind == ValueKind.ABSOLUTE else 0)
            mask    = (1 << width) - 1
            raw_int &= mask

            bit_cursor -= width
            result |= raw_int << bit_cursor

        return result.to_bytes(total_words * 4, 'big')

    # ==================================================================
    # Overridden directive handlers  (data-emitting ones)
    # ==================================================================

    # --- EQU / SET --------------------------------------------------

    def _handle_equ(self, stmt: Statement, modifier: str) -> None:
        v = self._eval_all_args(stmt)
        self._define_label(stmt, v, is_set=False)
        self._show_value(v)

    def _handle_set(self, stmt: Statement, modifier: str) -> None:
        v = self._eval_all_args(stmt)
        self._define_label(stmt, v, is_set=True)
        self._show_value(v)

    def _show_value(self, v: Value) -> None:
        """Record the value in the listing hex column without emitting bytes.

        For a LIST, show the first element if it is a simple integer.
        For a non-integer, leave the hex column blank (the original showed
        a 4-char type tag like 'LIST'; we just leave it empty for now).
        """
        if v.kind in (ValueKind.ABSOLUTE, ValueKind.RELOCATABLE):
            self._list_value = v.int_val
        elif v.kind == ValueKind.LIST and v.items:
            first = v.items[0]
            if first.kind == ValueKind.ABSOLUTE:
                self._list_value = first.int_val

    # --- RES --------------------------------------------------------

    def _handle_res(self, stmt: Statement, modifier: str) -> None:
        self._define_label(stmt)
        unit  = self._eval_modifier_int(modifier, 4)
        if unit <= 0:
            unit = 4
        count_v = self._eval_arg(stmt, 0, Value.absolute(0))
        count   = self._require_int(count_v, stmt, 0)
        if count < 0:
            count = 0
        self._emit(b'\x00' * (unit * count))

    # --- DATA -------------------------------------------------------

    def _handle_data(self, stmt: Statement, modifier: str) -> None:
        self._define_label(stmt)
        bits   = self._eval_modifier_int(modifier, 32)
        if bits <= 0 or bits > 64:
            bits = 32
        nbytes = max(1, (bits + 7) // 8)

        for arg in stmt.args:
            v   = self._eval(arg)
            raw = self._value_to_bytes(v, nbytes)
            self._emit(raw)

    # --- TEXT / TEXTC -----------------------------------------------

    def _handle_text(self, stmt: Statement, modifier: str) -> None:
        """
        TEXT 'string'

        Pack characters into 4-byte words, left-adjusted, zero-padded to
        the next word boundary.
        """
        self._define_label(stmt)
        for arg in stmt.args:
            if arg and arg[0].type == TT.CHARSTR:
                raw    = arg[0].value.encode('ascii', errors='replace')
                padded = raw.ljust(((len(raw) + 3) // 4) * 4, b'\x00')
            else:
                v      = self._eval(arg)
                raw    = self._value_to_bytes(v, 4)
                padded = raw
            self._emit(bytes(padded))

    def _handle_textc(self, stmt: Statement, modifier: str) -> None:
        """
        TEXTC 'string'

        Like TEXT but prefixed by a one-byte character count.  Total size
        padded to the next word boundary.
        """
        self._define_label(stmt)
        for arg in stmt.args:
            if arg and arg[0].type == TT.CHARSTR:
                s      = arg[0].value
                raw    = bytes([len(s) & 0xFF]) + s.encode('ascii', errors='replace')
                padded = raw.ljust(((len(raw) + 3) // 4) * 4, b'\x00')
            else:
                v      = self._eval(arg)
                raw    = self._value_to_bytes(v, 4)
                padded = raw
            self._emit(bytes(padded))

    # --- BOUND ------------------------------------------------------

    def _handle_bound(self, stmt: Statement, modifier: str) -> None:
        v = self._eval_arg(stmt, 0, Value.absolute(4))
        n = self._require_int(v, stmt, 4)
        if n <= 0 or (n & (n - 1)) != 0 or n > 2048:
            self._err(stmt.line_no,
                      f'BOUND: {n} is not a positive power-of-2 ≤ 2048')
            n = 4
        cs  = self.sym.current_section
        rem = cs.exec_lc % n
        if rem:
            self._emit(b'\x00' * (n - rem))

    # --- GEN --------------------------------------------------------

    def _handle_gen(self, stmt: Statement, modifier: str) -> None:
        self._define_label(stmt)
        if modifier:
            try:
                field_bits = [int(x) for x in modifier.split(',') if x]
            except ValueError:
                field_bits = []
        else:
            field_bits = []

        if field_bits:
            raw = self._pack_gen_fields(field_bits, stmt.args)
        else:
            raw = b'\x00' * 4
        self._emit(raw)

    # --- COM --------------------------------------------------------

    def _handle_com(self, stmt: Statement, modifier: str) -> None:
        # Command-template definition: no object output.
        if stmt.label:
            self.sym.define(stmt.label, Value.absolute(0))

    # --- ORG / LOC --------------------------------------------------

    def _handle_org(self, stmt: Statement, modifier: str) -> None:
        self._do_org_or_loc(stmt, modifier, move_load=True)

    def _handle_loc(self, stmt: Statement, modifier: str) -> None:
        self._do_org_or_loc(stmt, modifier, move_load=False)

    # --- Section directives (no bytes, but listing line) ------------

    def _handle_csect(self, stmt: Statement, modifier: str) -> None:
        super()._handle_csect(stmt, modifier)

    def _handle_dsect(self, stmt: Statement, modifier: str) -> None:
        super()._handle_dsect(stmt, modifier)

    def _handle_asect(self, stmt: Statement, modifier: str) -> None:
        super()._handle_asect(stmt, modifier)

    def _handle_psect(self, stmt: Statement, modifier: str) -> None:
        super()._handle_psect(stmt, modifier)

    def _handle_usect(self, stmt: Statement, modifier: str) -> None:
        super()._handle_usect(stmt, modifier)

    # --- Unknown instruction -----------------------------------------

    def _handle_instruction(self, stmt: Statement) -> None:
        """
        Unknown command — treated as a 32-bit instruction word.

        The label is defined at the current LC and 4 zero bytes are emitted.
        Actual instruction encoding requires the instruction-definition table
        (from APPART), which is implemented as a future enhancement.
        """
        self._define_label(stmt)
        self._emit(b'\x00' * 4)

    # --- Procedure stubs (no object output) -------------------------

    def _handle_proc(self, stmt: Statement, modifier: str) -> None:
        end = find_pend(self.stmts, self.pos + 1)
        self.pos = end

    def _handle_pend(self, stmt: Statement, modifier: str) -> None:
        pass

    def _handle_cname(self, stmt: Statement, modifier: str) -> None:
        if stmt.label:
            self.sym.define(stmt.label, Value.absolute(0))
        end = find_pend(self.stmts, self.pos + 1)
        self.pos = end

    def _handle_fname(self, stmt: Statement, modifier: str) -> None:
        if stmt.label:
            self.sym.define(stmt.label, Value.absolute(0))
        end = find_pend(self.stmts, self.pos + 1)
        self.pos = end
