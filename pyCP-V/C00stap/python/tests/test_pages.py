"""The page calls (MMNR.txt): M:GP, M:GCP, M:GVP, M:FP, M:FCP, M:FVP and M:GL, and the
memory limits FETCH sets (STPNR.txt LINKLIMS, OLAYLIM)."""

from tests.test_online import logged_on
from uts import fetch, jit
from uts.asm import assemble
from uts.fetch import write_load_module

PAGES = """
         ORG      X'D000'
START    CAL1,8   GP                M:GP 2: pages X'69', X'6A'
         STCF     R+0
         STW,8    R+1
         STW,9    R+2
         LI,1     5
         STW,1    *R+2              the first new page is there to use
         CAL1,8   GCP               M:GCP 1: page X'DF'
         STW,8    R+3
         STW,9    R+4
         CAL1,8   GL                M:GL
         STW,8    R+5
         STW,9    R+6
         CAL1,8   FP                M:FP 1: page X'6A' again
         STW,8    R+7
         CAL1,8   GVP               M:GVP X'D000': the program's own page
         STCF     R+8
         CAL1,8   FVP               M:FVP X'D200'
         STCF     R+9
         STW,8    R+10
         CAL1,8   FVP               again: no longer mapped
         STCF     R+11
         CAL1,9   1
GP       DATA     X'08000002'
GCP      DATA     X'0C000001'
GL       DATA     X'0B000000'
FP       DATA     X'09000001'
GVP      DATA     X'0400D000'
FVP      DATA     X'0500D200'
         ORG      X'D100'
R        RES      12
         END      START
"""


def test_the_limits_fetch_sets():
    t = logged_on()
    words, start = assemble(PAGES)
    write_load_module(t.s.cal.fs, "PROG", ":SYS", words, start)
    lm = fetch.read_load_module(t.s.cal.fs, "PROG", ":SYS")
    assert (lm.limits[jit.DLL], lm.limits[jit.DUL]) == (0x68, 0x68)    # X'D000'-X'D1FF'
    assert lm.limits[jit.PUL] < lm.limits[jit.PLL]                      # no procedure
    assert (lm.limits[jit.DDLL], lm.limits[jit.DDUL]) == (0x69, 0xDF)
    assert fetch.pages(lm) == {0x68}


def test_getting_and_freeing_pages():
    t = logged_on()
    words, start = assemble(PAGES)
    write_load_module(t.s.cal.fs, "PROG", ":SYS", words, start)
    t.type("PROG\r")
    assert t.text() == "PROG\r\n!"
    u = t.s.LB_UN[0]
    r = [t.s.umem[u].get(0xD100 + i, 0) & 0xFFFFFFFF for i in range(12)]
    assert r[0] >> 28 == 0 and (r[1], r[2]) == (2, 0xD200)             # M:GP
    assert (r[3], r[4]) == (1, 0x1BE00)                                 # M:GCP: X'DF'
    assert (r[5], r[6]) == (0x1BE00, 0x1BFFF)                           # M:GL: the common
    assert r[7] == 1                                                    # M:FP
    cc1 = lambda w: w >> 31                                             # SAD3: CC1 only
    assert cc1(r[8]) == 1                                               # M:GVP: mapped
    assert cc1(r[9]) == 0 and r[10] == 1                                # M:FVP
    assert cc1(r[11]) == 1                                              # M:FVP: free now
    cal = t.s.cal
    assert cal.jbyte(u, jit.TDP_BYTE) == 0x6A and cal.jbyte(u, jit.BCP_BYTE) == 0xDE
    assert cal.cmap[u] == {0x68, 0xDF}
    assert cal.jbyte(u, jit.PCP_BYTE + 2) == 1                          # JB:PCDD: X'DF'
