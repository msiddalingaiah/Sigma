"""
SDS/Xerox Sigma 7 CPU Testbench
Cocotb-based testbench using Python runner with Icarus Verilog
"""

import os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from cocotb_tools.runner import get_runner


# ---------------------------------------------------------------------------
# Opcodes
# ---------------------------------------------------------------------------
OP_LCFI = 0x02
OP_LW   = 0x32
OP_STW  = 0x35
OP_AW   = 0x30
OP_SW   = 0x38
OP_CW   = 0x31
OP_AI   = 0x20
OP_CI   = 0x21
OP_LI   = 0x22
OP_AND  = 0x4B
OP_OR   = 0x49
OP_EOR  = 0x48
OP_LH   = 0x52
OP_STH  = 0x55
OP_LB   = 0x72
OP_STB  = 0x75
OP_BCR  = 0x68
OP_BCS  = 0x69
OP_BAL  = 0x6A
OP_PLW  = 0x08
OP_PSW  = 0x09
OP_RD   = 0x6C
OP_WD   = 0x6D


# ---------------------------------------------------------------------------
# Instruction encoding helpers
# ---------------------------------------------------------------------------
def encode(op, r=0, x=0, addr=0, i=0):
    return ((i  & 0x1)  << 31) | \
           ((op & 0x7F) << 24) | \
           ((r  & 0x0F) << 20) | \
           ((x  & 0x07) << 17) | \
           (addr & 0x1FFFF)

def encode_imm(op, r=0, imm=0):
    imm20 = imm & 0xFFFFF
    return ((op & 0x7F) << 24) | \
           ((r  & 0x0F) << 20) | \
           imm20

def word_addr(byte_addr):
    return (byte_addr >> 2) & 0x1FFFF


# ---------------------------------------------------------------------------
# CC bit helpers
# CC is 4-bit [1:4]: CC1=MSB=bit3, CC2=bit2, CC3=bit1, CC4=LSB=bit0
# ---------------------------------------------------------------------------
def cc_carry(cc):    return bool(int(cc) & 0x8)
def cc_overflow(cc): return bool(int(cc) & 0x4)
def cc_pos(cc):      return bool(int(cc) & 0x2)
def cc_neg(cc):      return bool(int(cc) & 0x1)
def cc_zero(cc):     return not cc_pos(cc) and not cc_neg(cc)


# ---------------------------------------------------------------------------
# Array access helpers
# ---------------------------------------------------------------------------
def mem(dut, addr):
    """Access a memory byte cell."""
    return dut.sys.memory.mem[addr]

def rr(dut, idx):
    """Access a user register."""
    return dut.sys.cpu.RR[idx]


# ---------------------------------------------------------------------------
# Memory helpers
# ---------------------------------------------------------------------------
async def write_word(dut, byte_addr, value):
    value = value & 0xFFFFFFFF
    mem(dut, byte_addr    ).value = (value >> 24) & 0xFF
    mem(dut, byte_addr + 1).value = (value >> 16) & 0xFF
    mem(dut, byte_addr + 2).value = (value >>  8) & 0xFF
    mem(dut, byte_addr + 3).value =  value        & 0xFF

async def read_word(dut, byte_addr):
    b0 = int(mem(dut, byte_addr    ).value)
    b1 = int(mem(dut, byte_addr + 1).value)
    b2 = int(mem(dut, byte_addr + 2).value)
    b3 = int(mem(dut, byte_addr + 3).value)
    return (b0 << 24) | (b1 << 16) | (b2 << 8) | b3

async def write_halfword(dut, byte_addr, value):
    value = value & 0xFFFF
    mem(dut, byte_addr    ).value = (value >> 8) & 0xFF
    mem(dut, byte_addr + 1).value =  value       & 0xFF

async def write_byte(dut, byte_addr, value):
    mem(dut, byte_addr).value = value & 0xFF

async def read_byte(dut, byte_addr):
    return int(mem(dut, byte_addr).value)

async def load_program(dut, byte_addr, words):
    for i, w in enumerate(words):
        await write_word(dut, byte_addr + i * 4, w)

async def load_hex(dut, hexfile):
    """Load a $readmemh hex file into memory."""
    addr = 0
    with open(hexfile) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('//'):
                continue
            if line.startswith('@'):
                addr = int(line[1:], 16)
            else:
                word = int(line, 16)
                await write_word(dut, addr * 4, word)  # addr is word addr
                addr += 1


# ---------------------------------------------------------------------------
# Clock and reset helpers
# ---------------------------------------------------------------------------
async def init_memory(dut, size=0x500):
    """Initialize memory to zero to avoid X values."""
    for addr in range(0, size, 4):
        await write_word(dut, addr, 0x00000000)

async def reset_cpu(dut):
    """Reset CPU for 2 cycles then release."""
    dut.sys.rx_ready.value = 0
    dut.sys.rx_data.value  = 0
    dut.reset.value = 1
    for _ in range(2):
        await RisingEdge(dut.clock)
    dut.reset.value = 0


async def run_cycles(dut, n):
    for _ in range(n):
        await RisingEdge(dut.clock)


# ---------------------------------------------------------------------------
# Test result tracking
# ---------------------------------------------------------------------------
class TestResults:
    def __init__(self, name):
        self.name   = name
        self.passed = 0
        self.failed = 0
        cocotb.log.info(f"\n=== {name} ===")

    def check(self, label, got, expected):
        expected = int(expected) & 0xFFFFFFFF
        try:
            got = int(got) & 0xFFFFFFFF
        except ValueError:
            self.failed += 1
            cocotb.log.error(f"  FAIL  {label}: got X (unknown/uninitialized), expected 0x{expected:08X}")
            return
        if got == expected:
            self.passed += 1
            cocotb.log.info(f"  PASS  {label}: 0x{got:08X}")
        else:
            self.failed += 1
            cocotb.log.error(f"  FAIL  {label}: got 0x{got:08X}, expected 0x{expected:08X}")

    def check_bool(self, label, got, expected):
        if bool(got) == bool(expected):
            self.passed += 1
            cocotb.log.info(f"  PASS  {label}: {bool(got)}")
        else:
            self.failed += 1
            cocotb.log.error(f"  FAIL  {label}: got {bool(got)}, expected {bool(expected)}")

    def summary(self):
        total = self.passed + self.failed
        cocotb.log.info(f"  --- {self.name}: {self.passed}/{total} passed ---")
        if self.failed > 0:
            raise AssertionError(f"{self.name}: {self.failed} test(s) failed")


