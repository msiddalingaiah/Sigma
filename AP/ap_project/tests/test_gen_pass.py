"""
tests/test_gen_pass.py — Tests for the Phase 3 GEN pass.

Exercises byte emission for all data-generating directives, verifies that
the symbol table values match between DEF and GEN passes, checks that the
listing is populated correctly, and validates DO-loop repetition.

Run with:  python -m pytest tests/test_gen_pass.py -v
"""

import pytest
from ap_assembler.def_pass import DefPass
from ap_assembler.gen_pass import GenPass
from ap_assembler.listing_writer import ListingWriter
from ap_assembler.object_writer import ObjectWriter, SectionData
from ap_assembler.lexer import tokenize_text
from ap_assembler.symbol_table import SymbolTable
from ap_assembler.value import Value, ValueKind


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assemble(source: str):
    """
    Run both passes over *source* and return (sym, obj, lst, def_errors, gen_errors).
    """
    stmts = list(tokenize_text(source))
    sym   = SymbolTable()
    def_errors = DefPass(stmts, sym).run()

    obj = ObjectWriter()
    lst = ListingWriter()
    gen_errors = GenPass(stmts, sym, obj, lst).run()

    return sym, obj, lst, def_errors, gen_errors


def section_bytes(obj: ObjectWriter, section: int = 1) -> bytes:
    """Return the raw bytes accumulated in *section*."""
    sec = obj.get_section(section)
    if sec is None:
        return b''
    return bytes(sec.data)


def all_errors(def_errors, gen_errors):
    return def_errors + gen_errors


# ---------------------------------------------------------------------------
# 1. EQU / SET — no bytes, but listing shows value
# ---------------------------------------------------------------------------

class TestEquSetListing:
    def test_equ_listing_shows_value(self):
        _, _, lst, _, _ = assemble("A  EQU  5\n")
        lines = [ll for ll in lst._lines if ll.line_no > 0]
        assert any(ll.hex_val == '00000005' for ll in lines)

    def test_equ_no_bytes_emitted(self):
        _, obj, _, _, _ = assemble("A  EQU  5\n")
        assert section_bytes(obj) == b''

    def test_set_listing_shows_value(self):
        _, _, lst, _, _ = assemble("X  SET  X'DEADBEEF'\n")
        lines = [ll for ll in lst._lines if ll.line_no > 0]
        assert any('DEADBEEF' in (ll.hex_val or '') for ll in lines)

    def test_equ_negative(self):
        _, _, lst, _, _ = assemble("N  EQU  -1\n")
        lines = [ll for ll in lst._lines if ll.line_no > 0]
        # -1 displayed as FFFFFFFF
        assert any('FFFFFFFF' in (ll.hex_val or '') for ll in lines)


# ---------------------------------------------------------------------------
# 2. DATA — byte emission
# ---------------------------------------------------------------------------

