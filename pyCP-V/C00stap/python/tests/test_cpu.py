"""The user-mode CPU (uts/cpu.py) against simh's rules (sigma_cpu.c), instruction by
instruction, through the small assembler."""

import pytest

from uts.asm import assemble
from uts.cpu import CC1, CC2, CC3, CC4, OP, Cpu

ORG = 0xD000


def run(src, regs=None, cc=0, model="sigma9", steps=1000, am=False):
    """Assemble at X'D000' and run until a trap; returns (cpu, trap)."""
    words, start = assemble("         ORG      X'D000'\n" + src)
    r = [0] * 16
    for k, v in (regs or {}).items():
        r[k] = v & 0xFFFFFFFF
    mem = dict(words)
    cpu = Cpu(r, mem, pc=start if start is not None else ORG, cc=cc, model=model)
    cpu.AM = am
    _, trap = cpu.run(steps)
    return cpu, trap


END = "         CAL1,9   1\n"


# --- loads, stores and the CC -------------------------------------------------------------

def test_li_sign_extends_and_sets_cc34():
    cpu, t = run("         LI,1     -5\n" + END)
    assert cpu.R[1] == 0xFFFFFFFB and cpu.CC == CC4 and t.vector == 0x48
    cpu, _ = run("         LI,1     0\n" + END)
    assert cpu.CC == 0
    cpu, _ = run("         LI,1     7\n" + END)
    assert cpu.CC == CC3


def test_byte_half_and_doubleword_addressing_scale_the_index():
    src = """         LB,2     DATA,1
         LH,3     DATA,1
         LW,4     DATA,1
         LD,6     DATA,1
""" + END + """         BOUND    8
DATA     DATA     X'11223344',X'55667788',X'99AABBCC',X'DDEEFF00'
"""
    cpu, _ = run(src, regs={1: 1})
    assert cpu.R[2] == 0x22                            # byte 1
    assert cpu.R[3] == 0x3344                          # halfword 1
    assert cpu.R[4] == 0x55667788                      # word 1
    assert (cpu.R[6], cpu.R[7]) == (0x99AABBCC, 0xDDEEFF00)   # doubleword 1


def test_indirect_then_index():
    src = """         LW,2     *PTR,1
""" + END + """PTR      DATA     TAB
TAB      DATA     10,20,30
"""
    cpu, _ = run(src, regs={1: 2})
    assert cpu.R[2] == 30


def test_registers_are_memory_words_0_to_15():
    cpu, _ = run("         LW,2     5\n         STW,2    8\n" + END, regs={5: 1234})
    assert cpu.R[2] == 1234 and cpu.R[8] == 1234


def test_int_settles_the_odd_register_case():
    src = "         INT,11   W\n" + END + "W        DATA     X'5ABC1234'\n"
    cpu, _ = run(src)
    assert cpu.CC == 5 and cpu.R[11] == 0x1234        # odd R: bits 16-31 win (:876-:877)
    cpu, _ = run(src.replace("INT,11", "INT,10"))
    assert (cpu.R[10], cpu.R[11]) == (0xABC, 0x1234)


def test_lm_and_stm_take_the_count_from_the_cc():
    src = """         LM,4     TAB
         STM,4    COPY
""" + END + """TAB      DATA     1,2,3
COPY     RES      3
"""
    cpu, _ = run(src, cc=3)
    assert cpu.R[4:7] == [1, 2, 3]
    words = assemble("         ORG      X'D000'\n" + src)[0]
    copy = max(words) - 2
    assert [cpu.M[copy + i] for i in range(3)] == [1, 2, 3]


def test_sth_sets_cc2_when_the_register_is_not_a_halfword():
    cpu, _ = run("         STH,1    X\n" + END + "X        DATA     0\n", regs={1: 0x12345})
    assert cpu.CC & CC2
    cpu, _ = run("         STH,1    X\n" + END + "X        DATA     0\n", regs={1: -3})
    assert not cpu.CC & CC2


# --- arithmetic --------------------------------------------------------------------------