# ---------------------------------------------------------------------------
# Test: Boot sequence
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_boot_sequence(dut):
    """Cycle-by-cycle debug trace of boot sequence."""
    cocotb.log.info("\n=== Boot Sequence Debug ===")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    # Initialize memory and reset
    await init_memory(dut)
    await write_word(dut, 0x098, encode(OP_LW, r=1, addr=word_addr(0x400)))
    await write_word(dut, 0x09C, encode(OP_LCFI, r=0))
    await write_word(dut, 0x400, 0xDEADBEEF)
    cocotb.log.info(f"  M[0x098] = 0x{encode(OP_LW, r=1, addr=word_addr(0x400)):08X} (LW R1,[0x400])")
    cocotb.log.info(f"  M[0x09C] = 0x{encode(OP_LCFI, r=0):08X} (LCFI halt)")
    cocotb.log.info(f"  M[0x400] = 0xDEADBEEF")

    await reset_cpu(dut)

    # Trace 30 cycles
    for i in range(30):
        await RisingEdge(dut.clock)
        try:
            phase = str(dut.sys.cpu.phase_name.value)
            O     = int(dut.sys.cpu.O.value)
            P     = int(dut.sys.cpu.P.value)
            Q     = int(dut.sys.cpu.Q.value)
            ende  = int(dut.sys.cpu.ende.value)
            D     = int(dut.sys.cpu.D.value)
            addr  = int(dut.sys.bus_addr.value)
            cocotb.log.info(
                f"  cy{i:02d}: ph={phase} O=0x{O:02X} "
                f"P=0x{P:05X} Q=0x{Q:05X} "
                f"addr=0x{addr:05X} D=0x{D:08X} ende={ende}"
            )
        except Exception as e:
            cocotb.log.warning(f"  cy{i:02d}: {e}")

    # Check result
    try:
        r1 = int(rr(dut, 1).value)
        cocotb.log.info(f"  RR[1] = 0x{r1:08X} (expected 0xDEADBEEF)")
        if r1 == 0xDEADBEEF:
            cocotb.log.info("  PASS")
        else:
            cocotb.log.error("  FAIL")
    except Exception as e:
        cocotb.log.warning(f"  RR[1] read error: {e}")


# ---------------------------------------------------------------------------
# Test: LI — Load Immediate
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_li(dut):
    """Test LI — load immediate."""
    tr = TestResults("LI - Load Immediate")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await init_memory(dut)
    # LI R1, 42        → RR[1] = 42
    # LI R2, -1        → RR[2] = 0xFFFFFFFF
    # LI R3, 0x7FFFF   → RR[3] = 0x0007FFFF (max positive 20-bit)
    # LCFI             → halt
    await write_word(dut, 0x098, encode_imm(OP_LI, r=1, imm=42))
    await write_word(dut, 0x09C, encode_imm(OP_LI, r=2, imm=-1))
    await write_word(dut, 0x0A0, encode_imm(OP_LI, r=3, imm=0x7FFFF))
    await write_word(dut, 0x0A4, encode(OP_LCFI, r=0))

    await reset_cpu(dut)
    await run_cycles(dut, 40)

    tr.check("LI R1=42",         rr(dut, 1).value, 42)
    tr.check("LI R2=-1",         rr(dut, 2).value, 0xFFFFFFFF)
    tr.check("LI R3=0x7FFFF",    rr(dut, 3).value, 0x0007FFFF)
    tr.summary()


# ---------------------------------------------------------------------------
# Test: LW — Load Word
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_lw(dut):
    """Test LW with direct addressing."""
    tr = TestResults("LW - Load Word")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await init_memory(dut)
    await write_word(dut, 0x098, encode(OP_LW,   r=1, addr=word_addr(0x400)))
    await write_word(dut, 0x09C, encode(OP_LW,   r=2, addr=word_addr(0x404)))
    await write_word(dut, 0x0A0, encode(OP_LW,   r=3, addr=word_addr(0x408)))
    await write_word(dut, 0x0A4, encode(OP_LCFI, r=0))
    await write_word(dut, 0x400, 0x12345678)
    await write_word(dut, 0x404, 0xABCDEF01)
    await write_word(dut, 0x408, 0x00000000)

    await reset_cpu(dut)
    await run_cycles(dut, 60)

    tr.check("LW R1", rr(dut, 1).value, 0x12345678)
    tr.check("LW R2", rr(dut, 2).value, 0xABCDEF01)
    tr.check("LW R3", rr(dut, 3).value, 0x00000000)
    tr.summary()


# ---------------------------------------------------------------------------
# Test: STW — Store Word
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_stw(dut):
    """Test STW — store word."""
    tr = TestResults("STW - Store Word")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await init_memory(dut)
    await write_word(dut, 0x098, encode(OP_LW,   r=1, addr=word_addr(0x400)))
    await write_word(dut, 0x09C, encode(OP_STW,  r=1, addr=word_addr(0x404)))
    await write_word(dut, 0x0A0, encode(OP_LCFI, r=0))
    await write_word(dut, 0x400, 0xDEADBEEF)

    await reset_cpu(dut)
    await run_cycles(dut, 60)

    result = await read_word(dut, 0x404)
    tr.check("STW M[0x404]=0xDEADBEEF", result, 0xDEADBEEF)
    tr.summary()


