
        ORG         0x25

        LI,1        0x1ffff
        CW,1        cw_1
        BCR,3       ci_pass
        LI,0        test_fail_msg
        BAL,15      prnt
        WAIT,0      0

ci_pass    LI,0        msg0
        BAL,15      prnt

        GEN,1,7,4,20      0, 0x22, 1, '0'
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

        LI,8        0
        LW,9        pi_num
        DW,8        pi_den

        LI,10       113
        MI,10       31415
        CW,11       mi_1
        BCR,3       end1
        LI,0        test_fail_msg
        BAL,15      prnt
        WAIT,0      0

end1    LI,0        pass_msg
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
test_fail_msg    TEXTC    "Test Failure, check WAIT address\n"
pass_msg    TEXTC    "All tests pass!\n"
pi_num    GEN,32      355000000
pi_den    GEN,32      113
cw_1      GEN,32      0x1ffff
mi_1      GEN,32      113*31415
