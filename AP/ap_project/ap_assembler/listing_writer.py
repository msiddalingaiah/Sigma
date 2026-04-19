"""
ap_assembler/listing_writer.py — Assembly listing formatter.

Produces the LO (listing output) file.  Each source line, once processed,
generates one or more listing lines.  The format is:

  NNNNN  HHHHHHHH  SS OOOOOO  source text

  NNNNN   – source line number (5 digits)
  HHHHHHHH – 8 hex digits: first 4 bytes of generated code, or the integer
              value of an EQU/SET expression, or spaces if nothing generated.
  SS       – 2 hex digits: control section number at the time of generation.
  OOOOOO   – 6 hex digits: byte offset of the first byte generated.
  source   – original source text.

Error markers appear on lines immediately following the erroneous line:
  *E* message text

The original AP listing is 108 characters wide and uses EBCDIC.  This Python
implementation produces readable ASCII, wide enough for typical terminal use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import IO, List, Optional


# ---------------------------------------------------------------------------
# ListingLine — one record in the listing
# ---------------------------------------------------------------------------

@dataclass
class ListingLine:
    """
    A single line of assembly listing output.

    line_no  : source file line number (0 for synthetic lines)
    hex_val  : 8 upper-hex-char value string, or None
    section  : control section number when the line was processed
    offset   : byte offset within the section at the start of generation
    source   : original source text (may be blank for synthetic/error lines)
    errors   : list of error/warning message strings for this line
    """
    line_no:  int
    hex_val:  Optional[str]      # None means blank (no generation)
    section:  int
    offset:   int
    source:   str                = ''
    errors:   List[str]         = field(default_factory=list)


# ---------------------------------------------------------------------------
# ListingWriter
# ---------------------------------------------------------------------------

# Column widths
_W_LINENO = 5
_W_HEX    = 8
_W_ADDR   = 9    # "SS OOOOOO"

HEADER = (
    f"{'Line':>{_W_LINENO}}  "
    f"{'Hex':^{_W_HEX}}  "
    f"{'Address':^{_W_ADDR}}  "
    f"Source"
)
RULE = '-' * (len(HEADER) + 30)


class ListingWriter:
    """
    Collects listing lines and renders them to text.

    Usage::

        lw = ListingWriter()
        lw.add_line(lineno=1, hex_val='00000005', section=1,
                    offset=0, source='A1  EQU  5')
        print(lw.render())
    """

    def __init__(self, title: str = 'AP ASSEMBLER LISTING') -> None:
        self._title  = title
        self._lines: List[ListingLine] = []

    # ------------------------------------------------------------------
    # Adding lines
    # ------------------------------------------------------------------

    def add_line(self, line_no: int,
                 hex_val:  Optional[str],
                 section:  int,
                 offset:   int,
                 source:   str,
                 errors:   Optional[List[str]] = None) -> None:
        """
        Add one listing line.

        *hex_val* should be exactly 8 uppercase hex characters, or None.
        """
        self._lines.append(ListingLine(
            line_no = line_no,
            hex_val = hex_val,
            section = section,
            offset  = offset,
            source  = source.rstrip('\n'),
            errors  = errors or [],
        ))

    def add_comment(self, line_no: int, source: str) -> None:
        """Add a comment line (no hex, no address)."""
        self._lines.append(ListingLine(
            line_no = line_no,
            hex_val = None,
            section = 0,
            offset  = 0,
            source  = source.rstrip('\n'),
        ))

    def add_error(self, message: str, line_no: int = 0) -> None:
        """
        Append an error message to the most recently added line, or as a
        standalone error line if no lines exist.
        """
        if self._lines:
            self._lines[-1].errors.append(message)
        else:
            self._lines.append(ListingLine(
                line_no = line_no,
                hex_val = None,
                section = 0,
                offset  = 0,
                source  = f'*** {message}',
            ))

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    @staticmethod
    def _format_line(ll: ListingLine) -> str:
        """Render one ListingLine to a fixed-format string."""
        # Line number: right-justified in 5 chars
        lineno_s = f'{ll.line_no:5d}' if ll.line_no > 0 else '     '

        # Hex value: 8 uppercase hex chars or spaces
        hex_s = ll.hex_val.upper()[:8].ljust(8) if ll.hex_val else ' ' * 8

        # Address: "SS OOOOOO" (section + byte offset)
        addr_s = f'{ll.section:02X} {ll.offset:06X}' if (ll.hex_val or ll.offset) else ' ' * _W_ADDR

        # Source text (keep it to a reasonable width)
        src = ll.source[:72]

        return f'{lineno_s}  {hex_s}  {addr_s}  {src}'

    def render(self) -> str:
        """Return the complete listing as a single string."""
        parts = [
            self._title,
            RULE,
            HEADER,
            RULE,
        ]
        for ll in self._lines:
            parts.append(self._format_line(ll))
            for err in ll.errors:
                parts.append(f"{'':>{_W_LINENO}}  {'*ERR*':8s}  {'':9s}  {err}")
        parts.append(RULE)
        return '\n'.join(parts)

    def write(self, dest: IO[str]) -> None:
        """Write the rendered listing to a file-like object."""
        dest.write(self.render())
        dest.write('\n')

    def write_file(self, path: str) -> None:
        """Write the rendered listing to *path*."""
        with open(path, 'w', encoding='ascii', errors='replace') as f:
            self.write(f)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def line_count(self) -> int:
        return len(self._lines)

    def error_count(self) -> int:
        return sum(len(ll.errors) for ll in self._lines)
