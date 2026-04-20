
from ap_assembler.lexer import tokenize_text
from ap_assembler.symbol_table import SymbolTable
from ap_assembler.def_pass import DefPass
from ap_assembler.gen_pass import GenPass
from ap_assembler.object_writer import ObjectWriter
from ap_assembler.listing_writer import ListingWriter
from ap_assembler.hex_output import VerilogHexWriter

if __name__ == '__main__':
    source = """\
*  Small test program
         REF      M:LO         
A        SET      (8,6,9),15
         DISP     NUM(A)
         DISP     NUM(A(1))
START    EQU      0
         DATA     X'12345678'
         GEN,8,8,8,8 A(1,1),A(1,2),A(1,3),A(2)
A(1,1)   SET      9
         GEN,8,8,8,8 A(1,1),A(1,2),A(1,3),A(2)
         DATA     -1
         TEXT     'HELLO   '
         RES      1
         END      START
"""

    stmts     = list(tokenize_text(source))
    sym       = SymbolTable()
    DefPass(stmts, sym).run()              # Phase 2: build symbol table

    obj = ObjectWriter()
    lst = ListingWriter()
    GenPass(stmts, sym, obj, lst).run()    # Phase 3: emit bytes

    print(lst.render())                    # assembly listing
    print(VerilogHexWriter().render(obj))  # Verilog $readmemh hex