# ---------------------------------------------------------------------------
# Test: AW, SW — Word Arithmetic
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_word_arithmetic(dut):
    """Test AW, SW, CW, AND, OR, EOR."""
    tr = TestResults("Word Arithmetic")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await init_memory(dut)
    # LI R1, 10       → R1 = 10
    # AW R1, [0x400]  → R1 = 10 + 5 = 15
    # LI R2, 20       → R2 = 20
    # SW R2, [0x404]  → R2 = 20 - 7 = 13
    # LI R3, 0xFF     → R3 = 0xFF
    # AND R3, [0x408] → R3 = 0xFF & 0x0F = 0x0F
    # LI R4, 0xF0     → R4 = 0xF0
    # OR  R4, [0x40C] → R4 = 0xF0 | 0x0F = 0xFF
    # LI R5, 0xFF     → R5 = 0xFF
    # EOR R5, [0x410] → R5 = 0xFF ^ 0xFF = 0
    # LCFI            → halt
    await write_word(dut, 0x098, encode_imm(OP_LI,  r=1, imm=10))
    await write_word(dut, 0x09C, encode(OP_AW,  r=1, addr=word_addr(0x400)))
    await write_word(dut, 0x0A0, encode_imm(OP_LI,  r=2, imm=20))
    await write_word(dut, 0x0A4, encode(OP_SW,  r=2, addr=word_addr(0x404)))
    await write_word(dut, 0x0A8, encode_imm(OP_LI,  r=3, imm=0xFF))
    await write_word(dut, 0x0AC, encode(OP_AND, r=3, addr=word_addr(0x408)))
    await write_word(dut, 0x0B0, encode_imm(OP_LI,  r=4, imm=0xF0))
    await write_word(dut, 0x0B4, encode(OP_OR,  r=4, addr=word_addr(0x40C)))
    await write_word(dut, 0x0B8, encode_imm(OP_LI,  r=5, imm=0xFF))
    await write_word(dut, 0x0BC, encode(OP_EOR, r=5, addr=word_addr(0x410)))
    await write_word(dut, 0x0C0, encode(OP_LCFI, r=0))
    await write_word(dut, 0x400, 5)
    await write_word(dut, 0x404, 7)
    await write_word(dut, 0x408, 0x0F)
    await write_word(dut, 0x40C, 0x0F)
    await write_word(dut, 0x410, 0xFF)

    await reset_cpu(dut)
    await run_cycles(dut, 150)

    tr.check("AW  R1=15",   rr(dut, 1).value, 15)
    tr.check("SW  R2=13",   rr(dut, 2).value, 13)
    tr.check("AND R3=0x0F", rr(dut, 3).value, 0x0F)
    tr.check("OR  R4=0xFF", rr(dut, 4).value, 0xFF)
    tr.check("EOR R5=0",    rr(dut, 5).value, 0x00)
    # After EOR: result=0, CC3=0 (not positive), CC4=0 (not negative)
    tr.check_bool("EOR CC3=0", cc_pos(dut.sys.cpu.CC.value), False)
    tr.check_bool("EOR CC4=0", cc_neg(dut.sys.cpu.CC.value), False)
    tr.summary()


# ---------------------------------------------------------------------------
# Test: CW — Compare Word
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_cw(dut):
    """Test CW — compare word, checks CC bits."""
    tr = TestResults("CW - Compare Word")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await init_memory(dut)
    # LI R1, 10       → R1 = 10
    # CW R1, [0x400]  → compare 10 vs 10 → equal (CC3=0, CC4=0)
    # CW R1, [0x404]  → compare 10 vs 5  → R1>mem → CC3=1
    # CW R1, [0x408]  → compare 10 vs 20 → R1<mem → CC4=1
    # LCFI            → halt
    await write_word(dut, 0x098, encode_imm(OP_LI,  r=1, imm=10))
    await write_word(dut, 0x09C, encode(OP_CW, r=1, addr=word_addr(0x400)))
    await write_word(dut, 0x0A0, encode(OP_CW, r=1, addr=word_addr(0x404)))
    await write_word(dut, 0x0A4, encode(OP_CW, r=1, addr=word_addr(0x408)))
    await write_word(dut, 0x0A8, encode(OP_LCFI, r=0))
    await write_word(dut, 0x400, 10)   # equal
    await write_word(dut, 0x404, 5)    # R1 > mem
    await write_word(dut, 0x408, 20)   # R1 < mem

    await reset_cpu(dut)
    await run_cycles(dut, 80)

    # After last CW (10 vs 20): CC3=0, CC4=1
    tr.check_bool("CW R1<mem CC4=1", cc_neg(dut.sys.cpu.CC.value), True)
    tr.check_bool("CW R1<mem CC3=0", cc_pos(dut.sys.cpu.CC.value), False)
    tr.summary()


# ---------------------------------------------------------------------------
# Test: Indexed addressing (X field)
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_indexed(dut):
    """Test LW and STW with indexed addressing."""
    tr = TestResults("Indexed Addressing")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await init_memory(dut)
    base = word_addr(0x400)   # word address of 0x400 = 0x100

    # LI R5, base      → R5 = 0x100
    # LW R1, 0(R5)     → EA = R5+0 = 0x100 → M[0x400] = 0x11111111
    # LW R2, 1(R5)     → EA = R5+1 = 0x101 → M[0x404] = 0x22222222
    # LI R6, 2         → R6 = 2
    # LW R3, base(R6)  → EA = R6+base = 2+0x100=0x102 → M[0x408] = 0x33333333
    # STW R1, 2(R5)    → EA = R5+2 = 0x102 → M[0x408] = R1 = 0x11111111
    # LCFI             → halt
    await write_word(dut, 0x098, encode_imm(OP_LI,  r=5, imm=base))
    await write_word(dut, 0x09C, encode(OP_LW,  r=1, x=5, addr=0))
    await write_word(dut, 0x0A0, encode(OP_LW,  r=2, x=5, addr=1))
    await write_word(dut, 0x0A4, encode_imm(OP_LI,  r=6, imm=2))
    await write_word(dut, 0x0A8, encode(OP_LW,  r=3, x=6, addr=base))
    await write_word(dut, 0x0AC, encode(OP_STW, r=1, x=5, addr=2))
    await write_word(dut, 0x0B0, encode(OP_LCFI, r=0))
    await write_word(dut, 0x400, 0x11111111)
    await write_word(dut, 0x404, 0x22222222)
    await write_word(dut, 0x408, 0x33333333)

    await reset_cpu(dut)
    await run_cycles(dut, 120)

    tr.check("LW R1 indexed base+0",   rr(dut, 1).value, 0x11111111)
    tr.check("LW R2 indexed base+1",   rr(dut, 2).value, 0x22222222)
    tr.check("LW R3 indexed R6+base",  rr(dut, 3).value, 0x33333333)
    result = await read_word(dut, 0x408)
    tr.check("STW R1 indexed base+2",  result,            0x11111111)
    tr.summary()