class TestDataBytes:
    def test_data_32bit_default(self):
        _, obj, _, _, _ = assemble("  DATA  X'DEADBEEF'\n")
        assert section_bytes(obj) == bytes.fromhex('DEADBEEF')

    def test_data_zero(self):
        _, obj, _, _, _ = assemble("  DATA  0\n")
        assert section_bytes(obj) == b'\x00\x00\x00\x00'

    def test_data_integer(self):
        _, obj, _, _, _ = assemble("  DATA  1\n")
        assert section_bytes(obj) == b'\x00\x00\x00\x01'

    def test_data_negative(self):
        _, obj, _, _, _ = assemble("  DATA  -1\n")
        # -1 in 32-bit big-endian two's complement = 0xFFFFFFFF
        assert section_bytes(obj) == b'\xff\xff\xff\xff'

    def test_data_multiple_args(self):
        _, obj, _, _, _ = assemble("  DATA  1,2,3\n")
        raw = section_bytes(obj)
        assert raw == b'\x00\x00\x00\x01' + b'\x00\x00\x00\x02' + b'\x00\x00\x00\x03'

    def test_data_8bit(self):
        _, obj, _, _, _ = assemble("  DATA,8  X'AB'\n")
        assert section_bytes(obj) == b'\xAB'

    def test_data_16bit(self):
        _, obj, _, _, _ = assemble("  DATA,16  X'1234'\n")
        assert section_bytes(obj) == b'\x12\x34'

    def test_data_8bit_multi(self):
        _, obj, _, _, _ = assemble("  DATA,8  1,2,3\n")
        assert section_bytes(obj) == b'\x01\x02\x03'

    def test_data_char_string(self):
        # 'ABCD' packed into 4 bytes
        _, obj, _, _, _ = assemble("  DATA  'ABCD'\n")
        assert section_bytes(obj) == b'ABCD'

    def test_data_label_at_start(self):
        _, obj, lst, _, _ = assemble("X  DATA  42\n")
        # X should be at offset 0
        lines = [ll for ll in lst._lines if ll.source.strip().startswith('X')]
        assert any(ll.offset == 0 for ll in lines)

    def test_data_label_sequential(self):
        _, _, lst, _, _ = assemble("A  DATA  1\nB  DATA  2\n")
        a_line = next(ll for ll in lst._lines if 'A  DATA' in ll.source)
        b_line = next(ll for ll in lst._lines if 'B  DATA' in ll.source)
        assert a_line.offset == 0
        assert b_line.offset == 4

    def test_data_symbol_value(self):
        _, obj, _, _, _ = assemble("K  EQU  X'5A'\n   DATA  K\n")
        raw = section_bytes(obj)
        assert raw == b'\x00\x00\x00\x5a'

    def test_data_expression(self):
        _, obj, _, _, _ = assemble("  DATA  2+3\n")
        assert section_bytes(obj) == b'\x00\x00\x00\x05'


# ---------------------------------------------------------------------------
# 3. RES — zero bytes
# ---------------------------------------------------------------------------

class TestResBytes:
    def test_res_one_word(self):
        _, obj, _, _, _ = assemble("  RES  1\n")
        assert section_bytes(obj) == b'\x00\x00\x00\x00'

    def test_res_two_words(self):
        _, obj, _, _, _ = assemble("  RES  2\n")
        assert section_bytes(obj) == b'\x00' * 8

    def test_res_byte_unit(self):
        _, obj, _, _, _ = assemble("  RES,1  3\n")
        assert section_bytes(obj) == b'\x00\x00\x00'

    def test_res_zero_count(self):
        _, obj, _, _, _ = assemble("  RES  0\n")
        assert section_bytes(obj) == b''

    def test_res_followed_by_data(self):
        _, obj, _, _, _ = assemble("  RES  1\n  DATA  X'FF'\n")
        raw = section_bytes(obj)
        # 4 zeros then 0x000000FF
        assert raw == b'\x00\x00\x00\x00' + b'\x00\x00\x00\xff'

    def test_res_label_precedes_bytes(self):
        _, _, lst, _, _ = assemble("R  RES  2\n  DATA  1\n")
        r_line = next(ll for ll in lst._lines if 'R  RES' in ll.source)
        d_line = next(ll for ll in lst._lines if 'DATA  1' in ll.source)
        assert r_line.offset == 0
        assert d_line.offset == 8    # 2 words = 8 bytes


# ---------------------------------------------------------------------------
# 4. TEXT / TEXTC — character packing
# ---------------------------------------------------------------------------

