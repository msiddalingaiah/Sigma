
        ORG         0x25

        LI,0        TEXTC("Call me Ishmael...\n")
        BAL,15      prnt

        LI,1        0x1ffff
        CW,1        GEN32(0x1ffff)
        BCR,3       ci_pass
        LI,0        TEXTC("CW failed.\n")
        BAL,15      prnt
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

        LI,10       113
        MI,10       31415
        CW,11       GEN32(113*31415)
        BCR,3       test_mw
        LI,0        TEXTC("MI Failed.\n")
        BAL,15      prnt
        WAIT,0      0

test_mw    LI,10       113
        MW,10       GEN32(31415)
        CW,11       GEN32(113*31415)
        BCR,3       end1
        LI,0        TEXTC("MI Failed.\n")
        BAL,15      prnt
        WAIT,0      0

end1    LI,0        TEXTC("All tests pass!\n")
        BAL,15      prnt
        WAIT,0      0

prnt    LI,2        0
        LB,3        *0,2
        AI,2        1
p0      LB,1        *0,2
        AI,2        1
        WD,1        0
        BDR,3       p0
        BCR,0       *15