# ---------------------------------------------------------------------------
# Test: LH, STH — Halfword load/store with indexing
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_halfword(dut):
    """Test LH and STH — sign extension, halfword select via index low bit."""
    tr = TestResults("Halfword Load/Store")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await init_memory(dut)
    # Word at 0x400: high HW = 0x8000 (negative), low HW = 0x0005 (positive)
    # LH R1, word_addr(0x400)      → P[32:33]=00 → high HW = 0x8000
    #                                R1 = sign_ext(0x8000) = 0xFFFF8000, CC4=1
    # LI R6, 1                     → R6 = 1 (odd → idx_boff={1,0} → P[32:33]=10)
    # LH R2, word_addr(0x400)(R6)  → EA word=0x100, P[32:33]=10 → low HW = 0x0005
    #                                R2 = sign_ext(0x0005) = 0x00000005
    # STH R2, word_addr(0x404)     → high HW of 0x404 = 0x0005, low HW unchanged
    # LCFI                         → halt
    await write_word(dut, 0x098, encode_imm(OP_LI, r=6, imm=1))
    await write_word(dut, 0x09C, encode(OP_LH,   r=2, x=6, addr=word_addr(0x400)))
    await write_word(dut, 0x0A0, encode(OP_STH,  r=2, addr=word_addr(0x404)))
    # LI R7, 4: idx_data=4>>1=2 (word offset), idx_boff={4[31],0}={0,0}=00
    # LH R3, word_addr(0x400)(R7) → EA word = 2+0x100=0x102, P[32:33]=00 → byte 0x408 high HW
    await write_word(dut, 0x0A4, encode_imm(OP_LI, r=7, imm=4))
    await write_word(dut, 0x0A8, encode(OP_LH,   r=3, x=7, addr=word_addr(0x400)))
    await write_word(dut, 0x0AC, encode(OP_LH,   r=1, addr=word_addr(0x400)))  # last: sets CC
    await write_word(dut, 0x0B0, encode(OP_LCFI, r=0))
    await write_halfword(dut, 0x408, 0x1234)
    await write_halfword(dut, 0x400, 0x8000)
    await write_halfword(dut, 0x402, 0x0005)
    await write_word(dut, 0x404, 0xDEADBEEF)

    await reset_cpu(dut)
    await run_cycles(dut, 160)

    tr.check("LH R2 low HW (indexed)",  rr(dut, 2).value, 0x00000005)
    tr.check("LH R3 word-indexed HW",   rr(dut, 3).value, 0x00001234)
    result = await read_word(dut, 0x404)
    tr.check("STH M.H[0x404]=0x0005",   result,            0x0005BEEF)
    tr.check("LH R1 sign-ext neg",      rr(dut, 1).value, 0xFFFF8000)
    tr.check_bool("LH R1 CC4=1",        cc_neg(dut.sys.cpu.CC.value), True)
    tr.summary()


# ---------------------------------------------------------------------------
# Test: LB, STB — Byte load/store with indexing
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_byte(dut):
    """Test LB and STB — zero extension, byte select via index low 2 bits."""
    tr = TestResults("Byte Load/Store")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await init_memory(dut)
    # Word at 0x400: bytes = 0xAB 0xCD 0xEF 0x01
    # LB R1, word_addr(0x400)      → P[32:33]=00 → byte 0 = 0xAB, R1=0x000000AB
    # LI R7, 2                     → R7=2 → idx_boff=idx_reg[30:31]=10 → P[32:33]=10
    # LB R2, word_addr(0x400)(R7)  → EA word=0x100, P[32:33]=10 → byte 2=0xEF
    #                                R2 = 0x000000EF
    # STB R1, word_addr(0x404)     → byte 0 of 0x404 = 0xAB
    # LCFI                         → halt
    await write_word(dut, 0x098, encode(OP_LB,   r=1, addr=word_addr(0x400)))
    await write_word(dut, 0x09C, encode_imm(OP_LI, r=7, imm=2))
    await write_word(dut, 0x0A0, encode(OP_LB,   r=2, x=7, addr=word_addr(0x400)))
    # LI R3, 10: idx_data=10>>2=2 (word offset), idx_boff=10[30:31]=10 → byte 2 of word 0x102 = 0x40A = 0x33
    await write_word(dut, 0x0A4, encode_imm(OP_LI, r=3, imm=10))
    await write_word(dut, 0x0A8, encode(OP_LB,   r=4, x=3, addr=word_addr(0x400)))
    await write_word(dut, 0x0AC, encode(OP_STB,  r=1, addr=word_addr(0x404)))
    await write_word(dut, 0x0B0, encode(OP_LCFI, r=0))
    await write_word(dut, 0x400, 0xABCDEF01)
    await write_word(dut, 0x404, 0xDEADBEEF)
    await write_word(dut, 0x408, 0x11223344)

    await reset_cpu(dut)
    await run_cycles(dut, 160)

    tr.check("LB R1 byte 0 = 0xAB",     rr(dut, 1).value, 0x000000AB)
    tr.check_bool("LB CC3=1",           cc_pos(dut.sys.cpu.CC.value), True)
    tr.check("LB R2 byte 2 = 0xEF",     rr(dut, 2).value, 0x000000EF)
    tr.check("LB R4 word+byte indexed", rr(dut, 4).value, 0x00000033)  # byte 2 of 0x408 = 0x33
    result = await read_word(dut, 0x404)
    tr.check("STB M.B[0x404]=0xAB",     result,            0xABADBEEF)
    tr.summary()