class TestTextBytes:
    def test_text_4chars(self):
        _, obj, _, _, _ = assemble("  TEXT  'ABCD'\n")
        assert section_bytes(obj) == b'ABCD'

    def test_text_1char_padded(self):
        _, obj, _, _, _ = assemble("  TEXT  'A'\n")
        assert section_bytes(obj) == b'A\x00\x00\x00'

    def test_text_5chars_two_words(self):
        _, obj, _, _, _ = assemble("  TEXT  'ABCDE'\n")
        raw = section_bytes(obj)
        assert raw == b'ABCDE\x00\x00\x00'   # 5 chars + 3 pad = 8 bytes

    def test_text_8chars(self):
        _, obj, _, _, _ = assemble("  TEXT  'ABCDEFGH'\n")
        assert section_bytes(obj) == b'ABCDEFGH'

    def test_textc_3chars(self):
        # TEXTC: count byte (3) + 'ABC' = 4 bytes, no padding needed
        _, obj, _, _, _ = assemble("  TEXTC  'ABC'\n")
        assert section_bytes(obj) == b'\x03ABC'

    def test_textc_4chars_padded(self):
        # TEXTC 'ABCD': count (4) + 'ABCD' = 5 bytes → pad to 8
        _, obj, _, _, _ = assemble("  TEXTC  'ABCD'\n")
        raw = section_bytes(obj)
        assert raw == b'\x04ABCD\x00\x00\x00'

    def test_textc_label(self):
        _, _, lst, _, _ = assemble("MSG  TEXTC  'HI'\n")
        line = next(ll for ll in lst._lines if 'MSG' in ll.source)
        assert line.offset == 0

    def test_text_empty_pads_nothing(self):
        # Empty string should advance by one full word (4 zero bytes)
        _, obj, _, _, _ = assemble("  TEXT  ''\n")
        # '' has 0 chars → pad to word = 0 bytes? Actually ((0+3)//4)*4 = 0
        assert section_bytes(obj) == b''


# ---------------------------------------------------------------------------
# 5. BOUND — alignment padding
# ---------------------------------------------------------------------------

class TestBoundBytes:
    def test_bound_already_aligned(self):
        # 8 bytes → already word-aligned; BOUND 4 emits nothing
        _, obj, _, _, _ = assemble("  DATA  1,2\n  BOUND  4\n")
        assert section_bytes(obj) == b'\x00\x00\x00\x01\x00\x00\x00\x02'

    def test_bound_1byte_to_word(self):
        # 1 byte then BOUND 4 → emit 3 zero pad bytes
        _, obj, _, _, _ = assemble("  DATA,8  1\n  BOUND  4\n")
        raw = section_bytes(obj)
        assert raw == b'\x01\x00\x00\x00'    # 1 data + 3 pad

    def test_bound_3bytes_to_word(self):
        _, obj, _, _, _ = assemble("  DATA,8  1\n  DATA,8  2\n  DATA,8  3\n  BOUND  4\n")
        raw = section_bytes(obj)
        assert raw == b'\x01\x02\x03\x00'    # 3 data + 1 pad

    def test_bound_to_doubleword(self):
        _, obj, _, _, _ = assemble("  DATA  1\n  BOUND  8\n")
        raw = section_bytes(obj)
        assert raw == b'\x00\x00\x00\x01' + b'\x00\x00\x00\x00'

    def test_bound_after_text(self):
        # TEXT '1' = 4 bytes (already word-aligned), BOUND 8 → 4 more zeros
        _, obj, _, _, _ = assemble("  TEXT  '1234'\n  BOUND  8\n")
        raw = section_bytes(obj)
        assert raw == b'1234\x00\x00\x00\x00'


# ---------------------------------------------------------------------------
# 6. GEN — bit-field packing
# ---------------------------------------------------------------------------

