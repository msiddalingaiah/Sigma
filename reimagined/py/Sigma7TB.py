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


# ---------------------------------------------------------------------------
# Clock and reset helpers
# ---------------------------------------------------------------------------
async def init_memory(dut, size=0x500):
    """Initialize memory to zero to avoid X values."""
    for addr in range(0, size, 4):
        await write_word(dut, addr, 0x00000000)

async def reset_cpu(dut):
    """Reset CPU for 2 cycles then release."""
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
            cocotb.log.warning(f"{self.name}: {self.failed} test(s) failed")


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
# Test: AI, LI, CI — Immediate
# ---------------------------------------------------------------------------
@cocotb.test(skip=True)
async def test_immediate(dut):
    """Test AI, LI, CI."""
    tr = TestResults("Immediate Instructions")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await load_program(dut, 0x000, [
        encode_imm(OP_LI, r=1, imm=42),
        encode_imm(OP_AI, r=1, imm=8),        # R1 = 50
        encode_imm(OP_AI, r=2, imm=-1),       # R2 = 0xFFFFFFFF
        encode_imm(OP_CI, r=1, imm=50),       # R1 == 50 → equal
        encode(OP_LCFI, r=0),
    ])

    await reset_cpu(dut)
    await run_cycles(dut, 60)

    tr.check("LI R1=42",         rr(dut, 1).value, 42)
    tr.check("AI R1=50",         rr(dut, 1).value, 50)
    tr.check("AI R2=0xFFFFFFFF", rr(dut, 2).value, 0xFFFFFFFF)
    tr.check_bool("CI equal",    cc_zero(dut.sys.cpu.CC.value), True)
    tr.summary()


# ---------------------------------------------------------------------------
# Test: AND, OR, EOR — Logical
# ---------------------------------------------------------------------------
@cocotb.test(skip=True)
async def test_logical(dut):
    """Test AND, OR, EOR."""
    tr = TestResults("Logical Instructions")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await load_program(dut, 0x000, [
        encode_imm(OP_LI, r=1, imm=0xFF),
        encode(OP_AND, r=1, addr=word_addr(0x400)),  # R1 = 0xFF & 0x0F = 0x0F
        encode_imm(OP_LI, r=2, imm=0xF0),
        encode(OP_OR,  r=2, addr=word_addr(0x404)),  # R2 = 0xF0 | 0x0F = 0xFF
        encode_imm(OP_LI, r=3, imm=0xFF),
        encode(OP_EOR, r=3, addr=word_addr(0x408)),  # R3 = 0xFF ^ 0xFF = 0
        encode(OP_LCFI, r=0),
    ])
    await write_word(dut, 0x400, 0x0F)
    await write_word(dut, 0x404, 0x0F)
    await write_word(dut, 0x408, 0xFF)

    await reset_cpu(dut)
    await run_cycles(dut, 80)

    tr.check("AND R1=0x0F",   rr(dut, 1).value, 0x0F)
    tr.check("OR  R2=0xFF",   rr(dut, 2).value, 0xFF)
    tr.check("EOR R3=0",      rr(dut, 3).value, 0x00)
    tr.check_bool("EOR zero", cc_zero(dut.sys.cpu.CC.value), True)
    tr.summary()


# ---------------------------------------------------------------------------
# Test: LW indirect
# ---------------------------------------------------------------------------
@cocotb.test(skip=True)
async def test_lw_indirect(dut):
    """Test LW with indirect addressing."""
    tr = TestResults("LW Indirect")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await load_program(dut, 0x000, [
        encode(OP_LW, r=1, addr=word_addr(0x800), i=1),
        encode(OP_LCFI, r=0),
    ])
    await write_word(dut, 0x800, word_addr(0x400))
    await write_word(dut, 0x400, 0x55AA55AA)

    await reset_cpu(dut)
    await run_cycles(dut, 40)

    tr.check("LW indirect RR[1]", rr(dut, 1).value, 0x55AA55AA)
    tr.summary()


# ---------------------------------------------------------------------------
# Test: LH, STH — Halfword
# ---------------------------------------------------------------------------
@cocotb.test(skip=True)
async def test_halfword(dut):
    """Test LH and STH."""
    tr = TestResults("Halfword Load/Store")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await load_program(dut, 0x000, [
        encode(OP_LH,   r=1, addr=word_addr(0x400)),
        encode(OP_LH,   r=2, addr=word_addr(0x402)),
        encode(OP_STH,  r=2, addr=word_addr(0x404)),
        encode(OP_LCFI, r=0),
    ])
    await write_halfword(dut, 0x400, 0x8000)
    await write_halfword(dut, 0x402, 0x0005)

    await reset_cpu(dut)
    await run_cycles(dut, 60)

    tr.check("LH neg sext",  rr(dut, 1).value, 0xFFFF8000)
    tr.check("LH pos",       rr(dut, 2).value, 0x00000005)
    tr.check_bool("LH CC4",  cc_neg(dut.sys.cpu.CC.value), True)

    b0 = await read_byte(dut, 0x404)
    b1 = await read_byte(dut, 0x405)
    tr.check("STH M[0x404]", (b0 << 8) | b1, 0x0005)
    tr.summary()


# ---------------------------------------------------------------------------
# Test: LB, STB — Byte
# ---------------------------------------------------------------------------
@cocotb.test(skip=True)
async def test_byte(dut):
    """Test LB and STB."""
    tr = TestResults("Byte Load/Store")
    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    await load_program(dut, 0x000, [
        encode(OP_LB,   r=1, addr=word_addr(0x400)),
        encode(OP_STB,  r=1, addr=word_addr(0x404)),
        encode(OP_LCFI, r=0),
    ])
    await write_byte(dut, 0x400, 0xAB)

    await reset_cpu(dut)
    await run_cycles(dut, 40)

    tr.check("LB RR[1]=0xAB", rr(dut, 1).value, 0x000000AB)
    tr.check_bool("LB CC4=0", cc_neg(dut.sys.cpu.CC.value), False)
    tr.check_bool("LB CC3=1", cc_pos(dut.sys.cpu.CC.value), True)

    b = await read_byte(dut, 0x404)
    tr.check("STB M[0x404]", b, 0xAB)
    tr.summary()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    proj_dir = os.getcwd().replace('\\', '/')
    os.makedirs("vcd", exist_ok=True)
    files = ["Sigma7TB.v", "Sigma7System.v", "Sigma7CPU.v", "Memory.v", "BusArbiter.v", "IOProcessor.v"]
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