# ---------------------------------------------------------------------------
# Test: AI, CI — Add/Compare Immediate
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_ai_ci(dut):
    """Test AI (add immediate) and CI (compare immediate)."""
    tr = TestResults("AI and CI")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await init_memory(dut)
    # LI R1, 42          → R1 = 42
    # AI R1, 8           → R1 = 50
    # LI R2, 0           → R2 = 0
    # AI R2, -1          → R2 = 0xFFFFFFFF (negative, CC4=1)
    # CI R1, 50          → R1==50 → CC all clear (equal)
    # CI R1, 49          → R1>49  → CC3=1 (positive/greater)
    # LCFI               → halt
    await write_word(dut, 0x098, encode_imm(OP_LI,  r=1, imm=42))
    await write_word(dut, 0x09C, encode_imm(OP_AI,  r=1, imm=8))    # R1=50
    await write_word(dut, 0x0A0, encode_imm(OP_LI,  r=2, imm=0))
    await write_word(dut, 0x0A4, encode_imm(OP_AI,  r=2, imm=-1))   # R2=0xFFFFFFFF
    await write_word(dut, 0x0A8, encode_imm(OP_CI,  r=1, imm=50))   # R1==50 → CC=0000
    await write_word(dut, 0x0AC, encode(OP_LCFI, r=0))               # halt: check equal CC

    await reset_cpu(dut)
    await run_cycles(dut, 100)

    tr.check("AI R1=50",             rr(dut, 1).value, 50)
    tr.check("AI R2=0xFFFFFFFF",     rr(dut, 2).value, 0xFFFFFFFF)
    tr.check_bool("CI equal CC3=0",  cc_pos(dut.sys.cpu.CC.value), False)
    tr.check_bool("CI equal CC4=0",  cc_neg(dut.sys.cpu.CC.value), False)

    # Second run: check greater-than case
    await write_word(dut, 0x0AC, encode_imm(OP_CI, r=1, imm=49))    # R1>49 → CC3=1
    await write_word(dut, 0x0B0, encode(OP_LCFI, r=0))

    await reset_cpu(dut)
    await run_cycles(dut, 120)

    tr.check_bool("CI greater CC3=1", cc_pos(dut.sys.cpu.CC.value), True)
    tr.check_bool("CI greater CC4=0", cc_neg(dut.sys.cpu.CC.value), False)
    tr.summary()



# ---------------------------------------------------------------------------
# Test: AND, OR, EOR — Logical with CC
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_logical(dut):
    """Test AND, OR, EOR with CC checks."""
    tr = TestResults("Logical Instructions")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await init_memory(dut)
    # LI R1, 0xFF; AND R1, M[0x400]=0x0F  → R1 = 0x0F (CC3=1)
    # LI R2, 0xF0; OR  R2, M[0x404]=0x0F  → R2 = 0xFF (CC4=1)
    # LI R3, 0xFF; EOR R3, M[0x408]=0xFF  → R3 = 0x00 (CC=0000)
    # LCFI → halt
    await write_word(dut, 0x098, encode_imm(OP_LI,  r=1, imm=0xFF))
    await write_word(dut, 0x09C, encode(OP_AND, r=1, addr=word_addr(0x400)))
    await write_word(dut, 0x0A0, encode_imm(OP_LI,  r=2, imm=0xF0))
    await write_word(dut, 0x0A4, encode(OP_OR,  r=2, addr=word_addr(0x404)))
    await write_word(dut, 0x0A8, encode_imm(OP_LI,  r=3, imm=0xFF))
    await write_word(dut, 0x0AC, encode(OP_EOR, r=3, addr=word_addr(0x408)))
    await write_word(dut, 0x0B0, encode(OP_LCFI, r=0))
    await write_word(dut, 0x400, 0x0000000F)
    await write_word(dut, 0x404, 0x0000000F)
    await write_word(dut, 0x408, 0x000000FF)

    await reset_cpu(dut)
    await run_cycles(dut, 130)

    tr.check("AND R1=0x0F",        rr(dut, 1).value, 0x0F)
    tr.check("OR  R2=0xFF",        rr(dut, 2).value, 0xFF)
    tr.check("EOR R3=0x00",        rr(dut, 3).value, 0x00)
    tr.check_bool("EOR zero CC=0", cc_zero(dut.sys.cpu.CC.value), True)
    tr.summary()


# ---------------------------------------------------------------------------
# Test: LW indirect addressing
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_lw_indirect(dut):
    """Test LW with indirect addressing (I=1)."""
    tr = TestResults("LW Indirect")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await init_memory(dut)
    # M[0x800] = word_addr(0x400) — indirect pointer
    # M[0x400] = 0x55AA55AA      — actual data
    # LW R1, 0x800(indirect)     → EA = M[0x800][15:31] = word_addr(0x400)
    #                              R1 = M[0x400] = 0x55AA55AA
    # LW R2, 0x800               → direct: R2 = M[0x800] = word_addr(0x400)
    # LCFI                       → halt
    await write_word(dut, 0x098, encode(OP_LW, r=1, addr=word_addr(0x800), i=1))
    await write_word(dut, 0x09C, encode(OP_LW, r=2, addr=word_addr(0x800)))
    await write_word(dut, 0x0A0, encode(OP_LCFI, r=0))
    await write_word(dut, 0x800, word_addr(0x400))
    await write_word(dut, 0x400, 0x55AA55AA)

    await reset_cpu(dut)
    await run_cycles(dut, 80)

    tr.check("LW indirect R1",  rr(dut, 1).value, 0x55AA55AA)
    tr.check("LW direct R2",    rr(dut, 2).value, word_addr(0x400))
    tr.summary()


