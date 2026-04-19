"""
ap_assembler/object_writer.py — Object code collector.

Accumulates the raw bytes generated during the GEN pass, organised by control
section.  Each section grows a ``bytearray``; relocatable references are
recorded separately as ``Relocation`` entries so a linker can patch them.

The original AP assembler wrote a Xerox binary object (BO) file in a
specific loader format with control codes for load-origin, add-constant,
expression-end, external-definition, etc.  This module takes a simpler
approach suited to the Python port: bytes are collected in memory and can
later be serialised to any target format.

Loader control codes (mirroring the original APDGCOM equates)
--------------------------------------------------------------
These match the codes embedded in the Xerox BO format and are preserved here
for future use when full BO compatibility is needed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Loader control codes (from APDGCOM)
# ---------------------------------------------------------------------------

CTRL_EXPEND  = 2    # expression end
CTRL_ORIGIN  = 4    # load origin
CTRL_ADDCON  = 1    # add constant
CTRL_FWDREF  = 8    # forward reference definition
CTRL_FWDHLD  = 16   # forward reference and hold
CTRL_DEFEXT  = 10   # define external definition


# ---------------------------------------------------------------------------
# Relocation entry
# ---------------------------------------------------------------------------

@dataclass
class Relocation:
    """
    Describes one relocatable field within the generated data.

    byte_offset : byte offset within the section's data buffer
    bit_offset  : bit offset of the field's MSB within the 32-bit word
                  (0 = most significant bit; matches AP's LOB conventions)
    width       : field width in bits
    section     : control section number to add/subtract
    addend      : constant addend in byte units (the load-time base offset)
    sign        : +1 = add, -1 = subtract
    """
    byte_offset:  int
    bit_offset:   int
    width:        int
    section:      int
    addend:       int
    sign:         int = 1


# ---------------------------------------------------------------------------
# Per-section byte buffer
# ---------------------------------------------------------------------------

class SectionData:
    """
    Accumulated generated data for one AP control section.

    Bytes are written at explicit offsets; gaps between writes are zero-filled.
    """

    def __init__(self, number: int, name: str = '',
                 is_dummy: bool = False) -> None:
        self.number:   int           = number
        self.name:     str           = name
        self.is_dummy: bool          = is_dummy   # DSECT → no object output
        self.data:     bytearray     = bytearray()
        self.relocs:   List[Relocation] = []

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def pad_to(self, offset: int) -> None:
        """Extend the buffer with zeros up to *offset* if needed."""
        if offset > len(self.data):
            self.data.extend(b'\x00' * (offset - len(self.data)))

    def write_bytes(self, offset: int, data: bytes) -> None:
        """
        Write *data* starting at *offset*, zero-filling any gap before it.
        """
        self.pad_to(offset)
        end = offset + len(data)
        if end > len(self.data):
            self.data.extend(b'\x00' * (end - len(self.data)))
        self.data[offset:end] = data

    def write_word(self, offset: int, value: int) -> None:
        """Write a 32-bit big-endian word at *offset*."""
        self.write_bytes(offset, struct.pack('>I', value & 0xFFFF_FFFF))

    def add_reloc(self, reloc: Relocation) -> None:
        """Record a relocation entry."""
        self.relocs.append(reloc)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        return len(self.data)

    def hex_dump(self, width: int = 16) -> str:
        """Return a multi-line hex dump of the section data."""
        lines = []
        for i in range(0, len(self.data), width):
            chunk = self.data[i:i + width]
            hex_part = ' '.join(f'{b:02X}' for b in chunk)
            lines.append(f"  {i:08X}  {hex_part}")
        return '\n'.join(lines)


# ---------------------------------------------------------------------------
# ObjectWriter
# ---------------------------------------------------------------------------

class ObjectWriter:
    """
    Collects generated object code across all control sections.

    Usage::

        ow = ObjectWriter()
        ow.emit(section=1, offset=0, data=b'\\xDE\\xAD\\xBE\\xEF')
        ow.emit_reloc(section=1, byte_offset=0, ...)

        for sec in ow.sections():
            print(sec.name, sec.hex_dump())
    """

    def __init__(self) -> None:
        self._sections: Dict[int, SectionData] = {}

    # ------------------------------------------------------------------
    # Section management
    # ------------------------------------------------------------------

    def open_section(self, number: int, name: str = '',
                     is_dummy: bool = False) -> SectionData:
        """Register (or return) a section by number."""
        if number not in self._sections:
            self._sections[number] = SectionData(number, name, is_dummy)
        else:
            sec = self._sections[number]
            if name and not sec.name:
                sec.name = name
            # Only upgrade to dummy; never strip the dummy flag once set.
            if is_dummy:
                sec.is_dummy = True
        return self._sections[number]

    def get_section(self, number: int) -> Optional[SectionData]:
        return self._sections.get(number)

    # ------------------------------------------------------------------
    # Byte emission
    # ------------------------------------------------------------------

    def emit(self, section: int, offset: int, data: bytes,
             name: str = '') -> None:
        """
        Write *data* into *section* at byte *offset*.

        Creates the section if it does not yet exist.
        """
        sec = self.open_section(section, name)
        if not sec.is_dummy:
            sec.write_bytes(offset, data)

    def emit_reloc(self, section: int, byte_offset: int, bit_offset: int,
                   width: int, reloc_section: int, addend: int,
                   sign: int = 1) -> None:
        """Record a relocation entry in the given section."""
        sec = self.open_section(section)
        sec.add_reloc(Relocation(
            byte_offset  = byte_offset,
            bit_offset   = bit_offset,
            width        = width,
            section      = reloc_section,
            addend       = addend,
            sign         = sign,
        ))

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def emit_int(self, section: int, offset: int, value: int,
                 nbytes: int = 4) -> None:
        """Emit *value* as a big-endian integer of *nbytes* bytes."""
        raw = (value & 0xFFFF_FFFF_FFFF_FFFF).to_bytes(8, 'big')
        self.emit(section, offset, raw[-nbytes:])

    def emit_zeros(self, section: int, offset: int, nbytes: int) -> None:
        """Emit *nbytes* zero bytes at *offset*."""
        self.emit(section, offset, b'\x00' * nbytes)

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def sections(self) -> List[SectionData]:
        """Return all sections sorted by section number."""
        return sorted(self._sections.values(), key=lambda s: s.number)

    def total_bytes(self) -> int:
        return sum(s.size for s in self._sections.values()
                   if not s.is_dummy)

    def summary(self) -> str:
        lines = [f"Object code summary: {self.total_bytes()} bytes total"]
        for sec in self.sections():
            tag = ' (DSECT)' if sec.is_dummy else ''
            name = f" '{sec.name}'" if sec.name else ''
            lines.append(
                f"  Section {sec.number}{name}{tag}: {sec.size} bytes, "
                f"{len(sec.relocs)} relocs"
            )
        return '\n'.join(lines)
