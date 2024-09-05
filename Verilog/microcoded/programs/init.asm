
        ORG         0x20       ; 3-682 Bootstrap program

        GEN,32      0x00000000 ; Reserved for I/O
        GEN,32      0x00000000 ; Reserved for I/O
        GEN,32      0x020000A8 ; Bits 0 through 31 of I/O command doubleword. Specifies read order (02) and starting byte location X'A81. Word location is X'A8' 1/4, or X'2A'
        GEN,32      0x0E000058 ; Bits 32 through 63 of I/O command doubleword. Contains flag bits OE, which specify halt on transmission error, interrupt on unusual end, and suppress incorrect length. X'581 specifies reading 88 bytes into consecutive memory locations
        GEN,32      0x00000011 ; Command address of I/O command doubleword (shifted one bit position to the left in lOP to specify word location X'221)
        GEN,32      0x00000000 ; 0x00000XXX Address of I/O unit. (XXX represents address taken from UNIT ADDRESS switches)
        LW,0        0x24       ; Load Word instruction. Loads the contents of location X'24' (X'11') into private memory register 0
        SIO,0       *0x25      ; Indirectly-addressed Start Input/Output instruction. Takes command doubleword from location specified in private memory register 0 and specifies device pointed to by address in location 25
        TIO,0       *0x25      ; Indirectly-addressed Test Input/Output instruction
        BCS,12      28         ; Loop until I/O complete. Program execution continues at next instruction address at 0x2A

        LI,0        TEXTC("Call me Ishmael...\n")
        BAL,15      puts

        LI,1        0x1ffff
        CW,1        GEN32(0x1ffff)
        BCR,3       ci_pass
        LI,0        TEXTC("CW failed.\n")
        BAL,15      puts
        WAIT,0      0

ci_pass    GEN,1,7,4,20      0, 0x22, 1, '0'
        LI,3        9
lp1     AI,1        1
        WD,1        0
        BDR,3       lp1
        LI,1        '\n'
        WD,1        0

        LI,8        0
        LW,9        GEN32(355000000)
        DW,8        GEN32(113)
        CI,8        104
        BCR,3       test_q
        LI,0        TEXTC("DW Remainder failed.\n")
        BAL,15      puts
        WAIT,0      0

test_q    CW,9        GEN32(3141592)
        BCR,3       test_mi
        LI,0        TEXTC("DW quotient failed.\n")
        BAL,15      puts
        WAIT,0      0

test_mi    LI,10       113
        MI,10       31415
        CW,11       GEN32(113*31415)
        BCR,3       test_mw
        LI,0        TEXTC("MI Failed.\n")
        BAL,15      puts
        WAIT,0      0

test_mw    LI,10       113
        MW,10       GEN32(31415)
        CW,11       GEN32(113*31415)
        BCR,3       test_stw1
        LI,0        TEXTC("MW Failed.\n")
        BAL,15      puts
        WAIT,0      0

test_stw1:    LI,0    0
        CW,0        temp
        BCR,3       test_stw2
        LI,0        TEXTC("STW1 Failed.\n")
        BAL,15      puts
        WAIT,0      0

test_stw2:    LI,0    0x1234
        STW,0       temp
        CW,0        temp
        BCR,3       test_stb1
        LI,0        TEXTC("STW2 Failed.\n")
        BAL,15      puts
        WAIT,0      0

test_stb1:    LI,1        1
        LI,0        'A'
        STB,0       pass,1
        LI,0        0xff
        LI,1        0
        STB,0       temp,1
        AI,1        1
        LI,0        0xfe
        STB,0       temp,1
        LI,0        0xe1234
        CW,0        temp
        BCR,3       end1
        LI,0        TEXTC("STB Failed.\n")
        BAL,15      puts
        WAIT,0      0

end1    LI,0        pass
        BAL,15      puts
        WAIT,0      0

puts    LI,2        0
        LB,3        *0,2
        AI,2        1
p0      LB,1        *0,2
        AI,2        1
        WD,1        0
        BDR,3       p0
        BCR,0       *15

temp    GEN,32      0
pass    TEXTC       " ll tests pass!\n"
