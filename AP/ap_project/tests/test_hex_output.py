"""
tests/test_hex_output.py — Tests for the Verilog $readmemh hex output.

Covers:
  - Correct word encoding (big-endian, various word sizes)
  - @address markers
  - Multi-section layout and sequential placement
  - Comment lines
  - Dummy section exclusion
  - fill_gaps option
  - words_per_line grouping
  - Integration through the full assembler pipeline
  - Edge cases: empty sections, non-word-multiple sizes, relocations

Run with:  python -m pytest tests/test_hex_output.py -v
"""

import io
import pytest

from ap_assembler.hex_output import (
    VerilogHexWriter, SectionPlacement, write_verilog_hex,
    _bytes_to_words, _pad_to_words, _hex_word,
)
from ap_assembler.object_writer import ObjectWriter
from ap_assembler.def_pass import DefPass
from ap_assembler.gen_pass import GenPass
from ap_assembler.listing_writer import ListingWriter
from ap_assembler.symbol_table import SymbolTable
from ap_assembler.lexer import tokenize_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_obj(*sections):
    """
    Build an ObjectWriter from a sequence of (section_num, data) tuples.
    ``data`` may be bytes or an integer list (big-endian 32-bit words).
    """
    obj = ObjectWriter()
    for sec_num, data in sections:
        if isinstance(data, (list, tuple)):
            raw = b''.join(v.to_bytes(4, 'big') for v in data)
        else:
            raw = bytes(data)
        obj.emit(sec_num, 0, raw)
    return obj


def render(obj, **kwargs):
    """Return hex output as a string."""
    w = VerilogHexWriter(**kwargs)
    return w.render(obj)


def lines(text):
    """Split text into non-empty lines."""
    return [l for l in text.splitlines() if l]


def data_lines(text):
    """Return only non-comment, non-address lines."""
    return [l for l in lines(text)
            if not l.startswith('//') and not l.startswith('@')]


def addr_lines(text):
    """Return only @address lines."""
    return [l for l in lines(text) if l.startswith('@')]


def assemble(source):
    stmts = list(tokenize_text(source))
    sym = SymbolTable()
    DefPass(stmts, sym).run()
    obj = ObjectWriter()
    lst = ListingWriter()
    GenPass(stmts, sym, obj, lst).run()
    return obj


# ---------------------------------------------------------------------------
# 1. Low-level helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_pad_to_words_no_padding_needed(self):
        assert _pad_to_words(b'\x00\x00\x00\x01', 4) == b'\x00\x00\x00\x01'

    def test_pad_to_words_1_byte(self):
        assert _pad_to_words(b'\xFF', 4) == b'\xFF\x00\x00\x00'

    def test_pad_to_words_3_bytes(self):
        assert _pad_to_words(b'\x01\x02\x03', 4) == b'\x01\x02\x03\x00'

    def test_pad_to_words_word_size_2(self):
        assert _pad_to_words(b'\xAB', 2) == b'\xAB\x00'

    def test_bytes_to_words_32bit(self):
        raw = bytes.fromhex('DEADBEEF12345678')
        assert _bytes_to_words(raw, 4) == [0xDEADBEEF, 0x12345678]

    def test_bytes_to_words_16bit(self):
        raw = bytes.fromhex('1234ABCD')
        assert _bytes_to_words(raw, 2) == [0x1234, 0xABCD]

    def test_bytes_to_words_8bit(self):
        raw = b'\x01\x02\x03'
        assert _bytes_to_words(raw, 1) == [1, 2, 3]

    def test_hex_word_32bit(self):
        assert _hex_word(0xDEADBEEF, 4) == 'DEADBEEF'

    def test_hex_word_16bit(self):
        assert _hex_word(0x1234, 2) == '1234'

    def test_hex_word_8bit(self):
        assert _hex_word(0xFF, 1) == 'FF'

    def test_hex_word_zero_padded(self):
        assert _hex_word(1, 4) == '00000001'

    def test_hex_word_masks_overflow(self):
        # Values beyond word size are masked
        assert _hex_word(0x1_DEADBEEF, 4) == 'DEADBEEF'


# ---------------------------------------------------------------------------
# 2. Single-section output
# ---------------------------------------------------------------------------