def test_add_sets_carry_and_overflow():
    cpu, _ = run("         AW,1     X\n" + END + "X        DATA     1\n", regs={1: 0x7FFFFFFF})
    assert cpu.R[1] == 0x80000000 and cpu.CC & CC2 and cpu.CC & CC4 and not cpu.CC & CC1
    cpu, _ = run("         AW,1     X\n" + END + "X        DATA     1\n", regs={1: -1})
    assert cpu.R[1] == 0 and cpu.CC == CC1


def test_overflow_traps_only_with_am():
    src = "         AI,1     1\n" + END
    cpu, t = run(src, regs={1: 0x7FFFFFFF}, am=True)
    assert t.vector == 0x43 and t.pc == ORG and cpu.R[1] == 0x80000000
    cpu, t = run(src, regs={1: 0x7FFFFFFF})
    assert t.vector == 0x48


def test_multiply_and_divide_use_the_register_pair():
    cpu, _ = run("         MW,2     X\n" + END + "X        DATA     -7\n", regs={3: 6})
    assert (cpu.R[2], cpu.R[3]) == (0xFFFFFFFF, 0xFFFFFFD6)   # -42 in 64 bits
    cpu, _ = run("         DW,2     X\n" + END + "X        DATA     7\n", regs={2: 0, 3: 45})
    assert (cpu.R[2], cpu.R[3]) == (3, 6)              # remainder, quotient
    cpu, _ = run("         DW,2     X\n" + END + "X        DATA     0\n", regs={3: 45})
    assert cpu.CC & CC2                                # divide check


def test_dh_truncates_toward_zero():
    cpu, _ = run("         DH,1     X\n" + END + "X        DATA     X'00030000'\n", regs={1: -7})
    assert cpu.R[1] == 0xFFFFFFFE                      # -7 / 3 = -2


def test_mtw_modifies_and_tests_memory():
    src = "         MTW,-1   X\n" + END + "X        DATA     1\n"
    cpu, _ = run(src)
    assert cpu.M[max(cpu.M)] == 0 and cpu.CC & CC1     # 1 + (-1): carry, zero


# --- compare, logic, shift, convert -----------------------------------------------------------

def test_clm_cc_layout():
    src = "         CLM,1    LIM\n" + END + "         BOUND    8\nLIM      DATA     5,9\n"
    cpu, _ = run(src, regs={1: 5})
    assert cpu.CC & (CC3 | CC4) == 0                   # equal to the first word
    assert cpu.CC & (CC1 | CC2) == CC4 << 2           # less than the second word
    cpu, _ = run(src, regs={1: 9})
    assert cpu.CC & (CC1 | CC2) == 0                   # equal to the second word


@pytest.mark.parametrize("op, count, before, after", [
    ("SLS", 4, 0x0000000F, 0x000000F0),
    ("SLS", -4, 0x000000F0, 0x0000000F),
    ("SAS", -4, 0x80000000, 0xF8000000),
    ("SCS", 8, 0x12345678, 0x34567812),
    ("SCS", -8, 0x12345678, 0x78123456),
])
def test_single_shifts(op, count, before, after):
    cpu, _ = run(f"         {op},1    {count}\n".replace("-", "0-") + END
                 if count < 0 else f"         {op},1    {count}\n" + END, regs={1: before})
    assert cpu.R[1] == after


def test_double_shift_and_left_shift_cc():
    cpu, _ = run("         SLD,2    4\n" + END, regs={2: 0x0000000F, 3: 0xF0000000})
    assert (cpu.R[2], cpu.R[3]) == (0x000000FF, 0x00000000)
    cpu, _ = run("         SLS,2    1\n" + END, regs={2: 0x40000000})
    assert cpu.CC & CC2                                # the sign changed


def test_cva_and_cvs():
    table = "TAB      DATA     " + ",".join(str(1 << (31 - i)) for i in range(32)) + "\n"
    cpu, _ = run("         CVA,2    TAB\n" + END + table, regs={3: 0b1011})
    assert cpu.R[2] == 0b1011
    cpu, _ = run("         CVS,2    TAB\n" + END + table, regs={2: 13})
    assert (cpu.R[2], cpu.R[3]) == (0, 13)


# --- control ------------------------------------------------------------------------------

