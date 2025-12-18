
            ORG         0x2A       ; Boot start
start       LW,0        dwaddr     ; Loads the contents of location X'24' (X'11') into private memory register 0
            SIO,0       1          ; Write to IOP0, device 1 (console)

            LW,0        st_dw      ; Load Word instruction. Loads the contents of location X'24' (X'11') into private memory register 0
            SIO,0       5          ; Indirectly-addressed Start Input/Output instruction. Takes command doubleword from location specified in private memory register 0 and specifies device pointed to by address in location 25
st_tio      TIO,0       5          ; Indirectly-addressed Test Input/Output instruction
            BCS,12      st_tio     ; Loop until I/O complete. Program execution continues at next instruction address at 0x2A

            BCR,0       start2
            WAIT,0      0

            BOUND       8
st_sio      GEN,32      0x020000A8 ; I/O command 0. Read order (02), byte location X'A8'. Word location is X'A8'/4, or X'2A'
            GEN,32      0x0E000400 ; I/O command 1. X'1000' specifies reading 4096 bytes, 1024 words
siodw       GEN,32      0x01000000 | (message << 2) ; Bits 0 through 31 of I/O command doubleword. Specifies write order (01) and starting byte location.
            GEN,32      0x020000FF ; No flags, suppress incorrect length. X'FF' specifies writing up to 255 bytes
st_dw       GEN,32      st_sio>>1  ; DW address of I/O command doubleword
dwaddr      GEN,32      siodw>>1

message     TEXTC       "Microcode-NG here.\n"

            ; Traps
            ORG         0x40       ; NAO trap
            XPSD,0      trap40_p

            BOUND       8
trap40_p    GEN,32      0
            GEN,32      0
            GEN,32      trap40
            GEN,32      0

            ; Full start
            ORG         0x100
start2      LW,0        dwaddr
            SIO,0       1          ; Write to IOP0, device 1 (console)
            LW,1        0x40
            STW,1       0x200
            LW,2        0x200
            STW,2       0x200
            WAIT,0      0

trap40      LW,0        t40_dw     ; Loads the command I/O double word address
            SIO,0       1          ; Write to IOP0, device 1 (console)
            WAIT,0      0

            BOUND       8
t40_sio     GEN,32      0x01000000 | (t40_msg << 2) ; I/O command doubleword 1, write order (01) | starting byte location.
            GEN,32      0x020000FF ; No flags, suppress incorrect length. X'FF' specifies writing up to 255 bytes

t40_dw      GEN,32      t40_sio>>1

t40_msg     TEXTC       "Trap 40 - Nonexistent instruction.\n"
