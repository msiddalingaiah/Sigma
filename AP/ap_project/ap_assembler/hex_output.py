"""
ap_assembler/hex_output.py — Verilog $readmemh hex file writer.

Produces a plain-text hex file that Verilog/SystemVerilog simulators and
most FPGA BRAM initialisation tools can consume directly:

    initial $readmemh("prog.hex", instruction_memory);

Format
------
Lines beginning with ``//`` are comments (ignored by simulators).

``@XXXXXXXX`` sets the current word address (hexadecimal, no prefix).
The address is a *word index* — the index into the Verilog array — not a
byte offset.  For a 32-bit-wide memory, word N holds bytes 4N … 4N+3.

Each non-comment, non-address line contains one or more space-separated
hex values, each representing one memory word.

Example output (32-bit words, one per line)::

    // AP Assembler output — 32-bit words
    // Section 1 'CODE': 12 bytes
    @00000000
    12345678
    DEADBEEF
    00000000
    // Section 2 'DATA': 8 bytes
    @00000003
    CAFEBABE
    00000001

Section layout
--------------
By default sections are packed sequentially in the output: section 1
starts at word 0, section 2 starts immediately after the last word of
section 1, and so on.  A ``@address`` marker is emitted whenever a
section starts at a word address that does not immediately follow the
previous word (i.e. for the first section, and any time there would be a
gap).

Word size
---------
The default word size is 4 bytes (32-bit), matching the Sigma architecture.
Specify ``word_bytes=2`` for 16-bit-wide memories or ``word_bytes=1`` for
byte-addressed simulation.  Data is always packed big-endian within each
word; bytes that fall outside a section's data are padded with zeros.

Unresolved relocations
----------------------
The assembler may produce relocatable values (symbol + section-relative
offset) that a linker would normally patch.  These are emitted as their
raw integer offset values.  A comment line summarises the number of
unresolved relocation entries if any exist.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from typing import IO, Dict, List, Optional, Sequence

from .object_writer import ObjectWriter, SectionData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pad_to_words(data: bytes, word_bytes: int) -> bytes:
    """Zero-pad *data* to the next whole-word boundary."""
    rem = len(data) % word_bytes
    return data if rem == 0 else data + b'\x00' * (word_bytes - rem)


def _bytes_to_words(data: bytes, word_bytes: int) -> List[int]:
    """
    Split *data* (already padded to a word boundary) into a list of
    unsigned integers, one per word, big-endian.
    """
    padded = _pad_to_words(data, word_bytes)
    return [
        int.from_bytes(padded[i:i + word_bytes], 'big')
        for i in range(0, len(padded), word_bytes)
    ]


def _hex_word(value: int, word_bytes: int) -> str:
    """Format *value* as an uppercase hex string of the correct width."""
    digits = word_bytes * 2
    return f'{value & ((1 << (word_bytes * 8)) - 1):0{digits}X}'


# ---------------------------------------------------------------------------
# SectionPlacement — where one section lands in the combined address space
# ---------------------------------------------------------------------------

@dataclass
class SectionPlacement:
    """
    Describes where a single AP control section is placed in the flat
    word-addressed output.

    section     : the source SectionData object
    word_start  : first word index in the combined address space
    word_count  : number of words occupied (including padding to word boundary)
    """
    section:    SectionData
    word_start: int
    word_count: int

    @property
    def word_end(self) -> int:
        return self.word_start + self.word_count


# ---------------------------------------------------------------------------
# VerilogHexWriter
# ---------------------------------------------------------------------------

class VerilogHexWriter:
    """
    Converts an ``ObjectWriter``'s section data to a Verilog ``$readmemh``
    hex file.

    Parameters
    ----------
    word_bytes : int
        Bytes per memory word.  Default 4 (32-bit).
    words_per_line : int
        Number of word values to emit on each data line.  Default 1 (one
        word per line).  Use 4 or 8 for a denser listing.
    add_comments : bool
        Emit ``//``-prefixed comment lines describing each section.
        Default True.
    fill_gaps : bool
        When True, gaps between sections are filled with zero-word data so
        that the output is a single contiguous block.  When False (default),
        ``@address`` markers are emitted to skip over gaps.

    Usage::

        writer = VerilogHexWriter()
        writer.write(obj, sys.stdout)
        writer.write_file(obj, "prog.hex")
    """

    def __init__(self,
                 word_bytes:    int  = 4,
                 words_per_line: int  = 1,
                 add_comments:  bool = True,
                 fill_gaps:     bool = False) -> None:
        if word_bytes not in (1, 2, 4, 8):
            raise ValueError(f"word_bytes must be 1, 2, 4 or 8; got {word_bytes}")
        if words_per_line < 1:
            raise ValueError(f"words_per_line must be ≥ 1; got {words_per_line}")
        self.word_bytes     = word_bytes
        self.words_per_line = words_per_line
        self.add_comments   = add_comments
        self.fill_gaps      = fill_gaps

    # ------------------------------------------------------------------
    # Layout computation
    # ------------------------------------------------------------------

    def layout(self, obj: ObjectWriter) -> List[SectionPlacement]:
        """
        Compute the sequential placement of every non-empty, non-dummy
        section.  Returns a list of ``SectionPlacement`` objects in
        section-number order.
        """
        placements: List[SectionPlacement] = []
        current_word = 0

        for sec in obj.sections():
            if sec.is_dummy or not sec.data:
                continue
            word_count = math.ceil(len(sec.data) / self.word_bytes)
            placements.append(SectionPlacement(sec, current_word, word_count))
            current_word += word_count

        return placements

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def write(self, obj: ObjectWriter, dest: IO[str]) -> None:
        """
        Write the complete hex file to the file-like object *dest*.
        """
        placements = self.layout(obj)
        if not placements:
            if self.add_comments:
                dest.write("// AP Assembler output - no data sections\n")
            return

        # File header
        if self.add_comments:
            bits = self.word_bytes * 8
            total_words = placements[-1].word_end if placements else 0
            total_bytes = sum(p.section.size for p in placements)
            dest.write(f"// AP Assembler output - {bits}-bit words\n")
            dest.write(f"// {len(placements)} section(s), "
                       f"{total_words} word(s), {total_bytes} byte(s)\n")
            dest.write("//\n")

            # Report unresolved relocations
            total_relocs = sum(len(p.section.relocs) for p in placements)
            if total_relocs:
                dest.write(f"// NOTE: {total_relocs} unresolved relocation(s) "
                           f"- values are raw section offsets\n")
                dest.write("//\n")

        # Emit sections
        prev_word_end = 0
        for pl in placements:
            # Always emit an @address marker — explicit is safer in $readmemh
            dest.write(f"@{pl.word_start:08X}\n")

            # Section comment
            if self.add_comments:
                name_s = f" '{pl.section.name}'" if pl.section.name else ''
                reloc_s = (f", {len(pl.section.relocs)} reloc(s)"
                           if pl.section.relocs else '')
                dest.write(
                    f"// Section {pl.section.number}{name_s}: "
                    f"{pl.section.size} byte(s){reloc_s}\n"
                )

            # Data words
            words = _bytes_to_words(bytes(pl.section.data), self.word_bytes)
            # Pad to declared word_count (handles non-word-multiple sizes)
            while len(words) < pl.word_count:
                words.append(0)

            if self.fill_gaps:
                # Fill any gap before this section with zeros
                gap = pl.word_start - prev_word_end
                for _ in range(gap):
                    dest.write(_hex_word(0, self.word_bytes) + '\n')

            for i in range(0, len(words), self.words_per_line):
                chunk = words[i:i + self.words_per_line]
                dest.write(
                    ' '.join(_hex_word(w, self.word_bytes) for w in chunk)
                    + '\n'
                )

            prev_word_end = pl.word_end

    def write_file(self, obj: ObjectWriter, path: str) -> None:
        """Write the hex file to *path*."""
        with open(path, 'w', encoding='ascii') as f:
            self.write(obj, f)

    def render(self, obj: ObjectWriter) -> str:
        """Return the hex file as a string (useful for testing)."""
        buf = io.StringIO()
        self.write(obj, buf)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def total_words(self, obj: ObjectWriter) -> int:
        """Return the total number of words in the output."""
        pls = self.layout(obj)
        return pls[-1].word_end if pls else 0

    def total_bytes_covered(self, obj: ObjectWriter) -> int:
        """Return the total byte span of the output (word_size × total_words)."""
        return self.total_words(obj) * self.word_bytes


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def write_verilog_hex(obj: ObjectWriter,
                      path: str,
                      word_bytes:     int  = 4,
                      words_per_line: int  = 1,
                      add_comments:   bool = True,
                      fill_gaps:      bool = False) -> None:
    """
    Write a Verilog ``$readmemh``-compatible hex file from assembled object code.

    Parameters
    ----------
    obj            : ObjectWriter with assembled section data.
    path           : output file path (created or overwritten).
    word_bytes     : bytes per memory word (1, 2, 4, or 8).  Default 4.
    words_per_line : words on each data line.  Default 1.
    add_comments   : include ``//`` comment lines.  Default True.
    fill_gaps      : zero-fill gaps instead of using ``@address`` markers.
    """
    VerilogHexWriter(word_bytes, words_per_line, add_comments,
                     fill_gaps).write_file(obj, path)
