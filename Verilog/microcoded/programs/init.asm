
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
loop    AI,1        1
        WD,1        0
        BDR,3       loop

        LI,1        '\n'
        WD,1        0

        WAIT,0      0

msg1    TEXTC       "Call me Ishmael..."
msg2    TEXTC       "Bye"