# ---------------------------------------------------------------------------
# Test: BCR, BCS — Branch on Conditions
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_branch(dut):
    """Test BCR and BCS — taken/not-taken, unconditional."""
    tr = TestResults("Branch Instructions")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await init_memory(dut)
    # Test 1: BCR R=0 (unconditional) — should always branch
    # LI R1, 1
    # BCR 0, target     → unconditional branch to target
    # LI R1, 99         → should be skipped
    # target: LI R2, 42
    # LCFI
    target = word_addr(0x0B0)
    await write_word(dut, 0x098, encode_imm(OP_LI,  r=1, imm=1))
    await write_word(dut, 0x09C, encode(OP_BCR, r=0, addr=target))   # unconditional
    await write_word(dut, 0x0A0, encode_imm(OP_LI,  r=1, imm=99))   # skipped
    await write_word(dut, 0x0A4, encode_imm(OP_LI,  r=1, imm=99))   # skipped
    await write_word(dut, 0x0A8, encode_imm(OP_LI,  r=1, imm=99))   # skipped
    await write_word(dut, 0x0AC, encode_imm(OP_LI,  r=1, imm=99))   # skipped
    await write_word(dut, 0x0B0, encode_imm(OP_LI,  r=2, imm=42))   # branch target
    await write_word(dut, 0x0B4, encode(OP_LCFI, r=0))

    await reset_cpu(dut)
    await run_cycles(dut, 100)

    tr.check("BCR unconditional R1=1",  rr(dut, 1).value, 1)   # not overwritten
    tr.check("BCR unconditional R2=42", rr(dut, 2).value, 42)  # branch target executed

    # Test 2: BCS taken — set CC4 (negative), branch on CC4 mask
    # AW sets CC4 when result is negative
    # R field = 0b0001 = 1 → mask CC4
    await init_memory(dut)
    # LI R1, -1          → CC4=1 (negative)
    # BCS mask=1, target → CC AND 1 = CC4 AND 1 ≠ 0 → taken
    # LI R3, 99          → skipped
    # target: LI R3, 7
    # LCFI
    target2 = word_addr(0x0A8)
    await write_word(dut, 0x098, encode_imm(OP_LI,  r=1, imm=-1))      # CC4=1
    await write_word(dut, 0x09C, encode(OP_BCS, r=1, addr=target2))     # branch if CC4 set
    await write_word(dut, 0x0A0, encode_imm(OP_LI,  r=3, imm=99))      # skipped
    await write_word(dut, 0x0A4, encode_imm(OP_LI,  r=3, imm=99))      # skipped
    await write_word(dut, 0x0A8, encode_imm(OP_LI,  r=3, imm=7))       # branch target
    await write_word(dut, 0x0AC, encode(OP_LCFI, r=0))

    await reset_cpu(dut)
    await run_cycles(dut, 100)

    tr.check("BCS taken R3=7",    rr(dut, 3).value, 7)

    # Test 3: BCS not-taken — result is positive (CC3=1, CC4=0), mask=CC4 → not taken
    await init_memory(dut)
    # LI R4, 0; AI R4, 1   → R4=1, CC3=1, CC4=0 (AI correctly sets CC via ALU)
    # BCS mask=1            → CC4 AND 1 = 0 → not taken → fall through
    # LI R5, 55             → executed
    # LCFI
    await write_word(dut, 0x098, encode_imm(OP_LI,  r=4, imm=0))
    await write_word(dut, 0x09C, encode_imm(OP_AI,  r=4, imm=1))       # CC3=1, CC4=0
    await write_word(dut, 0x0A0, encode(OP_BCS, r=1, addr=word_addr(0x0B0)))  # not taken
    await write_word(dut, 0x0A4, encode_imm(OP_LI,  r=5, imm=55))      # executed
    await write_word(dut, 0x0A8, encode(OP_LCFI, r=0))
    await write_word(dut, 0x0B0, encode_imm(OP_LI,  r=5, imm=99))      # not reached

    await reset_cpu(dut)
    await run_cycles(dut, 80)

    tr.check("BCS not-taken R5=55", rr(dut, 5).value, 55)
    tr.summary()


# ---------------------------------------------------------------------------
# Test: BAL — Branch and Link (subroutine call)
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_bal(dut):
    """Test BAL — branch and link, return via BCR 0."""
    tr = TestResults("BAL Branch and Link")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await init_memory(dut)
    # Program at 0x098:
    #   LI  R1, 10          ; arg1
    #   LI  R2, 32          ; arg2
    #   BAL R7, sub         ; call subroutine, R7 = return word address
    #   LCFI                ; halt (return lands here)
    #
    # sub (at 0x0B0):
    #   AW  R1, M[arg2_addr]; R1 = R1 + R2... actually use AI for simplicity
    #   AI  R1, 5           ; R1 = 10 + 5 = 15 (just to show subroutine ran)
    #   BCR 0, 0(R7)        ; return: branch to address in R7 (indirect via R7... 
    #                       ; actually BCR 0 with addr=0 indexed by R7)
    #   LCFI

    sub_addr = word_addr(0x0B0)
    ret_addr = word_addr(0x0A4)   # word address of instruction after BAL

    await write_word(dut, 0x098, encode_imm(OP_LI,  r=1, imm=10))
    await write_word(dut, 0x09C, encode_imm(OP_LI,  r=2, imm=32))
    await write_word(dut, 0x0A0, encode(OP_BAL, r=7, addr=sub_addr))  # R7 ← ret_addr
    await write_word(dut, 0x0A4, encode(OP_LCFI, r=0))                 # return target
    # subroutine at 0x0B0
    await write_word(dut, 0x0B0, encode_imm(OP_AI,  r=1, imm=5))      # R1 = 15
    await write_word(dut, 0x0B4, encode(OP_BCR, r=0, addr=0, x=7))    # return via R7
    await write_word(dut, 0x0B8, encode(OP_LCFI, r=0))                 # not reached

    await reset_cpu(dut)
    await run_cycles(dut, 150)

    tr.check("BAL R1=15 (sub ran)",  rr(dut, 1).value, 15)
    tr.check("BAL R7=ret_addr",      rr(dut, 7).value, ret_addr)
    tr.summary()


# ---------------------------------------------------------------------------
# Test: RD, WD — Direct I/O (console status and output)
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_rd_wd(dut):
    """Test RD (status register) and WD (console output)."""
    tr = TestResults("RD and WD")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await init_memory(dut)
    # RD R1, 0x1002        → R1 = status register (TX ready bit 30 = 1)
    # WD R0, 0x1001        → write 0 to console (null char, should not crash)
    # LI R2, 0x41          → R2 = 'A' (0x41)
    # WD R2, 0x1001        → write 'A' to console stdout
    # LCFI                 → halt
    status_addr = 0x1002
    data_addr   = 0x1001
    await write_word(dut, 0x098, encode(OP_RD,   r=1, addr=status_addr))
    await write_word(dut, 0x09C, encode(OP_WD,   r=0, addr=data_addr))
    await write_word(dut, 0x0A0, encode_imm(OP_LI, r=2, imm=0x41))   # 'A'
    await write_word(dut, 0x0A4, encode(OP_WD,   r=2, addr=data_addr))
    await write_word(dut, 0x0A8, encode(OP_LCFI, r=0))

    await reset_cpu(dut)
    await run_cycles(dut, 120)

    # TX ready bit (bit 30 = value 2 in big-endian) should be set
    status = int(rr(dut, 1).value)
    tr.check_bool("RD status TX ready", bool(status & 2), True)
    tr.summary()