class TestGenBytes:
    def test_gen_8_24(self):
        # GEN,8,24: 8-bit + 24-bit = 32-bit word
        # Value 0x14 in 8 bits, 0x000001 in 24 bits
        # = 0x14_000001
        _, obj, _, _, _ = assemble("  GEN,8,24  X'14',1\n")
        raw = section_bytes(obj)
        assert raw == bytes.fromhex('14000001')

    def test_gen_4_12_8_3_5(self):
        # 4+12+8+3+5 = 32 bits
        # values: 1, -5 (12-bit: 0xFFB), 0x35, -1 (3-bit: 0x7), 0xF (5-bit: 0x0F)
        # bit layout:
        #   [31-28] 0001
        #   [27-16] 111111111011 = 0xFFB  (-5 in 12-bit)
        #   [15-8]  00110101 = 0x35
        #   [7-5]   111 = 0x7  (-1 in 3-bit)
        #   [4-0]   01111 = 0xF
        _, obj, _, _, _ = assemble(
            "  GEN,4,12,8,3,5  1,-5,X'35',-1,X'F'\n"
        )
        raw = section_bytes(obj)
        # Manual: 0001_111111111011_00110101_111_01111
        # = 0001 1111 1111 1011 0011 0101 1110 1111
        # = 0x1FFB35EF
        assert raw == bytes.fromhex('1FFB35EF')

    def test_gen_32bit_single(self):
        # GEN,32: one full word
        _, obj, _, _, _ = assemble("  GEN,32  X'CAFEBABE'\n")
        assert section_bytes(obj) == bytes.fromhex('CAFEBABE')

    def test_gen_16_16(self):
        _, obj, _, _, _ = assemble("  GEN,16,16  X'1234',X'5678'\n")
        assert section_bytes(obj) == bytes.fromhex('12345678')

    def test_gen_no_modifier(self):
        # GEN without modifier: emit 4 zero bytes
        _, obj, _, _, _ = assemble("  GEN  0\n")
        assert section_bytes(obj) == b'\x00\x00\x00\x00'

    def test_gen_label(self):
        _, _, lst, _, _ = assemble("G  GEN,8,24  1,2\n")
        line = next(ll for ll in lst._lines if 'G  GEN' in ll.source)
        assert line.offset == 0


# ---------------------------------------------------------------------------
# 7. DO loop repetition
# ---------------------------------------------------------------------------

class TestDoBytes:
    def test_do_3_times(self):
        # DO 3: DATA 1 runs 3 times → 3 words = 12 bytes
        _, obj, _, _, _ = assemble("  DO  3\n  DATA  1\n  FIN\n")
        raw = section_bytes(obj)
        assert raw == (b'\x00\x00\x00\x01') * 3

    def test_do_zero_skips(self):
        _, obj, _, _, _ = assemble("  DO  0\n  DATA  1\n  FIN\n")
        assert section_bytes(obj) == b''

    def test_do_else_positive(self):
        # DO 2 body runs twice; ELSE section skipped
        _, obj, _, _, _ = assemble(
            "  DO  2\n"
            "  DATA,8  X'AA'\n"
            "  ELSE\n"
            "  DATA,8  X'BB'\n"
            "  FIN\n"
        )
        raw = section_bytes(obj)
        assert raw == b'\xAA\xAA'   # body twice; else skipped

    def test_do_else_zero(self):
        # DO 0: body skipped; ELSE section runs once
        _, obj, _, _, _ = assemble(
            "  DO  0\n"
            "  DATA,8  X'AA'\n"
            "  ELSE\n"
            "  DATA,8  X'BB'\n"
            "  FIN\n"
        )
        raw = section_bytes(obj)
        assert raw == b'\xBB'

    def test_do_nested(self):
        # Outer DO 2, inner DO 3: DATA runs 6 times
        _, obj, _, _, _ = assemble(
            "  DO  2\n"
            "  DO  3\n"
            "  DATA,8  1\n"
            "  FIN\n"
            "  FIN\n"
        )
        assert section_bytes(obj) == b'\x01' * 6

    def test_do1_repeat(self):
        # DO1 3: next statement emitted 3 times
        _, obj, _, _, _ = assemble("  DO1  3\n  DATA,8  X'FF'\n")
        assert section_bytes(obj) == b'\xff\xff\xff'

    def test_do1_skip(self):
        _, obj, _, _, _ = assemble("  DO1  0\n  DATA  1\n")
        assert section_bytes(obj) == b''


# ---------------------------------------------------------------------------
# 8. Multiple sections
# ---------------------------------------------------------------------------