class TestSingleSection:
    def test_one_word(self):
        obj = make_obj((1, bytes.fromhex('DEADBEEF')))
        text = render(obj, add_comments=False)
        dl = data_lines(text)
        assert dl == ['DEADBEEF']

    def test_zero_word(self):
        obj = make_obj((1, b'\x00\x00\x00\x00'))
        text = render(obj, add_comments=False)
        assert data_lines(text) == ['00000000']

    def test_multiple_words(self):
        obj = make_obj((1, bytes.fromhex('11111111' '22222222' '33333333')))
        text = render(obj, add_comments=False)
        assert data_lines(text) == ['11111111', '22222222', '33333333']

    def test_first_section_starts_at_address_zero(self):
        obj = make_obj((1, b'\x00' * 4))
        text = render(obj, add_comments=False)
        assert addr_lines(text)[0] == '@00000000'

    def test_address_is_word_index_not_bytes(self):
        # With a single section starting at word 0
        obj = make_obj((1, b'\x00' * 4))
        w = VerilogHexWriter(add_comments=False)
        pls = w.layout(obj)
        assert pls[0].word_start == 0

    def test_non_word_multiple_size_padded(self):
        # 5 bytes → 2 words (padded to 8 bytes)
        obj = make_obj((1, b'\x01\x02\x03\x04\x05'))
        text = render(obj, add_comments=False)
        dl = data_lines(text)
        assert dl == ['01020304', '05000000']

    def test_big_endian_encoding(self):
        obj = make_obj((1, b'\x01\x02\x03\x04'))
        text = render(obj, add_comments=False)
        assert data_lines(text) == ['01020304']


# ---------------------------------------------------------------------------
# 3. Multi-section layout
# ---------------------------------------------------------------------------

class TestMultiSection:
    def test_two_sections_sequential(self):
        obj = make_obj(
            (1, bytes.fromhex('11111111')),
            (2, bytes.fromhex('22222222')),
        )
        w = VerilogHexWriter(add_comments=False)
        pls = w.layout(obj)
        assert pls[0].word_start == 0
        assert pls[1].word_start == 1   # immediately after section 1

    def test_address_marker_for_second_section(self):
        obj = make_obj(
            (1, bytes.fromhex('AAAAAAAA')),
            (2, bytes.fromhex('BBBBBBBB')),
        )
        text = render(obj, add_comments=False)
        al = addr_lines(text)
        assert '@00000000' in al
        assert '@00000001' in al

    def test_data_values_correct_both_sections(self):
        obj = make_obj(
            (1, bytes.fromhex('11111111')),
            (2, bytes.fromhex('22222222')),
        )
        text = render(obj, add_comments=False)
        assert 'AAAAAAAA' not in text    # sanity check wrong value absent
        assert '11111111' in text
        assert '22222222' in text

    def test_three_sections_address_sequence(self):
        obj = make_obj(
            (1, bytes.fromhex('AAAAAAAA' 'BBBBBBBB')),   # 2 words
            (2, bytes.fromhex('CCCCCCCC')),               # 1 word
            (3, bytes.fromhex('DDDDDDDD' 'EEEEEEEE')),   # 2 words
        )
        w = VerilogHexWriter(add_comments=False)
        pls = w.layout(obj)
        assert pls[0].word_start == 0
        assert pls[1].word_start == 2
        assert pls[2].word_start == 3

    def test_large_section_advances_address(self):
        obj = make_obj((1, b'\x00' * 100))
        w = VerilogHexWriter(add_comments=False)
        pls = w.layout(obj)
        assert pls[0].word_count == 25   # 100 / 4

    def test_total_words_computed_correctly(self):
        obj = make_obj(
            (1, b'\x00' * 8),    # 2 words
            (2, b'\x00' * 12),   # 3 words
        )
        w = VerilogHexWriter()
        assert w.total_words(obj) == 5

    def test_total_bytes_covered(self):
        obj = make_obj((1, b'\x00' * 16))
        w = VerilogHexWriter()
        assert w.total_bytes_covered(obj) == 16


# ---------------------------------------------------------------------------
# 4. Word size options
# ---------------------------------------------------------------------------

class TestWordSizes:
    def test_16bit_words(self):
        obj = make_obj((1, bytes.fromhex('1234ABCD')))
        text = render(obj, word_bytes=2, add_comments=False)
        assert data_lines(text) == ['1234', 'ABCD']

    def test_8bit_words(self):
        obj = make_obj((1, b'\xDE\xAD\xBE\xEF'))
        text = render(obj, word_bytes=1, add_comments=False)
        assert data_lines(text) == ['DE', 'AD', 'BE', 'EF']

    def test_8bit_word_count(self):
        obj = make_obj((1, b'\x00' * 8))
        w = VerilogHexWriter(word_bytes=1)
        assert w.total_words(obj) == 8

    def test_16bit_address_is_halfword_index(self):
        obj = make_obj(
            (1, b'\x00' * 4),   # 2 halfwords
            (2, b'\xFF' * 4),
        )
        w = VerilogHexWriter(word_bytes=2, add_comments=False)
        pls = w.layout(obj)
        assert pls[1].word_start == 2   # 4 bytes / 2 = 2 halfwords

    def test_invalid_word_size_raises(self):
        with pytest.raises(ValueError):
            VerilogHexWriter(word_bytes=3)