# ---------------------------------------------------------------------------
# Test: PSW and PLW — push-down stack
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_psw_plw(dut):
    """Test PSW (push word) and PLW (pull word) with a simple stack."""
    tr = TestResults("PSW and PLW")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await init_memory(dut, size=0x1000)

    # Stack layout:
    #   SPD at word 0x200: word 0 = {15'b0, initial_TOS}
    #   Stack area: words 0x201..0x240 (grows upward)
    #   Initial TOS = 0x200 (empty — first push will write to 0x201)
    SPD_ADDR = 0x200
    INIT_TOS  = 0x200

    # Program at boot address 0x026:
    #   LI  R1, 0xAA        ; value to push
    #   LI  R2, 0xBB        ; another value
    #   PSW R1, SPD_ADDR    ; push R1 → stack[0x201]=0xAA; TOS=0x201
    #   PSW R2, SPD_ADDR    ; push R2 → stack[0x202]=0xBB; TOS=0x202
    #   PLW R3, SPD_ADDR    ; pull → R3=0xBB; TOS=0x201
    #   PLW R4, SPD_ADDR    ; pull → R4=0xAA; TOS=0x200
    #   LCFI                ; halt

    await write_word(dut, SPD_ADDR * 4, INIT_TOS)   # SPD[0] = initial TOS

    await write_word(dut, 0x098, encode_imm(OP_LI,  r=1, imm=0xAA))
    await write_word(dut, 0x09C, encode_imm(OP_LI,  r=2, imm=0xBB))
    await write_word(dut, 0x0A0, encode(OP_PSW, r=1, addr=SPD_ADDR))
    await write_word(dut, 0x0A4, encode(OP_PSW, r=2, addr=SPD_ADDR))
    await write_word(dut, 0x0A8, encode(OP_PLW, r=3, addr=SPD_ADDR))
    await write_word(dut, 0x0AC, encode(OP_PLW, r=4, addr=SPD_ADDR))
    await write_word(dut, 0x0B0, encode(OP_LCFI, r=0))

    await reset_cpu(dut)
    await run_cycles(dut, 200)

    tr.check("PSW/PLW R3=0xBB (LIFO order)", rr(dut, 3).value, 0xBB)
    tr.check("PSW/PLW R4=0xAA (LIFO order)", rr(dut, 4).value, 0xAA)

    # Check TOS was restored to initial value
    spd_val = int(dut.sys.memory.mem[SPD_ADDR * 4 + 3].value) | \
              (int(dut.sys.memory.mem[SPD_ADDR * 4 + 2].value) << 8) | \
              (int(dut.sys.memory.mem[SPD_ADDR * 4 + 1].value) << 16) | \
              (int(dut.sys.memory.mem[SPD_ADDR * 4 + 0].value) << 24)
    tr.check("SPD TOS restored", spd_val, INIT_TOS)
    tr.summary()



