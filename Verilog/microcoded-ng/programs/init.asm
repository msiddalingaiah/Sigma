
            ORG         0x20       ; 3-682 Bootstrap program

            GEN,32      0x00000000 ; Reserved for I/O
            GEN,32      0x00000000 ; Reserved for I/O
            GEN,32      0x020000A8 ; Bits 0 through 31 of I/O command doubleword. Specifies read order (02) and starting byte location X'A8'. Word location is X'A8'/4, or X'2A'
            GEN,32      0x0E000058 ; Bits 32 through 63 of I/O command doubleword. Contains flag bits OE, which specify halt on transmission error, interrupt on unusual end, and suppress incorrect length. X'58' specifies reading 88 bytes into consecutive memory locations
            GEN,32      0x00000011 ; Command address of I/O command doubleword (shifted one bit position to the left in lOP to specify word location X'22')
            GEN,32      0x00000005 ; 0x00000XXX Address of I/O unit. (XXX represents address taken from UNIT ADDRESS switches)
            LW,0        0x24       ; Load Word instruction. Loads the contents of location X'24' (X'11') into private memory register 0
            ; GEN,32      0x01000000
            SIO,0       *0x25      ; Indirectly-addressed Start Input/Output instruction. Takes command doubleword from location specified in private memory register 0 and specifies device pointed to by address in location 25
            TIO,0       *0x25      ; Indirectly-addressed Test Input/Output instruction
            BCS,12      0x28         ; Loop until I/O complete. Program execution continues at next instruction address at 0x2A

            ORG         0x40       ; NAO trap
            XPSD,0      trap40_p

            BOUND       8
trap40_p    GEN,32      0
            GEN,32      0
            GEN,32      trap40
            GEN,32      0

            ORG         0x100
trap40      LW,0        dwaddr     ; Loads the command I/O double word address
            SIO,0       1          ; Write to IOP0, device 1 (console)
            WAIT,0      0

            BOUND       8
siodw       GEN,32      0x01000000 | (message << 2) ; I/O command doubleword 1, write order (01) | starting byte location.
            GEN,32      0x020000FF ; No flags, suppress incorrect length. X'FF' specifies writing up to 255 bytes

dwaddr      GEN,32      siodw>>1

message     TEXTC       "Trap 40 - Nonexistent instruction.\n"