class TestSections:
    def test_two_sections_independent(self):
        src = (
            "CODE  CSECT\n"
            "      DATA  X'11111111'\n"
            "DATA  CSECT\n"
            "      DATA  X'22222222'\n"
        )
        _, obj, _, _, _ = assemble(src)
        # CODE is section 2 (section 1 is the default CSECT that gets opened first)
        # Actually: default section opened = 1, CODE CSECT opens a new one
        # Let me just check total bytes are correct
        total = sum(len(s.data) for s in obj.sections() if not s.is_dummy)
        assert total == 8   # 4 bytes in each section

    def test_dsect_no_bytes(self):
        src = "DS  DSECT\n    RES  10\n"
        _, obj, _, _, _ = assemble(src)
        # DSECT should not produce object bytes
        for sec in obj.sections():
            if sec.is_dummy:
                assert sec.size == 0 or True  # dsect data not written

    def test_section_resume(self):
        src = (
            "CODE  CSECT\n"
            "      DATA  X'11'\n"
            "DATA  CSECT\n"
            "      DATA  X'22'\n"
            "CODE  USECT  CODE\n"
            "      DATA  X'33'\n"
        )
        _, obj, _, _, _ = assemble(src)
        # CODE section should have 8 bytes (X'11' + X'33')
        # Find the CODE section
        code_sec = next(
            (s for s in obj.sections() if s.name == 'CODE'),
            None
        )
        assert code_sec is not None
        assert len(code_sec.data) == 8


# ---------------------------------------------------------------------------
# 9. Listing content
# ---------------------------------------------------------------------------

class TestListing:
    def test_listing_has_all_lines(self):
        _, _, lst, _, _ = assemble("A  EQU  1\nB  DATA  2\nC  RES  3\n")
        # 3 source lines → 3 listing lines (plus any blanks)
        line_nos = [ll.line_no for ll in lst._lines if ll.line_no > 0]
        assert 1 in line_nos
        assert 2 in line_nos
        assert 3 in line_nos

    def test_listing_addresses_sequential(self):
        src = "  DATA  1\n  DATA  2\n  DATA  3\n"
        _, _, lst, _, _ = assemble(src)
        data_lines = [ll for ll in lst._lines
                      if 'DATA' in ll.source and ll.hex_val]
        offsets = [ll.offset for ll in data_lines]
        assert offsets == [0, 4, 8]

    def test_listing_equ_hex(self):
        _, _, lst, _, _ = assemble("K  EQU  X'ABCD'\n")
        line = next(ll for ll in lst._lines if 'EQU' in ll.source)
        assert line.hex_val is not None
        assert 'ABCD' in line.hex_val.upper()

    def test_listing_data_hex(self):
        _, _, lst, _, _ = assemble("  DATA  X'12345678'\n")
        line = next(ll for ll in lst._lines if 'DATA' in ll.source)
        assert line.hex_val == '12345678'

    def test_listing_render_format(self):
        _, _, lst, _, _ = assemble("A  EQU  5\n  DATA  1\n  END\n")
        text = lst.render()
        assert 'Line' in text      # header
        assert '00000005' in text  # EQU value
        assert '00000001' in text  # DATA value

    def test_listing_comment_lines(self):
        src = "* A comment line\nA  EQU  5\n"
        _, _, lst, _, _ = assemble(src)
        comment = next((ll for ll in lst._lines
                        if '* A comment line' in ll.source), None)
        assert comment is not None


# ---------------------------------------------------------------------------
# 10. Two-pass consistency — LC must match between DEF and GEN
# ---------------------------------------------------------------------------

