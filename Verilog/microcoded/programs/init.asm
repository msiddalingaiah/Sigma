
        ORG         0x25

        LI,1        0x1fffff
        LI,2        0
        LI,3        1

        LI,0        msg0
        BAL,15      prnt

        LI,1        '0'
        LI,3        9
lp1     AI,1        1
        WD,1        0
        BDR,3       lp1
        LI,1        '\n'
        WD,1        0

        LI,0        msg1
        BAL,15      prnt

        LI,0        msg2
        BAL,15      prnt

        LI,0        msg3
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

msg0    TEXTC       "Hello!\n"
msg1    TEXTC       "Call me Ishmael...\n"
msg2    TEXTC       "OK...\n"
msg3    TEXTC       "Bye!\n"
