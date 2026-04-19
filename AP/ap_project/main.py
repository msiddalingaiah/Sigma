
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

def assemble(source):
    stmts = list(tokenize_text(source))
    sym = SymbolTable()
    DefPass(stmts, sym).run()
    obj = ObjectWriter()
    lst = ListingWriter()
    GenPass(stmts, sym, obj, lst).run()
    return obj

def render(obj, **kwargs):
    """Return hex output as a string."""
    w = VerilogHexWriter(**kwargs)
    return w.render(obj)

if __name__ == '__main__':
    print("Hi")

    src = """\
*  Small test program
         REF      M:LO
A        SET      (8,6,9),15
START    EQU      0
         DATA     X'12345678'
         GEN,8,8,8,8 A(1,1),A(1,2),A(1,3),A(2)
         DATA     -1
         TEXT     'HELLO   '
         RES      1
         END      START
"""
    obj = assemble(src)
    text = render(obj, add_comments=True)
    print(text)