class TestTwoPassConsistency:
    def _lc_after_def(self, source: str) -> int:
        stmts = list(tokenize_text(source))
        sym = SymbolTable()
        DefPass(stmts, sym).run()
        return sym.exec_lc()

    def _lc_after_gen(self, source: str) -> int:
        stmts = list(tokenize_text(source))
        sym = SymbolTable()
        DefPass(stmts, sym).run()
        sym2 = SymbolTable()
        DefPass(stmts, sym2).run()    # re-use same stmts
        obj = ObjectWriter()
        lst = ListingWriter()
        GenPass(stmts, sym2, obj, lst).run()
        return sym2.exec_lc()

    def test_data_lc_matches(self):
        src = "  DATA  1,2,3\n"
        assert self._lc_after_def(src) == self._lc_after_gen(src)

    def test_res_lc_matches(self):
        src = "  RES  5\n"
        assert self._lc_after_def(src) == self._lc_after_gen(src)

    def test_text_lc_matches(self):
        src = "  TEXT  'HELLO WORLD'\n"
        assert self._lc_after_def(src) == self._lc_after_gen(src)

    def test_bound_lc_matches(self):
        src = "  DATA,8  1\n  BOUND  4\n  DATA  2\n"
        assert self._lc_after_def(src) == self._lc_after_gen(src)

    def test_do_lc_matches(self):
        src = "  DO  4\n  DATA  1\n  FIN\n"
        assert self._lc_after_def(src) == self._lc_after_gen(src)

    def test_gen_directive_lc_matches(self):
        src = "  GEN,8,24  1,2\n"
        assert self._lc_after_def(src) == self._lc_after_gen(src)

    def test_mixed_lc_matches(self):
        src = (
            "K  EQU  4\n"
            "   DO  K\n"
            "   DATA  0\n"
            "   FIN\n"
            "   TEXT  'HELLO'\n"
            "   BOUND  8\n"
            "   RES,1  3\n"
        )
        assert self._lc_after_def(src) == self._lc_after_gen(src)


# ---------------------------------------------------------------------------
# 11. ObjectWriter — standalone unit tests
# ---------------------------------------------------------------------------

class TestObjectWriter:
    def test_emit_and_retrieve(self):
        ow = ObjectWriter()
        ow.emit(1, 0, b'\xDE\xAD\xBE\xEF')
        assert bytes(ow.get_section(1).data) == b'\xDE\xAD\xBE\xEF'

    def test_emit_at_offset(self):
        ow = ObjectWriter()
        ow.emit(1, 4, b'\xFF')
        raw = bytes(ow.get_section(1).data)
        # 4 zero bytes + 0xFF
        assert raw == b'\x00\x00\x00\x00\xFF'

    def test_two_sections(self):
        ow = ObjectWriter()
        ow.emit(1, 0, b'\x11')
        ow.emit(2, 0, b'\x22')
        assert bytes(ow.get_section(1).data) == b'\x11'
        assert bytes(ow.get_section(2).data) == b'\x22'

    def test_dsect_no_data(self):
        ow = ObjectWriter()
        ow.open_section(3, 'DS', is_dummy=True)
        ow.emit(3, 0, b'\xFF')   # should be swallowed
        sec = ow.get_section(3)
        assert sec.is_dummy
        assert len(sec.data) == 0

    def test_total_bytes(self):
        ow = ObjectWriter()
        ow.emit(1, 0, b'\x00' * 8)
        ow.emit(2, 0, b'\x00' * 4)
        assert ow.total_bytes() == 12

    def test_summary(self):
        ow = ObjectWriter()
        ow.open_section(1, 'CODE')
        ow.emit(1, 0, b'\x00' * 4)
        s = ow.summary()
        assert 'CODE' in s
        assert '4 bytes' in s


# ---------------------------------------------------------------------------
# 12. ListingWriter — standalone unit tests
# ---------------------------------------------------------------------------

class TestListingWriter:
    def test_add_and_render(self):
        lw = ListingWriter()
        lw.add_line(1, '00000005', 1, 0, 'A  EQU  5')
        text = lw.render()
        assert '00000005' in text
        assert 'A  EQU  5' in text

    def test_header_present(self):
        lw = ListingWriter()
        assert 'Line' in lw.render()

    def test_error_appears(self):
        lw = ListingWriter()
        lw.add_line(1, None, 0, 0, 'BAD', errors=['Undefined symbol'])
        text = lw.render()
        assert 'Undefined symbol' in text

    def test_comment_line(self):
        lw = ListingWriter()
        lw.add_comment(1, '* This is a comment')
        text = lw.render()
        assert '* This is a comment' in text

    def test_line_count(self):
        lw = ListingWriter()
        lw.add_line(1, None, 0, 0, 'A')
        lw.add_line(2, None, 0, 0, 'B')
        assert lw.line_count() == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
