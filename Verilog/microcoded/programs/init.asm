
        ORG         0x25

        LI,1        0x1fffff
        LI,2        0
        LI,3        1
        LI,1        'H'
        WD,1        0
        LI,1        'e'
        WD,1        0
        LI,1        'l'
        WD,1        0
        LI,1        'l'
        WD,1        0
        LI,1        'o'
        WD,1        0
        LI,1        '!'
        WD,1        0
        LI,1        '\n'
        WD,1        0

        LI,1        '0'
        LI,3        9
lp1     AI,1        1
        WD,1        0
        BDR,3       lp1

        LI,1        '\n'
        WD,1        0

        LI,2        0
        LB,3        msg1,2
        AI,2        1
lp2     LB,1        msg1,2
        AI,2        1
        WD,1        0
        BDR,3       lp2

        LI,0        msg2
        LI,2        0
        LB,3        *0,2
        AI,2        1
lp3     LB,1        *0,2
        AI,2        1
        WD,1        0
        BDR,3       lp3

        WAIT,0      0

msg1    TEXTC       "Call me Ishmael...\n"
msg2    TEXTC       "Bye!\n"
