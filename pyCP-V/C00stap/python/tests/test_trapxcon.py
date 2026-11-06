"""M:TRAP (ALTCP.txt MTRAP), M:XCON (TRAPC.txt MXCON) and exit control at a program's
exit (STPNR.txt XCONSEE/XCONSETUP, SCHED.txt T:UTSXTS), run in assembled programs."""

from tests.test_online import logged_on
from uts import jit
from uts.asm import assemble
from uts.fetch import write_load_module


def run(source, name="PROG"):
    t = logged_on()
    words, start = assemble(source)
    write_load_module(t.s.cal.fs, name, ":SYS", words, start)
    t.type(name + "\r")
    return t, t.text(), t.s.LB_UN[0]


def mem(t, u, a):
    return t.s.umem[u].get(a, 0) & 0xFFFFFFFF


XCON = """
         ORG      X'D000'
START    CAL1,8   XCON              M:XCON EXIT
         STW,8    OLD               SR1: the old address
         CAL1,1   W1
         CAL1,9   1                 M:EXIT: to EXIT
EXIT     STW,8    RNST
         CAL1,1   W2
         CAL1,9   1                 M:EXIT again: in progress, so the end
XCON     DATA     X'19000000'+EXIT
W1       DATA     X'11008C2C',X'30000000',M1,4
W2       DATA     X'11008C2C',X'30000000',M2,4
M1       TEXT     'MAIN'
M2       TEXT     'EXIT'
OLD      DATA     -1
RNST     DATA     -1
         END      START
"""


def test_exit_control_on_m_exit_then_the_end():
    t, out, u = run(XCON)
    assert out == "PROG\r\nMAIN\r\nEXIT\r\n!"
    ext = mem(t, u, jit.J_JIT + jit.EXTENT)
    assert ext >> 24 == 0x20 and ext & 0x1FFFF == 0xD004      # in progress; the address
    words, _ = assemble(XCON)
    old = [a for a, w in words.items() if w == 0xFFFFFFFF][0]
    assert mem(t, u, old) == 0 and mem(t, u, old + 1) == 0     # SR1 0; R8: run status 0


XCON_LAST = """
         ORG      X'D000'
START    CAL1,8   XCON              M:XCON EXIT,LAST
         CAL1,8   XCON2             refused: CC1
         STCF     CC
         CAL1,9   1
EXIT     CAL1,9   1
XCON     DATA     X'19800000'+EXIT
XCON2    DATA     X'19000000'+START
CC       DATA     0
         END      START
"""


def test_after_last_another_m_xcon_is_refused():
    t, out, u = run(XCON_LAST)
    assert out == "PROG\r\n!"
    words, _ = assemble(XCON_LAST)
    cc = max(words)
    assert mem(t, u, cc) >> 28 == 8                             # CC1SET
    assert mem(t, u, jit.J_JIT + jit.EXTENT) & 0x1FFFF == 0xD004   # the first address stays


ABORTED = """
         ORG      X'D000'
START    STW,0    TCBP              R0: the TCB
         LD,2     STACKP
         STD,2    *TCBP             its stack pointer doubleword
         CAL1,8   XCON
         CAL1,8   BAD               code 0: BADCAL, abort X'AE'
EXIT     STW,0    SAVE
         STW,1    SAVE+1
         STW,8    SAVE+2
         STW,10   SAVE+3
         STW,12   SAVE+4
         CAL1,1   W2
         CAL1,9   1
XCON     DATA     X'19000000'+EXIT
BAD      DATA     0
W2       DATA     X'11008C2C',X'30000000',M2,4
M2       TEXT     'EXIT'
SAVE     RES      5
TCBP     DATA     0
         BOUND    8
STACKP   DATA     STACK-1,X'00400000'   empty, 64 words of space
STACK    RES      64
         END      START
"""


def test_exit_control_after_an_abort_with_the_environment_on_the_stack():
    t, out, u = run(ABORTED)
    assert out == "PROG\r\nEXIT\r\n!"
    words, _ = assemble(ABORTED)
    save = [a for a in sorted(words) if words[a] == 0x11008C2C][0] + 5   # after W2, M2
    tcb, psd_at, rnst, abc, r12 = (mem(t, u, save + i) for i in range(5))
    assert tcb == mem(t, u, jit.J_JIT + jit.TCB) and tcb
    assert (rnst, abc, r12) == (0x01, 0xAE, 0)                  # T:ABORTM; good stack
    assert mem(t, u, psd_at) & 0x1FFFF == 0xD005                # the PSD: after the bad CAL
    assert mem(t, u, psd_at + 1) == 0x10000000
    assert mem(t, u, psd_at + 2) == tcb                         # R0 as it was
    spd = mem(t, u, tcb), mem(t, u, tcb + 1)
    assert spd[0] == psd_at + 18 and spd[1] & 0x7FFF in (20, 21)


TRAPS = """
         ORG      X'D000'
START    CAL1,8   PERMIT            M:TRAP PERMIT FX: AM on
         STW,8    SR1
         STW,9    SR2
         CAL1,8   IGNORE            M:TRAP IGNORE FX: AM off
         LW,1     BIG
         AW,1     BIG               overflow, no trap
         CAL1,8   RESTORE           back to after PERMIT's SR1/SR2: AM off still
         CAL1,8   PERMIT
         LW,1     BIG
         AW,1     BIG               overflow with AM: trap X'43'
         CAL1,9   1
PERMIT   DATA     X'14000000'+HANDLER,X'00000100'
IGNORE   DATA     X'14000000'+HANDLER,X'00000001'
RESTORE  DATA     X'14000000'+SR1,X'80000000'
HANDLER  CAL1,9   1
BIG      DATA     X'7FFFFFFF'
SR1      DATA     -1
SR2      DATA     -1
         END      START
"""


def test_m_trap_sets_the_arithmetic_mask_and_returns_the_old_conditions():
    t, out, u = run(TRAPS)
    assert "TRAP X'43'" in out and "FIXED-POINT OVERFLOW" in out
    words, _ = assemble(TRAPS)
    sr1 = [a for a, w in words.items() if w == 0xFFFFFFFF][0]
    assert mem(t, u, sr1) == 0x000000C0                         # no flags; the PSD: slave, mapped
    assert mem(t, u, sr1 + 1) == 0                              # no entry before
    assert mem(t, u, jit.J_JIT + jit.USENT) & 0x1FFFF == 0xD011  # HANDLER


TRAP_TO_ENTRY = """
         ORG      X'D000'
START    CAL1,8   TRAP              M:TRAP: TRAP FX and CAL, PERMIT FX
         LW,1     BIG
         AW,1     BIG
         CAL1,9   1
TRAP     DATA     X'14000000'+HANDLER,X'00018100'
HANDLER  CAL1,9   1
BIG      DATA     X'7FFFFFFF'
         END      START
"""


def test_a_trap_the_program_asked_for_is_not_translated():
    t, out, u = run(TRAP_TO_ENTRY)
    flags = (mem(t, u, jit.J_JIT + jit.USENT) >> 17) & 0xFF
    assert flags == 0x81                                        # CAL and FX
    assert "NOT TRANSLATED: trap X'43'" in out