# ---------------------------------------------------------------------------
# Test: S — Shift (logical, single register)
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_shift(dut):
    """Test S instruction: logical left and right shifts, single register."""
    tr = TestResults("S - Shift (logical single register)")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())
    await init_memory(dut, size=0x1000)

    # S R, addr encodes shift type in addr bits 21-23 and count in bits 25-31.
    # For logical single register: bits 21-23 = 000.
    # The address field = count directly (0-63 left, use negative for right).
    # S R1, 4   → logical left  4  (addr=4  = 0x000004)
    # S R1, 1   → logical left  1  (addr=1  = 0x000001)
    # S R1, 8   → logical left  8  (addr=8)
    # S R1, 28  → logical left  28 (addr=28)
    # For right shift: count is negative 7-bit = embed in addr bits 25-31.
    # addr = 0x7C = 0b1111100 = -4 as 7-bit signed → right 4
    # addr = 0x7F = 0b1111111 = -1 as 7-bit signed → right 1

    # Encode S instruction: {I=0, op=0x25, R, X=0, addr}
    def enc_shift(r, count):
        # count: positive=left, negative=right (7-bit signed in addr[25:31])
        if count < 0:
            addr = ((-count) ^ 0x7F) + 1  # two's complement in 7 bits, place in bits 25-31
            addr = addr & 0x7F             # 7 bits
        else:
            addr = count & 0x7F
        return (0x25 << 24) | (r << 20) | addr

    # Program at boot:
    #   LI  R1, 0x12345678   (but LI only has 20 bits — load upper/lower separately)
    #   We'll use AI + LI to build the test value.
    #   Actually: use two LI + shift trick. Simplest: just use a known 20-bit value.
    #   LI R1, 0x00F0F  (= 0x000F0F sign-extended = 0x000F0F0F... no)
    #   Let's use LI R1, 1 then shift left various amounts.

    # Test 1: left shift by 4
    # LI R1, 1; S R1, 4 → R1 should be 0x10 (1 << 4, but big-endian: 1 in bit 31 → shift to bit 27)
    # In big-endian bit 31 = LSB = value 1. Shift left 4: bit 27 = value 0x10.
    # So LI R1, 1 → R1 = 0x00000001. S R1, 4 → R1 = 0x00000010. ✓ (same as little-endian math)

    # Test 2: left shift by 1
    # Test 3: left shift by 8
    # Test 4: right shift by 4
    # Test 5: right shift by 1
    # Test 6: shift by 0 (no-op)
    # Test 7: left shift 28 (extracts top nibble position — monitor use case)
    # Test 8: chain — LI R1, 0xABCDE (20-bit) then shift left 12 to get upper bits

    prog = 0x098  # byte address
    def wp(addr, val):
        return (addr, val)

    instructions = [
        # --- Test 1: LI R1, 1; S R1, 4 → R1 = 0x10 ---
        encode_imm(OP_LI, r=1, imm=1),
        enc_shift(1, 4),
        encode(OP_STW, r=1, addr=0x400),     # save result

        # --- Test 2: LI R1, 1; S R1, 1 → R1 = 0x02 ---
        encode_imm(OP_LI, r=1, imm=1),
        enc_shift(1, 1),
        encode(OP_STW, r=1, addr=0x401),

        # --- Test 3: LI R1, 1; S R1, 8 → R1 = 0x100 ---
        encode_imm(OP_LI, r=1, imm=1),
        enc_shift(1, 8),
        encode(OP_STW, r=1, addr=0x402),

        # --- Test 4: LI R1, 0x80; S R1, -4 (right 4) → R1 = 0x08 ---
        encode_imm(OP_LI, r=1, imm=0x80),
        enc_shift(1, -4),
        encode(OP_STW, r=1, addr=0x403),

        # --- Test 5: LI R1, 0x80; S R1, -1 (right 1) → R1 = 0x40 ---
        encode_imm(OP_LI, r=1, imm=0x80),
        enc_shift(1, -1),
        encode(OP_STW, r=1, addr=0x404),

        # --- Test 6: LI R1, 0x55; S R1, 0 (shift by 0) → R1 = 0x55 ---
        encode_imm(OP_LI, r=1, imm=0x55),
        enc_shift(1, 0),
        encode(OP_STW, r=1, addr=0x405),

        # --- Test 7: LI R1, 0xABCDE; S R1, 12 → 0xABCDE000 ---
        encode_imm(OP_LI, r=1, imm=0xABCDE),
        enc_shift(1, 12),
        encode(OP_STW, r=1, addr=0x406),

        # --- Test 8: LI R1, 0x7F000; S R1, -16 (right 16) → 0x00000007 ---
        encode_imm(OP_LI, r=1, imm=0x7F000),
        enc_shift(1, -16),
        encode(OP_STW, r=1, addr=0x407),

        encode(OP_LCFI, r=0),  # halt
    ]

    for i, instr in enumerate(instructions):
        await write_word(dut, 0x098 + i*4, instr)

    await reset_cpu(dut)
    await run_cycles(dut, 600)

    def mem_word(addr):
        b = [int(dut.sys.memory.mem[addr*4+j].value) for j in range(4)]
        return (b[0]<<24)|(b[1]<<16)|(b[2]<<8)|b[3]

    tr.check("S R1, 4   (left  4): 0x00000010", mem_word(0x400), 0x00000010)
    tr.check("S R1, 1   (left  1): 0x00000002", mem_word(0x401), 0x00000002)
    tr.check("S R1, 8   (left  8): 0x00000100", mem_word(0x402), 0x00000100)
    tr.check("S R1,-4   (right 4): 0x00000008", mem_word(0x403), 0x00000008)
    tr.check("S R1,-1   (right 1): 0x00000040", mem_word(0x404), 0x00000040)
    tr.check("S R1, 0   (shift 0): 0x00000055", mem_word(0x405), 0x00000055)
    tr.check("S R1, 12  (left 12): 0xABCDE000", mem_word(0x406), 0xABCDE000)
    tr.check("S R1,-16  (right16): 0x00000007", mem_word(0x407), 0x00000007)
    tr.summary()


# ---------------------------------------------------------------------------
# Test: Register-file address mapping (EA 0-15 → RR, not memory)
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_reg_mapping(dut):
    """EA 0-15 accesses RR directly: LW R2,1 loads RR[1]; STW R2,3 stores to RR[3]."""
    tr = TestResults("Register-file address mapping")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())
    await init_memory(dut, size=0x1000)

    # Program:
    #   LI  R1, 0xAA      ; R1 = 0xAA
    #   LI  R2, 0xBB      ; R2 = 0xBB
    #   LW  R3, 1         ; R3 ← RR[1] = 0xAA  (register-to-register load)
    #   STW R2, 4         ; RR[4] ← R2 = 0xBB  (register-to-register store)
    #   AW  R5, 1         ; R5 ← R5 + RR[1] = 0 + 0xAA = 0xAA
    #   LI  R6, 0xCC
    #   STW R6, 7         ; RR[7] ← 0xCC
    #   LW  R8, 7         ; R8 ← RR[7] = 0xCC
    #   LCFI

    prog = [
        encode_imm(OP_LI,  r=1, imm=0xAA),
        encode_imm(OP_LI,  r=2, imm=0xBB),
        encode(OP_LW,  r=3, addr=1),        # R3 ← RR[1]
        encode(OP_STW, r=2, addr=4),        # RR[4] ← R2
        encode(OP_AW,  r=5, addr=1),        # R5 ← R5 + RR[1] = 0xAA
        encode_imm(OP_LI,  r=6, imm=0xCC),
        encode(OP_STW, r=6, addr=7),        # RR[7] ← 0xCC
        encode(OP_LW,  r=8, addr=7),        # R8 ← RR[7]
        encode(OP_LCFI, r=0),
    ]
    for i, instr in enumerate(prog):
        await write_word(dut, 0x098 + i*4, instr)

    await reset_cpu(dut)
    await run_cycles(dut, 300)

    tr.check("LW  R3,1  → R3=RR[1]=0xAA", rr(dut,3).value, 0xAA)
    tr.check("STW R2,4  → RR[4]=0xBB",    rr(dut,4).value, 0xBB)
    tr.check("AW  R5,1  → R5=0+0xAA",     rr(dut,5).value, 0xAA)
    tr.check("LW  R8,7  → R8=RR[7]=0xCC", rr(dut,8).value, 0xCC)
    tr.summary()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    proj_dir = os.getcwd().replace('\\', '/')
    os.makedirs("vcd", exist_ok=True)
    files = ["Sigma7TB.v", "Sigma7System.v", "Sigma7CPU.v", "Memory.v", "Console.v", "BusArbiter.v", "IOProcessor.v"]
    sources = [f"verilog/{f}" for f in files]

    runner = get_runner("icarus")
    runner.build(
        sources=sources,
        hdl_toplevel="Sigma7TB",
        build_dir="vcd",
        always=True,
        defines={"PROJ_DIR": proj_dir},
    )
    runner.test(hdl_toplevel="Sigma7TB", test_module="Sigma7TB,", waves=True)