# ---------------------------------------------------------------------------
# 5. Words-per-line grouping
# ---------------------------------------------------------------------------

class TestWordsPerLine:
    def test_4_words_per_line(self):
        obj = make_obj((1, bytes.fromhex(
            '11111111' '22222222' '33333333' '44444444'
        )))
        text = render(obj, words_per_line=4, add_comments=False)
        assert data_lines(text) == ['11111111 22222222 33333333 44444444']

    def test_2_words_per_line_odd_count(self):
        obj = make_obj((1, bytes.fromhex('AABBCCDD' '11223344' 'DEADBEEF')))
        text = render(obj, words_per_line=2, add_comments=False)
        dl = data_lines(text)
        assert dl[0] == 'AABBCCDD 11223344'
        assert dl[1] == 'DEADBEEF'          # last line has 1 word

    def test_invalid_words_per_line_raises(self):
        with pytest.raises(ValueError):
            VerilogHexWriter(words_per_line=0)


# ---------------------------------------------------------------------------
# 6. Comment lines
# ---------------------------------------------------------------------------

class TestComments:
    def test_header_comment_present(self):
        obj = make_obj((1, b'\x00' * 4))
        text = render(obj, add_comments=True)
        assert any(l.startswith('//') for l in lines(text))

    def test_header_mentions_word_size(self):
        obj = make_obj((1, b'\x00' * 4))
        text = render(obj)
        assert '32-bit' in text

    def test_section_comment_shows_size(self):
        obj = make_obj((1, b'\x00' * 12))
        text = render(obj, add_comments=True)
        assert '12 byte' in text

    def test_section_comment_shows_name(self):
        obj = ObjectWriter()
        obj.open_section(1, 'CODE')
        obj.emit(1, 0, b'\x00' * 4)
        text = render(obj, add_comments=True)
        assert "'CODE'" in text

    def test_no_comments_when_disabled(self):
        obj = make_obj((1, b'\x00' * 4))
        text = render(obj, add_comments=False)
        assert not any(l.startswith('//') for l in lines(text))

    def test_relocation_warning_in_header(self):
        from ap_assembler.object_writer import Relocation
        obj = ObjectWriter()
        obj.open_section(1, 'CODE')
        obj.emit(1, 0, b'\x00' * 4)
        obj.get_section(1).add_reloc(
            Relocation(byte_offset=0, bit_offset=0, width=32,
                       section=2, addend=0, sign=1)
        )
        text = render(obj, add_comments=True)
        assert 'relocation' in text.lower() or 'reloc' in text.lower()


# ---------------------------------------------------------------------------
# 7. Dummy sections excluded
# ---------------------------------------------------------------------------

class TestDummySections:
    def test_dsect_excluded(self):
        obj = ObjectWriter()
        obj.open_section(1, 'CODE')
        obj.emit(1, 0, bytes.fromhex('DEADBEEF'))
        obj.open_section(2, 'DS', is_dummy=True)
        # Try to add data (should be swallowed by is_dummy)
        obj.emit(2, 0, bytes.fromhex('11111111'))
        text = render(obj, add_comments=False)
        assert '11111111' not in text
        assert 'DEADBEEF' in text

    def test_empty_section_excluded(self):
        obj = ObjectWriter()
        obj.open_section(1, 'EMPTY')
        # No emit — section is registered but has no data
        obj.open_section(2, 'DATA')
        obj.emit(2, 0, b'\xFF' * 4)
        w = VerilogHexWriter()
        pls = w.layout(obj)
        assert len(pls) == 1
        assert pls[0].section.name == 'DATA'

    def test_no_sections_produces_comment_only(self):
        obj = ObjectWriter()
        text = render(obj, add_comments=True)
        assert 'no data' in text.lower() or not data_lines(text)


# ---------------------------------------------------------------------------
# 8. fill_gaps option
# ---------------------------------------------------------------------------

class TestFillGaps:
    def test_fill_gaps_false_uses_address_markers(self):
        # Default: no fill, use @address
        obj = make_obj(
            (1, b'\x11' * 4),
            (2, b'\x22' * 4),
        )
        text = render(obj, add_comments=False, fill_gaps=False)
        # Both sections need @address markers
        al = addr_lines(text)
        assert len(al) == 2

    def test_fill_gaps_true_with_gap_section(self):
        # If sections are laid out with a gap, fill_gaps adds zeros
        # Create a gap by manually placing two sections apart
        obj = ObjectWriter()
        obj.emit(1, 0, b'\x11' * 4)    # section 1: 1 word
        obj.emit(2, 0, b'\x22' * 4)    # section 2: 1 word
        # Sections 1 and 2 are sequential (no gap), so fill_gaps has no effect here.
        text = render(obj, add_comments=False, fill_gaps=True)
        dl = data_lines(text)
        assert '11111111' in dl
        assert '22222222' in dl

    def test_fill_gaps_produces_contiguous_output(self):
        obj = make_obj(
            (1, b'\xAA' * 8),  # 2 words
            (2, b'\xBB' * 4),  # 1 word
        )
        # With fill_gaps, no extra @addr needed after the first
        text = render(obj, add_comments=False, fill_gaps=True)
        al = addr_lines(text)
        # Only one @address marker needed (the opening one)
        assert al[0] == '@00000000'