def test_branches():
    src = """         LI,1     3
LOOP     AI,2     1
         BDR,1    LOOP
         BAL,15   SUB
""" + END + """SUB      LI,4     9
         B        *15
"""
    src = src.replace("         B        *15", "         BCR,0    *15")
    cpu, t = run(src.replace(END, "         CAL1,9   1\n"))
    assert cpu.R[2] == 3 and cpu.R[4] == 9 and t.pc == ORG + 4


def test_exu_executes_the_word():
    cpu, _ = run("         EXU      I\n" + END + "I        LI,3     42\n")
    assert cpu.R[3] == 42


def test_bcs_uses_r_as_a_mask():
    src = """         LI,1     0
         BCS,3    NO
         LI,2     1
""" + END + "NO       LI,2     2\n" + END
    cpu, _ = run(src)
    assert cpu.R[2] == 1                               # CC 0: no branch
    cpu, _ = run(src.replace("LI,1     0", "LI,1     5"))
    assert cpu.R[2] == 2                               # CC3 set: branch


# --- the stack ----------------------------------------------------------------------------

def test_push_and_pull():
    src = """         PSW,5    SP
         LCFI,2   X'20'
         PSM,6    SP
         PLW,9    SP
""" + END + """         BOUND    8
SP       DATA     STK-1,X'00100000'
STK      RES      16
"""
    cpu, _ = run(src, regs={5: 111, 6: 222, 7: 333}, cc=2)
    assert cpu.R[9] == 333                             # the last pushed (PSM 2 words)


def test_stack_overflow_traps():
    src = "         PSW,5    SP\n" + END + "         BOUND    8\nSP       DATA     STK,0\nSTK      RES      1\n"
    cpu, t = run(src)
    assert t.vector == 0x42                            # no space, trap enabled


# --- byte strings -------------------------------------------------------------------------

def test_mbs_and_cbs():
    src = """         LI,2     BA(SRC)
         LW,3     CNT
         MBS,2    0
         LI,2     BA(SRC)
         LW,3     CNT
         CBS,2    0
""" + END + """CNT      DATA     X'05000000'+BA(DST)
SRC      TEXT     'HELLO   '
DST      RES      2
"""
    cpu, _ = run(src)
    words = assemble("         ORG      X'D000'\n" + src)[0]
    dst = max(words) - 1
    assert cpu.M[dst].to_bytes(4, "big") + bytes([cpu.M[dst + 1] >> 24]) == "HELLO".encode("cp037")
    assert cpu.CC & (CC3 | CC4) == 0                   # equal after the move


# --- traps --------------------------------------------------------------------------------

def test_privileged_unimplemented_and_undefined():
    cpu, t = run("         WD,0     0\n" + END)
    assert (t.vector, t.cc) == (0x40, CC3)
    cpu, t = run("         FAS,0    0\n" + END)
    assert t.vector == 0x41
    words = {ORG: 0x01000000}                          # opcode X'01'
    t = Cpu([0] * 16, words, pc=ORG).step()
    assert (t.vector, t.cc) == (0x40, CC1)


def test_odd_register_doubleword_is_invalid_on_sigma9_only():
    src = "         AD,3     X\n" + END + "         BOUND    8\nX        DATA     0,1\n"
    _, t = run(src)
    assert t.vector == 0x4D
    _, t = run(src, model="sigma7")
    assert t.vector == 0x48


def test_cal_reports_its_number_and_address():
    _, t = run("         LI,1     0\n         CAL1,2   0\n")
    assert t.vector == 0x48 and t.cc == 2 and t.pc == ORG + 1
    _, t = run("         CAL3,0   0\n")
    assert t.vector == 0x4A


def test_anlz():
    src = "         ANLZ,2   I\n" + END + "I        LW,1     X'D100',3\n"
    cpu, _ = run(src, regs={3: 2})
    assert cpu.R[2] == 0xD102 and cpu.CC & CC4 == 0    # a word memory reference


def test_opcode_numbers_follow_the_table():
    assert OP["LW"] == 0x32 and OP["CAL1"] == 0x04 and OP["BAL"] == 0x6A and OP["INT"] == 0x6B
