
            ORG         0x20       ; 3-682 Bootstrap program

            GEN,32      0x00000000 ; Reserved for I/O
            GEN,32      0x00000000 ; Reserved for I/O
            GEN,32      0x020000A8 ; Bits 0 through 31 of I/O command doubleword. Specifies read order (02) and starting byte location X'A8'. Word location is X'A8'/4, or X'2A'
            GEN,32      0x0E000058 ; Bits 32 through 63 of I/O command doubleword. Contains flag bits OE, which specify halt on transmission error, interrupt on unusual end, and suppress incorrect length. X'58' specifies reading 88 bytes into consecutive memory locations
            GEN,32      0x00000011 ; Command address of I/O command doubleword (shifted one bit position to the left in lOP to specify word location X'22')
            GEN,32      0x00000003 ; 0x00000XXX Address of I/O unit. (XXX represents address taken from UNIT ADDRESS switches)
            LW,0        0x24       ; Load Word instruction. Loads the contents of location X'24' (X'11') into private memory register 0
            SIO,0       *0x25      ; Indirectly-addressed Start Input/Output instruction. Takes command doubleword from location specified in private memory register 0 and specifies device pointed to by address in location 25
            TIO,0       *0x25      ; Indirectly-addressed Test Input/Output instruction
            BCS,12      28         ; Loop until I/O complete. Program execution continues at next instruction address at 0x2A

            ORG         0x3C0      ; 1024 words - 256 bytes
message     TEXTC       "Initial message\n"