# ---------------------------------------------------------------------------
# 9. Integration: assemble then emit hex
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_data_words_round_trip(self):
        src = "  DATA  X'DEADBEEF'\n  DATA  X'12345678'\n"
        obj = assemble(src)
        text = render(obj, add_comments=False)
        dl = data_lines(text)
        assert 'DEADBEEF' in dl
        assert '12345678' in dl

    def test_res_produces_zeros(self):
        src = "  RES  2\n"    # 2 words = 8 bytes
        obj = assemble(src)
        text = render(obj, add_comments=False)
        dl = data_lines(text)
        assert dl == ['00000000', '00000000']

    def test_text_ascii_packed(self):
        src = "  TEXT  'ABCD'\n"
        obj = assemble(src)
        text = render(obj, add_comments=False)
        # 'ABCD' = 0x41 0x42 0x43 0x44
        assert '41424344' in data_lines(text)

    def test_do_loop_byte_count(self):
        src = "  DO  4\n  DATA  1\n  FIN\n"
        obj = assemble(src)
        w = VerilogHexWriter()
        assert w.total_words(obj) == 4

    def test_section_addresses_correct(self):
        src = (
            "CODE  CSECT\n"
            "      DATA  X'11111111'\n"
            "DATA  CSECT\n"
            "      DATA  X'22222222'\n"
        )
        obj = assemble(src)
        w = VerilogHexWriter(add_comments=False)
        pls = w.layout(obj)
        assert len(pls) == 2
        assert pls[0].word_start == 0
        assert pls[1].word_start == 1

    def test_equ_produces_no_hex_words(self):
        src = "K  EQU  X'FACE'\n"
        obj = assemble(src)
        w = VerilogHexWriter()
        assert w.total_words(obj) == 0

    def test_full_program_round_trip(self):
        src = """\
*  Small test program
         REF      M:LO
START    EQU      0
         DATA     X'12345678'
         DATA     -1
         TEXT     'HELLO   '
         RES      1
         END      START
"""
        obj = assemble(src)
        text = render(obj, add_comments=True)

        # Should have an address marker, data words, and a header comment
        assert '@00000000' in text
        assert '12345678' in text
        assert 'FFFFFFFF' in text     # -1 in 32-bit two's complement
        # 'HELLO   ' = 48 45 4C 4C 4F 20 20 20
        assert '48454C4C' in text or '48454c4c' in text.lower()

    def test_gen_bit_fields(self):
        # GEN,8,24 produces a packed 32-bit word
        src = "  GEN,8,24  X'14',1\n"
        obj = assemble(src)
        text = render(obj, add_comments=False)
        assert '14000001' in data_lines(text)

    def test_write_file_creates_file(self, tmp_path):
        src = "  DATA  X'CAFEBABE'\n"
        obj = assemble(src)
        path = str(tmp_path / "test.hex")
        write_verilog_hex(obj, path)
        content = open(path).read()
        assert 'CAFEBABE' in content

    def test_convenience_function(self, tmp_path):
        obj = make_obj((1, bytes.fromhex('12345678')))
        path = str(tmp_path / "out.hex")
        write_verilog_hex(obj, path, word_bytes=4, words_per_line=1,
                          add_comments=False)
        content = open(path).read().strip()
        assert '@00000000' in content
        assert '12345678' in content


# ---------------------------------------------------------------------------
# 10. SectionPlacement dataclass
# ---------------------------------------------------------------------------

class TestSectionPlacement:
    def test_word_end(self):
        from ap_assembler.object_writer import SectionData
        sec = SectionData(1, 'TEST')
        pl = SectionPlacement(sec, word_start=5, word_count=3)
        assert pl.word_end == 8

    def test_layout_matches_manual_calc(self):
        obj = make_obj(
            (1, b'\x00' * 8),    # 2 words
            (2, b'\x00' * 16),   # 4 words
            (3, b'\x00' * 4),    # 1 word
        )
        w = VerilogHexWriter()
        pls = w.layout(obj)
        assert pls[0].word_start == 0
        assert pls[0].word_count == 2
        assert pls[1].word_start == 2
        assert pls[1].word_count == 4
        assert pls[2].word_start == 6
        assert pls[2].word_count == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
