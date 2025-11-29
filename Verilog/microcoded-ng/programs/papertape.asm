
            ORG         0x2A       ; Boot start

            LW,0        siodw      ; Loads the contents of location X'24' (X'11') into private memory register 0
            SIO,0       1          ; Write to IOP0, device 1 (console)
            WAIT,0      0

            ORG         0x50
siodw       GEN,32      0x01000000 | (message << 2) ; Bits 0 through 31 of I/O command doubleword. Specifies read order (02) and starting byte location X'A8'. Word location is X'A8'/4, or X'2A'
            GEN,32      0x020000FF ; No flags, suppress incorrect length. X'FF' specifies writing up to 255 bytes

dwaddr      GEN,32      siodw>>1

            ORG         0x60      ; 1024 words - 256 bytes
message     TEXTC       "Initial message\n"
