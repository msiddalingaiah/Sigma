
            ORG         0x2A       ; Boot start

start       LW,0        dwaddr     ; Loads the contents of location X'24' (X'11') into private memory register 0
            SIO,0       1          ; Write to IOP0, device 1 (console)
            LCFI,2      0x90
            SIO,0       1          ; Write to IOP0, device 1 (console)
            WAIT,0      0

            BOUND       8
siodw       GEN,32      0x01000000 | (message << 2) ; Bits 0 through 31 of I/O command doubleword. Specifies write order (01) and starting byte location.
            GEN,32      0x020000FF ; No flags, suppress incorrect length. X'FF' specifies writing up to 255 bytes

dwaddr      GEN,32      siodw>>1

message     TEXTC       "Microcode-NG here.\n"
