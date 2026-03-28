#!/usr/bin/env python3
"""
SDS/Xerox Sigma 7 CPU Simulator
Implements RTL for all documented instructions and runs automated test cases.
"""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WORD_MASK  = 0xFFFFFFFF
HALF_MASK  = 0x0000FFFF
BYTE_MASK  = 0x000000FF
MEM_SIZE   = 512 * 1024   # 512 KB (19-bit byte address space)

def mask32(v): return v & WORD_MASK
def mask16(v): return v & HALF_MASK
def mask8(v):  return v & BYTE_MASK

def sext(v, bits):
    """Sign-extend v from 'bits' bits to 32 bits."""
    v &= (1 << bits) - 1
    if v & (1 << (bits - 1)):
        v |= WORD_MASK ^ ((1 << bits) - 1)
    return mask32(v)

def upward_align_byte(v):
    """Replicate low byte into all four byte positions."""
    b = v & BYTE_MASK
    return mask32((b << 24) | (b << 16) | (b << 8) | b)

def upward_align_halfword(v):
    """Replicate low halfword into both halfword positions."""
    h = v & HALF_MASK
    return mask32((h << 16) | h)

def signed32(v):
    v = mask32(v)
    return v - (1 << 32) if v & 0x80000000 else v


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
class Memory:
    def __init__(self, size=MEM_SIZE):
        self.data = bytearray(size)

    def read_word(self, addr):
        addr &= 0x7FFFC   # word-align, 19-bit space
        d = self.data
        return (d[addr] << 24) | (d[addr+1] << 16) | (d[addr+2] << 8) | d[addr+3]

    def write_word(self, addr, val):
        addr &= 0x7FFFC
        val   = mask32(val)
        self.data[addr]   = (val >> 24) & 0xFF
        self.data[addr+1] = (val >> 16) & 0xFF
        self.data[addr+2] = (val >>  8) & 0xFF
        self.data[addr+3] =  val        & 0xFF

    def read_halfword(self, addr):
        addr &= 0x7FFFE   # halfword-align
        return (self.data[addr] << 8) | self.data[addr+1]

    def write_halfword(self, addr, val):
        addr &= 0x7FFFE
        val   = mask16(val)
        self.data[addr]   = (val >> 8) & 0xFF
        self.data[addr+1] =  val       & 0xFF

    def read_byte(self, addr):
        return self.data[addr & 0x7FFFF]

    def write_byte(self, addr, val):
        self.data[addr & 0x7FFFF] = mask8(val)

    def load(self, byte_addr, words):
        """Write a list of 32-bit words to memory starting at byte_addr."""
        for i, w in enumerate(words):
            self.write_word(byte_addr + i * 4, w)


# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------
class Sigma7CPU:
    """
    Sigma 7 CPU simulator.

    Instruction word layout (Sigma big-endian, bit 0 = MSB of 32-bit word):
      bit  0      → I    (indirect flag)     → standard bit 31
      bits 1-7    → op   (7-bit opcode)      → standard bits 30-24
      bits 8-11   → r    (R field / register) → standard bits 23-20
      bits 12-14  → x    (X field / index)   → standard bits 19-17
      bits 15-31  → addr (17-bit word index)  → standard bits 16-0

    Immediate instructions use bits 12-31 (20-bit signed immediate).

    P (19-bit byte address):
      P[15:31] = upper 17 bits = word address  (= P >> 2)
      P[32:33] = lower  2 bits = byte offset   (= P & 3)
    Q (17-bit word address): byte address = Q << 2
    """

    # Opcode constants
    OP_AD  = 0x10; OP_CD  = 0x11; OP_LD  = 0x12; OP_STD = 0x15
    OP_SD  = 0x18; OP_LCD = 0x1A; OP_LAD = 0x1B
    OP_AI  = 0x20; OP_CI  = 0x21; OP_LI  = 0x22; OP_MI  = 0x23
    OP_AW  = 0x30; OP_CW  = 0x31; OP_LW  = 0x32; OP_STW = 0x35
    OP_SW  = 0x38; OP_LCW = 0x3A; OP_LAW = 0x3B
    OP_EOR = 0x48; OP_OR  = 0x49; OP_AH  = 0x50; OP_CH  = 0x51
    OP_LH  = 0x52; OP_MTH = 0x53; OP_STH = 0x55
    OP_SH  = 0x58; OP_LCH = 0x5A; OP_LAH = 0x5B
    OP_AND = 0x4B; OP_CB  = 0x71; OP_LB  = 0x72; OP_MTB = 0x73
    OP_STB = 0x75

    def __init__(self, memory=None):
        self.mem  = memory or Memory()
        self.RR   = [0] * 16   # user-visible registers
        self.A    = 0           # primary ALU input
        self.B    = 0           # multiply/divide pair with A
        self.C    = 0           # memory interface (transparent latch)
        self.D    = 0           # secondary ALU input
        self.E    = 0           # floating-point exponent (8-bit)
        self.O    = 0           # opcode register (7-bit)
        self.R    = 0           # register-field register (4-bit)
        self.P    = 0           # effective byte address (19-bit)
        self.Q    = 0           # next instruction word address (17-bit)
        self.AWZ  = False       # A-Was-Zero flip-flop (doubleword zero detection)
        self.carry = 0
        self.CC1  = False      # carry
        self.CC2  = False      # overflow
        self.CC3  = False      # positive
        self.CC4  = False      # negative

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def set_cc_arith(self, result, carry=0, overflow=False):
        """CC for arithmetic/load/logical instructions."""
        result = mask32(result)
        self.CC1 = bool(carry)
        self.CC2 = bool(overflow)
        self.CC3 = (result != 0) and not bool(result & 0x80000000)
        self.CC4 = bool(result & 0x80000000)

    def set_cc_arith_dw(self, hi, awz, carry=0, overflow=False):
        """CC for doubleword arithmetic/load instructions."""
        hi = mask32(hi)
        self.CC1 = bool(carry)
        self.CC2 = bool(overflow)
        self.CC4 = bool(hi & 0x80000000)
        self.CC3 = (not self.CC4) and (not (hi == 0 and awz))

    def set_cc_compare(self, reg, operand):
        """CC for compare instructions."""
        self.CC1 = False
        self.CC2 = bool(mask32(reg) & mask32(operand))   # bitwise AND non-zero
        s_reg = signed32(reg)
        s_op  = signed32(operand)
        self.CC3 = s_reg > s_op
        self.CC4 = s_reg < s_op

    def set_cc_compare_dw(self, reg_hi, reg_lo, op_hi, op_lo):
        """CC for doubleword compare instructions."""
        self.CC1 = False
        self.CC2 = bool((mask32(reg_hi) & mask32(op_hi)) or
                        (mask32(reg_lo) & mask32(op_lo)))
        r64 = (mask32(reg_hi) << 32) | mask32(reg_lo)
        o64 = (mask32(op_hi)  << 32) | mask32(op_lo)
        # treat as signed 64-bit
        if r64 & (1 << 63): r64 -= (1 << 64)
        if o64 & (1 << 63): o64 -= (1 << 64)
        self.CC3 = r64 > o64
        self.CC4 = r64 < o64

    def set_cc_abs(self, result, overflow=False):
        """CC for load absolute instructions (LAW, LAH, LAD)."""
        result = mask32(result)
        self.CC1 = False
        self.CC2 = bool(overflow)
        self.CC3 = result != 0 and not overflow
        self.CC4 = bool(overflow)   # only set on overflow

    def set_cc_abs_dw(self, hi, awz, overflow=False):
        """CC for doubleword load absolute."""
        hi = mask32(hi)
        self.CC1 = False
        self.CC2 = bool(overflow)
        self.CC3 = not overflow and not (hi == 0 and awz)
        self.CC4 = bool(overflow)

    def set_cc_complement(self, result, carry=0, overflow=False):
        """CC for load complement instructions (LCW, LCH, LCD)."""
        result = mask32(result)
        self.CC1 = bool(carry)
        self.CC2 = bool(overflow)
        self.CC3 = (result != 0) and not bool(result & 0x80000000) and not overflow
        self.CC4 = bool(result & 0x80000000) or bool(overflow)

    def set_cc_complement_dw(self, hi, awz, carry=0, overflow=False):
        """CC for doubleword load complement."""
        hi = mask32(hi)
        self.CC1 = bool(carry)
        self.CC2 = bool(overflow)
        self.CC4 = bool(hi & 0x80000000) or bool(overflow)
        self.CC3 = not self.CC4 and not (hi == 0 and awz)

    def set_cc_byte(self, result):
        """CC for LB and MTB — CC3 only, CC4 never set."""
        self.CC1 = False
        self.CC2 = False
        self.CC3 = mask8(result) != 0
        self.CC4 = False

    def cc_dict(self):
        return {'CC1': self.CC1, 'CC2': self.CC2,
                'CC3': self.CC3, 'CC4': self.CC4}

    def alu_add(self, a, b, cin=0):
        """32-bit add; updates carry and overflow."""
        a = mask32(a); b = mask32(b)
        result = a + b + cin
        self.carry = 1 if result > WORD_MASK else 0
        sa = bool(a      & 0x80000000)
        sb = bool(b      & 0x80000000)
        sr = bool(result & 0x80000000)
        self.CC2 = (sa == sb) and (sa != sr)
        self.CC1 = bool(self.carry)
        return mask32(result)

    def alu_sub(self, a, b):
        """32-bit subtract a − b via two's complement."""
        return self.alu_add(a, mask32(~b), 1)

    # ------------------------------------------------------------------
    # Instruction encoding helpers
    # ------------------------------------------------------------------
    @staticmethod
    def encode(op, r=0, x=0, addr=0, i=0):
        """
        Build a 32-bit Sigma 7 instruction word.
        addr is a 17-bit WORD index (not byte address).
        """
        return (mask32(i) << 31) | ((op & 0x7F) << 24) | \
               ((r  & 0x0F) << 20) | ((x & 0x07) << 17) | (addr & 0x1FFFF)

    @staticmethod
    def encode_imm(op, r=0, imm=0):
        """
        Build an immediate instruction (20-bit signed immediate in bits 12-31).
        imm is a signed Python integer.
        """
        imm20 = mask32(imm) & 0xFFFFF
        return ((op & 0x7F) << 24) | ((r & 0x0F) << 20) | imm20

    @staticmethod
    def decode(instr):
        i    = (instr >> 31) & 1
        op   = (instr >> 24) & 0x7F
        r    = (instr >> 20) & 0x0F
        x    = (instr >> 17) & 0x07
        addr = instr & 0x1FFFF
        return i, op, r, x, addr

    # ------------------------------------------------------------------
    # Prep: effective address calculation
    # ------------------------------------------------------------------
    def _prep(self, i, x, addr, size='word'):
        """
        Execute PREP phases; return effective byte address in P.
        addr = 17-bit word index from instruction.
        size = 'word' | 'halfword' | 'byte' | 'doubleword'
        Sets A and P[32:33] consistent with ENDE, then runs PREP1-3.
        """
        # ENDE: set up A and P[32:33] for indexing
        if x == 0:
            index = 0
            byte_off = 0
        else:
            rx = mask32(self.RR[x])
            if size == 'byte':
                index    = rx >> 2
                byte_off = rx & 3
            elif size == 'halfword':
                index    = rx >> 1
                byte_off = (rx & 1) << 1
            elif size == 'doubleword':
                index    = mask32(rx << 1) & 0x1FFFF
                byte_off = 0
            else:  # word
                index    = rx & 0x1FFFF
                byte_off = 0
        self.A = mask32(index)

        # Preserve word address from P, set byte offset
        self.P = (self.P & ~3) | byte_off

        # PREP1: Q ← P[15:31]  (save next instruction word address)
        self.Q = self.P >> 2

        # PREP2: indirect resolution (hardware masks C to bits 15-31 = word address)
        word_ptr = addr   # start with instruction address field as word index
        if i:
            byte_ptr   = word_ptr << 2
            self.C     = self.mem.read_word(byte_ptr)
            self.D     = self.C
            word_ptr   = self.C & 0x1FFFF   # resolved word address

        # PREP3: P[15:31] ← A + D[15:31];  P[32:33] unchanged
        word_ea  = (index + word_ptr) & 0x1FFFF
        self.P   = (word_ea << 2) | (self.P & 3)
        return self.P

    # ------------------------------------------------------------------
    # Main execute entry point
    # ------------------------------------------------------------------
    def execute(self, instr):
        """Execute a single pre-fetched instruction word."""
        i, op, r, x, addr = self.decode(instr)
        self.O = op
        self.R = r

        dispatch = {
            self.OP_AW:  self._AW,  self.OP_SW:  self._SW,  self.OP_CW:  self._CW,
            self.OP_AI:  self._AI,  self.OP_CI:  self._CI,  self.OP_LI:  self._LI,
            self.OP_LW:  self._LW,  self.OP_STW: self._STW, self.OP_LCW: self._LCW,
            self.OP_LAW: self._LAW,
            self.OP_AH:  self._AH,  self.OP_SH:  self._SH,  self.OP_CH:  self._CH,
            self.OP_LH:  self._LH,  self.OP_STH: self._STH, self.OP_LCH: self._LCH,
            self.OP_LAH: self._LAH, self.OP_MTH: self._MTH,
            self.OP_LB:  self._LB,  self.OP_STB: self._STB, self.OP_CB:  self._CB,
            self.OP_MTB: self._MTB,
            self.OP_AND: self._AND, self.OP_OR:  self._OR,  self.OP_EOR: self._EOR,
            self.OP_LD:  self._LD,  self.OP_STD: self._STD, self.OP_AD:  self._AD,
            self.OP_SD:  self._SD,  self.OP_CD:  self._CD,  self.OP_LCD: self._LCD,
            self.OP_LAD: self._LAD,
        }
        if op not in dispatch:
            raise ValueError(f"Unimplemented opcode: 0x{op:02X}")
        dispatch[op](i, r, x, addr)

    # ------------------------------------------------------------------
    # Word arithmetic
    # ------------------------------------------------------------------
    def _AW(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'word')
        self.A = self.RR[r]
        self.C = self.mem.read_word(ea); self.D = self.C
        s = self.alu_add(self.A, self.D)
        self.A = s; self.RR[r] = s
        self.set_cc_arith(self.A, self.carry, self.CC2)

    def _SW(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'word')
        self.A = self.RR[r]
        self.C = self.mem.read_word(ea); self.D = self.C
        s = self.alu_sub(self.A, self.D)
        self.A = s; self.RR[r] = s
        self.set_cc_arith(self.A, self.carry, self.CC2)

    def _CW(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'word')
        self.A = self.RR[r]
        self.C = self.mem.read_word(ea); self.D = self.C
        s = self.alu_sub(self.A, self.D)
        self.A = s
        self.set_cc_compare(self.RR[r], self.D)

    def _imm20(self, x, addr):
        """Reconstruct 20-bit signed immediate from X and addr fields."""
        return sext((x << 17) | addr, 20)

    def _AI(self, i, r, x, addr):
        imm = self._imm20(x, addr)
        self.A = self.RR[r]; self.D = imm
        s = self.alu_add(self.A, self.D)
        self.A = s; self.RR[r] = s
        self.set_cc_arith(self.A, self.carry, self.CC2)

    def _CI(self, i, r, x, addr):
        imm = self._imm20(x, addr)
        self.A = self.RR[r]; self.D = imm
        s = self.alu_sub(self.A, self.D)
        self.A = s
        self.set_cc_compare(self.RR[r], mask32(self.D))

    def _LI(self, i, r, x, addr):
        imm = self._imm20(x, addr)
        self.A = imm
        self.RR[r] = imm
        self.set_cc_arith(self.A)

    # ------------------------------------------------------------------
    # Word load / store
    # ------------------------------------------------------------------
    def _LW(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'word')
        self.C = self.mem.read_word(ea); self.A = self.C
        self.RR[r] = self.A
        self.set_cc_arith(self.A, self.carry, self.CC2)

    def _STW(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'word')
        self.A = self.RR[r]
        self.mem.write_word(ea, self.A)

    def _LCW(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'word')
        self.C = self.mem.read_word(ea); self.D = self.C
        s = self.alu_add(mask32(~self.D), 0, 1)
        self.A = s; self.RR[r] = s
        self.set_cc_arith(self.A, self.carry, self.CC2)

    def _LAW(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'word')
        self.C = self.mem.read_word(ea); self.D = self.C
        if self.D & 0x80000000:   # negative → negate
            s = self.alu_add(mask32(~self.D), 0, 1)
        else:
            s = self.D
        self.A = s; self.RR[r] = s
        self.set_cc_abs(self.A, self.CC2)

    # ------------------------------------------------------------------
    # Halfword arithmetic
    # ------------------------------------------------------------------
    def _AH(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'halfword')
        self.A = self.RR[r]
        hw = self.mem.read_halfword(ea)
        self.C = hw; self.D = sext(hw, 16)
        s = self.alu_add(self.A, self.D)
        self.A = s; self.RR[r] = s
        self.set_cc_arith(self.A, self.carry, self.CC2)

    def _SH(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'halfword')
        self.A = self.RR[r]
        hw = self.mem.read_halfword(ea)
        self.C = hw; self.D = sext(hw, 16)
        s = self.alu_sub(self.A, self.D)
        self.A = s; self.RR[r] = s
        self.set_cc_arith(self.A, self.carry, self.CC2)

    def _CH(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'halfword')
        self.A = self.RR[r]
        hw = self.mem.read_halfword(ea)
        self.C = hw; self.D = sext(hw, 16)
        s = self.alu_sub(self.A, self.D)
        self.A = s
        self.set_cc_compare(self.RR[r], mask32(self.D))

    # ------------------------------------------------------------------
    # Halfword load / store
    # ------------------------------------------------------------------
    def _LH(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'halfword')
        hw = self.mem.read_halfword(ea)
        self.C = hw; self.A = sext(hw, 16)
        self.RR[r] = self.A
        self.set_cc_arith(self.A)

    def _STH(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'halfword')
        self.A = self.RR[r]
        self.mem.write_halfword(ea, self.A & HALF_MASK)

    def _LCH(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'halfword')
        hw = self.mem.read_halfword(ea)
        self.C = hw; self.D = sext(hw, 16)
        s = self.alu_add(mask32(~self.D), 0, 1)
        self.A = s; self.RR[r] = s
        self.set_cc_complement(self.A, self.carry, self.CC2)

    def _LAH(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'halfword')
        hw = self.mem.read_halfword(ea)
        self.C = hw; self.D = sext(hw, 16)
        if self.D & 0x80000000:
            s = self.alu_add(mask32(~self.D), 0, 1)
        else:
            s = self.D
        self.A = s; self.RR[r] = s
        self.set_cc_abs(self.A, self.CC2)

    def _MTH(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'halfword')
        hw = self.mem.read_halfword(ea)
        self.C = hw; self.A = sext(hw, 16)
        self.D = sext(self.R, 4)   # 4-bit R sign-extended → 16-bit increment
        s = self.alu_add(self.A, self.D)
        self.A = s
        self.mem.write_halfword(ea, s & HALF_MASK)
        self.set_cc_arith(self.A, self.carry, self.CC2)

    # ------------------------------------------------------------------
    # Byte load / store
    # ------------------------------------------------------------------
    def _LB(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'byte')
        b = self.mem.read_byte(ea)
        self.C = b; self.A = b   # zero extend
        self.RR[r] = self.A
        self.set_cc_byte(self.A)

    def _STB(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'byte')
        self.A = self.RR[r]
        self.mem.write_byte(ea, self.A & BYTE_MASK)

    def _CB(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'byte')
        self.A = self.RR[r] & BYTE_MASK   # low byte, zero extended
        b = self.mem.read_byte(ea)
        self.C = b; self.D = b
        s = self.alu_sub(self.A, self.D)
        self.A = s
        self.set_cc_compare(self.RR[r], self.D)

    def _MTB(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'byte')
        b = self.mem.read_byte(ea)
        self.C = b; self.A = b   # zero extend
        self.D = sext(self.R, 4)
        s = self.alu_add(self.A, self.D)
        self.A = s
        self.mem.write_byte(ea, s & BYTE_MASK)
        self.set_cc_byte(self.A)

    # ------------------------------------------------------------------
    # Logical
    # ------------------------------------------------------------------
    def _AND(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'word')
        self.A = self.RR[r]
        self.C = self.mem.read_word(ea); self.D = self.C
        s = mask32(self.A & self.D)
        self.A = s; self.RR[r] = s
        self.set_cc_arith(self.A)

    def _OR(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'word')
        self.A = self.RR[r]
        self.C = self.mem.read_word(ea); self.D = self.C
        s = mask32(self.A | self.D)
        self.A = s; self.RR[r] = s
        self.set_cc_arith(self.A)

    def _EOR(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'word')
        self.A = self.RR[r]
        self.C = self.mem.read_word(ea); self.D = self.C
        s = mask32(self.A ^ self.D)
        self.A = s; self.RR[r] = s
        self.set_cc_arith(self.A)

    # ------------------------------------------------------------------
    # Doubleword
    # ------------------------------------------------------------------
    def _LD(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'doubleword')
        lo = self.mem.read_word(ea + 4)
        self.C = lo; self.A = lo
        self.RR[r+1] = lo; self.AWZ = (lo == 0)
        hi = self.mem.read_word(ea)
        self.C = hi; self.A = hi
        self.RR[r] = hi
        self.set_cc_arith_dw(self.A, self.AWZ)

    def _STD(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'doubleword')
        self.A = self.RR[r];   self.mem.write_word(ea,     self.A)
        self.A = self.RR[r+1]; self.mem.write_word(ea + 4, self.A)

    def _AD(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'doubleword')
        self.A = self.RR[r+1]
        self.C = self.mem.read_word(ea + 4); self.D = self.C
        lo_s = self.alu_add(self.A, self.D)
        self.A = lo_s; self.RR[r+1] = lo_s; self.AWZ = (lo_s == 0)
        lo_carry = self.carry
        self.A = self.RR[r]
        self.C = self.mem.read_word(ea); self.D = self.C
        hi_s = self.alu_add(self.A, self.D, lo_carry)
        self.A = hi_s; self.RR[r] = hi_s
        self.set_cc_arith_dw(self.A, self.AWZ, self.carry, self.CC2)

    def _SD(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'doubleword')
        self.A = self.RR[r+1]
        self.C = self.mem.read_word(ea + 4); self.D = self.C
        lo_s = self.alu_sub(self.A, self.D)
        self.A = lo_s; self.RR[r+1] = lo_s; self.AWZ = (lo_s == 0)
        lo_carry = self.carry   # 1 = no borrow, 0 = borrow
        self.A = self.RR[r]
        self.C = self.mem.read_word(ea); self.D = self.C
        hi_s = self.alu_add(self.A, mask32(~self.D), lo_carry)
        self.A = hi_s; self.RR[r] = hi_s
        self.set_cc_arith_dw(self.A, self.AWZ, self.carry, self.CC2)

    def _CD(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'doubleword')
        reg_hi = self.RR[r]; reg_lo = self.RR[r+1]
        op_hi  = self.mem.read_word(ea); op_lo = self.mem.read_word(ea + 4)
        self.A = self.RR[r+1]
        self.C = op_lo; self.D = self.C
        lo_s = self.alu_sub(self.A, self.D)
        self.A = lo_s; self.AWZ = (lo_s == 0)
        lo_carry = self.carry
        self.A = self.RR[r]
        self.C = op_hi; self.D = self.C
        hi_s = self.alu_add(self.A, mask32(~self.D), lo_carry)
        self.A = hi_s
        self.set_cc_compare_dw(reg_hi, reg_lo, op_hi, op_lo)

    def _LCD(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'doubleword')
        self.C = self.mem.read_word(ea + 4); self.D = self.C
        lo_s = self.alu_add(mask32(~self.D), 0, 1)
        self.A = lo_s; self.RR[r+1] = lo_s; self.AWZ = (lo_s == 0)
        lo_carry = self.carry
        self.C = self.mem.read_word(ea); self.D = self.C
        hi_s = self.alu_add(mask32(~self.D), 0, lo_carry)
        self.A = hi_s; self.RR[r] = hi_s
        self.set_cc_complement_dw(self.A, self.AWZ, self.carry, self.CC2)

    def _LAD(self, i, r, x, addr):
        ea = self._prep(i, x, addr, 'doubleword')
        self.C = self.mem.read_word(ea); self.D = self.C
        if self.D & 0x80000000:   # negative → negate
            lo_mem = self.mem.read_word(ea + 4)
            self.C = lo_mem; self.D = lo_mem
            lo_s = self.alu_add(mask32(~self.D), 0, 1)
            self.A = lo_s; self.RR[r+1] = lo_s; self.AWZ = (lo_s == 0)
            lo_carry = self.carry
            hi_mem = self.mem.read_word(ea)
            self.C = hi_mem; self.D = hi_mem
            hi_s = self.alu_add(mask32(~self.D), 0, lo_carry)
            self.A = hi_s; self.RR[r] = hi_s
        else:                     # positive → load directly
            lo_mem = self.mem.read_word(ea + 4)
            self.C = lo_mem; self.A = lo_mem
            self.RR[r+1] = lo_mem; self.AWZ = (lo_mem == 0)
            hi_mem = self.mem.read_word(ea)
            self.C = hi_mem; self.A = hi_mem
            self.RR[r] = hi_mem
        self.set_cc_abs_dw(self.A, self.AWZ, self.CC2)


# ---------------------------------------------------------------------------
# Test framework
# ---------------------------------------------------------------------------
class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures = []

    def check(self, name, got, expected):
        if got == expected:
            self.passed += 1
        else:
            self.failed += 1
            self.failures.append(f"FAIL  {name}: got 0x{got:08X}, expected 0x{expected:08X}")

    def check_bool(self, name, got, expected):
        if bool(got) == bool(expected):
            self.passed += 1
        else:
            self.failed += 1
            self.failures.append(f"FAIL  {name}: got {bool(got)}, expected {bool(expected)}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"Results: {self.passed}/{total} passed, {self.failed} failed")
        if self.failures:
            print()
            for f in self.failures:
                print(f)
        print('='*60)


def make_cpu():
    """Return a fresh CPU + runner for each test group."""
    return Sigma7CPU(), TestRunner()


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------
def word_addr(byte_addr):
    """Convert byte address to 17-bit word index for instruction encoding."""
    return (byte_addr >> 2) & 0x1FFFF


# ---------------------------------------------------------------------------
# CC helpers for tests
# ---------------------------------------------------------------------------
def cc_zero(cpu):   return not cpu.CC3 and not cpu.CC4
def cc_pos(cpu):    return cpu.CC3 and not cpu.CC4
def cc_neg(cpu):    return cpu.CC4
def cc_equal(cpu):  return not cpu.CC3 and not cpu.CC4  # compare equal
def cc_gt(cpu):     return cpu.CC3                       # compare greater
def cc_lt(cpu):     return cpu.CC4                       # compare less


# ---------------------------------------------------------------------------
# Tests: Word Arithmetic
# ---------------------------------------------------------------------------
def test_word_arithmetic(tr):
    cpu = Sigma7CPU()
    C = Sigma7CPU

    # --- AW ---
    cpu.mem.write_word(0x1000, 0x00000005)
    cpu.RR[2] = 0x00000003
    cpu.execute(C.encode(C.OP_AW, r=2, addr=word_addr(0x1000)))
    tr.check("AW basic",          cpu.RR[2],  0x00000008)
    tr.check_bool("AW CC3 pos",   cc_pos(cpu),   True)
    tr.check_bool("AW CC4=F",     cc_neg(cpu),   False)

    cpu.mem.write_word(0x1000, mask32(-3))
    cpu.RR[2] = 0x00000003
    cpu.execute(C.encode(C.OP_AW, r=2, addr=word_addr(0x1000)))
    tr.check("AW zero",           cpu.RR[2],  0x00000000)
    tr.check_bool("AW zero CC",   cc_zero(cpu),  True)

    cpu.mem.write_word(0x1000, mask32(-10))
    cpu.RR[2] = 0x00000003
    cpu.execute(C.encode(C.OP_AW, r=2, addr=word_addr(0x1000)))
    tr.check("AW negative",       cpu.RR[2],  mask32(-7))
    tr.check_bool("AW CC4 neg",   cc_neg(cpu),   True)
    tr.check_bool("AW CC3=F",     cc_pos(cpu),   False)

    # AW carry
    cpu.mem.write_word(0x1000, 0x00000001)
    cpu.RR[2] = 0xFFFFFFFF
    cpu.execute(C.encode(C.OP_AW, r=2, addr=word_addr(0x1000)))
    tr.check_bool("AW CC1 carry", cpu.CC1,       True)
    tr.check_bool("AW carry zero",cc_zero(cpu),  True)

    # --- SW ---
    cpu.mem.write_word(0x1000, 0x00000003)
    cpu.RR[2] = 0x00000008
    cpu.execute(C.encode(C.OP_SW, r=2, addr=word_addr(0x1000)))
    tr.check("SW basic",          cpu.RR[2],  0x00000005)
    tr.check_bool("SW CC3 pos",   cc_pos(cpu),   True)

    cpu.mem.write_word(0x1000, 0x00000005)
    cpu.RR[2] = 0x00000005
    cpu.execute(C.encode(C.OP_SW, r=2, addr=word_addr(0x1000)))
    tr.check("SW zero",           cpu.RR[2],  0x00000000)
    tr.check_bool("SW zero CC",   cc_zero(cpu),  True)

    # --- CW ---
    cpu.mem.write_word(0x1000, 0x00000005)
    cpu.RR[2] = 0x00000005
    cpu.execute(C.encode(C.OP_CW, r=2, addr=word_addr(0x1000)))
    tr.check("CW no write",       cpu.RR[2],  0x00000005)
    tr.check_bool("CW equal",     cc_equal(cpu), True)
    tr.check_bool("CW CC2 bits",  cpu.CC2,       True)  # 5 AND 5 = 5 ≠ 0

    cpu.mem.write_word(0x1000, 0x0000000A)
    cpu.RR[2] = 0x00000003
    cpu.execute(C.encode(C.OP_CW, r=2, addr=word_addr(0x1000)))
    tr.check_bool("CW less CC4",  cc_lt(cpu),    True)
    tr.check("CW no write2",      cpu.RR[2],  0x00000003)

    cpu.mem.write_word(0x1000, 0x00000003)
    cpu.RR[2] = 0x0000000A
    cpu.execute(C.encode(C.OP_CW, r=2, addr=word_addr(0x1000)))
    tr.check_bool("CW greater CC3", cc_gt(cpu),  True)

    # --- AI ---
    cpu.RR[3] = 0x00000010
    cpu.execute(C.encode_imm(C.OP_AI, r=3, imm=5))
    tr.check("AI pos",            cpu.RR[3],  0x00000015)
    tr.check_bool("AI CC3",       cc_pos(cpu),   True)

    cpu.RR[3] = 0x00000010
    cpu.execute(C.encode_imm(C.OP_AI, r=3, imm=-3))
    tr.check("AI neg imm",        cpu.RR[3],  0x0000000D)

    # --- CI ---
    cpu.RR[3] = 0x00000005
    cpu.execute(C.encode_imm(C.OP_CI, r=3, imm=5))
    tr.check_bool("CI equal",     cc_equal(cpu), True)
    tr.check("CI no write",       cpu.RR[3],  0x00000005)

    cpu.RR[3] = 0x00000003
    cpu.execute(C.encode_imm(C.OP_CI, r=3, imm=5))
    tr.check_bool("CI less CC4",  cc_lt(cpu),    True)

    cpu.RR[3] = 0x0000000A
    cpu.execute(C.encode_imm(C.OP_CI, r=3, imm=5))
    tr.check_bool("CI greater CC3", cc_gt(cpu),  True)

    # --- LI ---
    cpu.execute(C.encode_imm(C.OP_LI, r=4, imm=42))
    tr.check("LI pos",            cpu.RR[4],  42)
    tr.check_bool("LI CC3",       cc_pos(cpu),   True)

    cpu.execute(C.encode_imm(C.OP_LI, r=4, imm=-1))
    tr.check("LI neg",            cpu.RR[4],  mask32(-1))
    tr.check_bool("LI CC4",       cc_neg(cpu),   True)

    cpu.execute(C.encode_imm(C.OP_LI, r=4, imm=0))
    tr.check_bool("LI zero CC",   cc_zero(cpu),  True)


# ---------------------------------------------------------------------------
# Tests: Word Load / Store
# ---------------------------------------------------------------------------
def test_word_load_store(tr):
    cpu = Sigma7CPU()
    C = Sigma7CPU

    # --- LW ---
    cpu.mem.write_word(0x2000, 0xDEADBEEF)
    cpu.execute(C.encode(C.OP_LW, r=1, addr=word_addr(0x2000)))
    tr.check("LW direct",         cpu.RR[1],  0xDEADBEEF)
    tr.check_bool("LW CC4 neg",   cc_neg(cpu),   True)

    cpu.mem.write_word(0x2000, 0x00000000)
    cpu.execute(C.encode(C.OP_LW, r=1, addr=word_addr(0x2000)))
    tr.check_bool("LW zero CC",   cc_zero(cpu),  True)

    cpu.mem.write_word(0x2000, 0x00000001)
    cpu.execute(C.encode(C.OP_LW, r=1, addr=word_addr(0x2000)))
    tr.check_bool("LW CC3 pos",   cc_pos(cpu),   True)

    # LW indexed
    cpu.mem.write_word(0x2010, 0x12345678)
    cpu.RR[3] = 2
    cpu.execute(C.encode(C.OP_LW, r=1, x=3, addr=word_addr(0x2008)))
    tr.check("LW indexed",        cpu.RR[1],  0x12345678)

    # LW indirect
    cpu.mem.write_word(0x3000, word_addr(0x2000))
    cpu.mem.write_word(0x2000, 0xCAFEBABE)
    cpu.execute(C.encode(C.OP_LW, r=1, addr=word_addr(0x3000), i=1))
    tr.check("LW indirect",       cpu.RR[1],  0xCAFEBABE)

    # --- STW ---
    cpu.RR[5] = 0xABCDEF01
    cpu.execute(C.encode(C.OP_STW, r=5, addr=word_addr(0x4000)))
    tr.check("STW",               cpu.mem.read_word(0x4000), 0xABCDEF01)

    # --- LCW ---
    cpu.mem.write_word(0x2000, 0x00000001)
    cpu.execute(C.encode(C.OP_LCW, r=2, addr=word_addr(0x2000)))
    tr.check("LCW pos→neg",       cpu.RR[2],  mask32(-1))
    tr.check_bool("LCW CC4",      cc_neg(cpu),   True)

    cpu.mem.write_word(0x2000, mask32(-5))
    cpu.execute(C.encode(C.OP_LCW, r=2, addr=word_addr(0x2000)))
    tr.check("LCW neg→pos",       cpu.RR[2],  0x00000005)
    tr.check_bool("LCW CC3",      cc_pos(cpu),   True)

    # LCW overflow: negate most-negative → overflow, CC2+CC4 set
    cpu.mem.write_word(0x2000, 0x80000000)
    cpu.execute(C.encode(C.OP_LCW, r=2, addr=word_addr(0x2000)))
    tr.check("LCW overflow val",  cpu.RR[2],  0x80000000)
    tr.check_bool("LCW OVF CC2",  cpu.CC2,       True)
    tr.check_bool("LCW OVF CC4",  cpu.CC4,       True)

    # --- LAW ---
    cpu.mem.write_word(0x2000, mask32(-7))
    cpu.execute(C.encode(C.OP_LAW, r=2, addr=word_addr(0x2000)))
    tr.check("LAW neg→pos",       cpu.RR[2],  0x00000007)
    tr.check_bool("LAW CC3",      cc_pos(cpu),   True)
    tr.check_bool("LAW CC4=F",    cc_neg(cpu),   False)

    cpu.mem.write_word(0x2000, 0x00000007)
    cpu.execute(C.encode(C.OP_LAW, r=2, addr=word_addr(0x2000)))
    tr.check("LAW pos→pos",       cpu.RR[2],  0x00000007)

    cpu.mem.write_word(0x2000, 0x00000000)
    cpu.execute(C.encode(C.OP_LAW, r=2, addr=word_addr(0x2000)))
    tr.check_bool("LAW zero CC",  cc_zero(cpu),  True)

    # LAW overflow: most-negative value
    cpu.mem.write_word(0x2000, 0x80000000)
    cpu.execute(C.encode(C.OP_LAW, r=2, addr=word_addr(0x2000)))
    tr.check_bool("LAW OVF CC2",  cpu.CC2,       True)
    tr.check_bool("LAW OVF CC4",  cpu.CC4,       True)


# ---------------------------------------------------------------------------
# Tests: Halfword Arithmetic
# ---------------------------------------------------------------------------
def test_halfword_arithmetic(tr):
    cpu = Sigma7CPU()
    C = Sigma7CPU

    # --- AH ---
    cpu.mem.write_halfword(0x1000, 0x0005)
    cpu.RR[2] = 0x00000003
    cpu.execute(C.encode(C.OP_AH, r=2, addr=word_addr(0x1000)))
    tr.check("AH basic",          cpu.RR[2],  0x00000008)
    tr.check_bool("AH CC3",       cc_pos(cpu),   True)

    cpu.mem.write_halfword(0x1000, 0xFFFE)   # -2 in 16-bit
    cpu.RR[2] = 0x00000003
    cpu.execute(C.encode(C.OP_AH, r=2, addr=word_addr(0x1000)))
    tr.check("AH neg hw",         cpu.RR[2],  0x00000001)
    tr.check_bool("AH CC3 pos",   cc_pos(cpu),   True)

    # --- SH ---
    cpu.mem.write_halfword(0x1000, 0x0003)
    cpu.RR[2] = 0x00000008
    cpu.execute(C.encode(C.OP_SH, r=2, addr=word_addr(0x1000)))
    tr.check("SH basic",          cpu.RR[2],  0x00000005)

    # --- CH ---
    cpu.mem.write_halfword(0x1000, 0x0005)
    cpu.RR[2] = 0x00000005
    cpu.execute(C.encode(C.OP_CH, r=2, addr=word_addr(0x1000)))
    tr.check_bool("CH equal",     cc_equal(cpu), True)
    tr.check("CH no write",       cpu.RR[2],  0x00000005)

    cpu.mem.write_halfword(0x1000, 0x000A)
    cpu.RR[2] = 0x00000003
    cpu.execute(C.encode(C.OP_CH, r=2, addr=word_addr(0x1000)))
    tr.check_bool("CH less CC4",  cc_lt(cpu),    True)

    cpu.mem.write_halfword(0x1000, 0x0003)
    cpu.RR[2] = 0x0000000A
    cpu.execute(C.encode(C.OP_CH, r=2, addr=word_addr(0x1000)))
    tr.check_bool("CH greater CC3", cc_gt(cpu),  True)


# ---------------------------------------------------------------------------
# Tests: Halfword Load / Store
# ---------------------------------------------------------------------------
def test_halfword_load_store(tr):
    cpu = Sigma7CPU()
    C = Sigma7CPU

    # --- LH ---
    cpu.mem.write_halfword(0x1000, 0x7FFF)
    cpu.execute(C.encode(C.OP_LH, r=1, addr=word_addr(0x1000)))
    tr.check("LH pos",            cpu.RR[1],  0x00007FFF)
    tr.check_bool("LH CC3",       cc_pos(cpu),   True)

    cpu.mem.write_halfword(0x1000, 0x8000)
    cpu.execute(C.encode(C.OP_LH, r=1, addr=word_addr(0x1000)))
    tr.check("LH neg sext",       cpu.RR[1],  0xFFFF8000)
    tr.check_bool("LH CC4",       cc_neg(cpu),   True)

    # --- STH ---
    cpu.RR[5] = 0xABCD1234
    cpu.execute(C.encode(C.OP_STH, r=5, addr=word_addr(0x4000)))
    tr.check("STH low hw",        cpu.mem.read_halfword(0x4000), 0x1234)

    # --- LCH ---
    cpu.mem.write_halfword(0x1000, 0x0001)
    cpu.execute(C.encode(C.OP_LCH, r=2, addr=word_addr(0x1000)))
    tr.check("LCH pos→neg",       cpu.RR[2],  mask32(-1))
    tr.check_bool("LCH CC4",      cc_neg(cpu),   True)

    cpu.mem.write_halfword(0x1000, 0xFFFF)   # -1 in 16-bit
    cpu.execute(C.encode(C.OP_LCH, r=2, addr=word_addr(0x1000)))
    tr.check("LCH neg→pos",       cpu.RR[2],  0x00000001)
    tr.check_bool("LCH CC3",      cc_pos(cpu),   True)

    # LCH overflow: negate most-negative halfword
    cpu.mem.write_halfword(0x1000, 0x8000)
    cpu.execute(C.encode(C.OP_LCH, r=2, addr=word_addr(0x1000)))
    tr.check_bool("LCH OVF CC2",  cpu.CC2,       True)
    tr.check_bool("LCH OVF CC4",  cpu.CC4,       True)

    # --- LAH ---
    cpu.mem.write_halfword(0x1000, 0xFFFB)   # -5 in 16-bit
    cpu.execute(C.encode(C.OP_LAH, r=2, addr=word_addr(0x1000)))
    tr.check("LAH neg→pos",       cpu.RR[2],  0x00000005)
    tr.check_bool("LAH CC3",      cc_pos(cpu),   True)

    cpu.mem.write_halfword(0x1000, 0x0005)
    cpu.execute(C.encode(C.OP_LAH, r=2, addr=word_addr(0x1000)))
    tr.check("LAH pos→pos",       cpu.RR[2],  0x00000005)

    # --- MTH ---
    cpu.mem.write_halfword(0x1000, 0x000A)
    cpu.execute(C.encode(C.OP_MTH, r=2, addr=word_addr(0x1000)))
    tr.check("MTH +2",            cpu.mem.read_halfword(0x1000), 0x000C)
    tr.check_bool("MTH CC3",      cc_pos(cpu),   True)

    cpu.mem.write_halfword(0x1000, 0x000A)
    cpu.execute(C.encode(C.OP_MTH, r=0xF, addr=word_addr(0x1000)))
    tr.check("MTH -1",            cpu.mem.read_halfword(0x1000), 0x0009)


# ---------------------------------------------------------------------------
# Tests: Byte Load / Store
# ---------------------------------------------------------------------------
def test_byte_load_store(tr):
    cpu = Sigma7CPU()
    C = Sigma7CPU

    # --- LB: zero extend, CC4 never set ---
    cpu.mem.write_byte(0x1000, 0xFF)
    cpu.execute(C.encode(C.OP_LB, r=1, addr=word_addr(0x1000)))
    tr.check("LB 0xFF zero ext",  cpu.RR[1],  0x000000FF)
    tr.check_bool("LB CC4=F",     cpu.CC4,       False)   # never set for LB
    tr.check_bool("LB CC3 nz",    cpu.CC3,       True)    # non-zero

    cpu.mem.write_byte(0x1000, 0x00)
    cpu.execute(C.encode(C.OP_LB, r=1, addr=word_addr(0x1000)))
    tr.check_bool("LB zero CC3=F",cpu.CC3,       False)
    tr.check_bool("LB zero CC4=F",cpu.CC4,       False)

    cpu.mem.write_byte(0x1000, 0x41)
    cpu.execute(C.encode(C.OP_LB, r=1, addr=word_addr(0x1000)))
    tr.check("LB value",          cpu.RR[1],  0x00000041)

    # --- STB ---
    cpu.RR[5] = 0xABCD1234
    cpu.execute(C.encode(C.OP_STB, r=5, addr=word_addr(0x4000)))
    tr.check("STB low byte",      cpu.mem.read_byte(0x4000), 0x34)

    # --- CB: compare byte, compare CC encoding ---
    cpu.mem.write_byte(0x1000, 0x05)
    cpu.RR[2] = 0x00000005
    cpu.execute(C.encode(C.OP_CB, r=2, addr=word_addr(0x1000)))
    tr.check_bool("CB equal",     cc_equal(cpu), True)
    tr.check("CB no write",       cpu.RR[2],  0x00000005)

    cpu.mem.write_byte(0x1000, 0x0A)
    cpu.RR[2] = 0x00000003
    cpu.execute(C.encode(C.OP_CB, r=2, addr=word_addr(0x1000)))
    tr.check_bool("CB less CC4",  cc_lt(cpu),    True)

    cpu.mem.write_byte(0x1000, 0x03)
    cpu.RR[2] = 0x0000000A
    cpu.execute(C.encode(C.OP_CB, r=2, addr=word_addr(0x1000)))
    tr.check_bool("CB greater CC3", cc_gt(cpu),  True)

    # --- MTB: CC3 only, CC4 never set ---
    cpu.mem.write_byte(0x1000, 0x0A)
    cpu.execute(C.encode(C.OP_MTB, r=3, addr=word_addr(0x1000)))
    tr.check("MTB +3",            cpu.mem.read_byte(0x1000), 0x0D)
    tr.check_bool("MTB CC3 nz",   cpu.CC3,       True)
    tr.check_bool("MTB CC4=F",    cpu.CC4,       False)

    cpu.mem.write_byte(0x1000, 0x01)
    cpu.execute(C.encode(C.OP_MTB, r=0xF, addr=word_addr(0x1000)))
    tr.check("MTB -1",            cpu.mem.read_byte(0x1000), 0x00)
    tr.check_bool("MTB zero CC3=F", cpu.CC3,     False)
    tr.check_bool("MTB zero CC4=F", cpu.CC4,     False)


# ---------------------------------------------------------------------------
# Tests: Logical
# ---------------------------------------------------------------------------
def test_logical(tr):
    cpu = Sigma7CPU()
    C = Sigma7CPU

    # --- AND ---
    cpu.mem.write_word(0x1000, 0xFF00FF00)
    cpu.RR[2] = 0xFFFFFFFF
    cpu.execute(C.encode(C.OP_AND, r=2, addr=word_addr(0x1000)))
    tr.check("AND mask",          cpu.RR[2],  0xFF00FF00)
    tr.check_bool("AND CC4 neg",  cc_neg(cpu),   True)   # bit 0 set

    cpu.mem.write_word(0x1000, 0xFF00FF00)
    cpu.RR[2] = 0x00FF00FF
    cpu.execute(C.encode(C.OP_AND, r=2, addr=word_addr(0x1000)))
    tr.check("AND zero",          cpu.RR[2],  0x00000000)
    tr.check_bool("AND zero CC",  cc_zero(cpu),  True)

    cpu.mem.write_word(0x1000, 0x00000001)
    cpu.RR[2] = 0x00000001
    cpu.execute(C.encode(C.OP_AND, r=2, addr=word_addr(0x1000)))
    tr.check_bool("AND CC3 pos",  cc_pos(cpu),   True)

    # --- OR ---
    cpu.mem.write_word(0x1000, 0xFF000000)
    cpu.RR[2] = 0x00FFFFFF
    cpu.execute(C.encode(C.OP_OR, r=2, addr=word_addr(0x1000)))
    tr.check("OR full",           cpu.RR[2],  0xFFFFFFFF)
    tr.check_bool("OR CC4 neg",   cc_neg(cpu),   True)

    cpu.mem.write_word(0x1000, 0x00000000)
    cpu.RR[2] = 0x00000000
    cpu.execute(C.encode(C.OP_OR, r=2, addr=word_addr(0x1000)))
    tr.check_bool("OR zero CC",   cc_zero(cpu),  True)

    # --- EOR ---
    cpu.mem.write_word(0x1000, 0xFFFFFFFF)
    cpu.RR[2] = 0xFFFFFFFF
    cpu.execute(C.encode(C.OP_EOR, r=2, addr=word_addr(0x1000)))
    tr.check("EOR self→0",        cpu.RR[2],  0x00000000)
    tr.check_bool("EOR zero CC",  cc_zero(cpu),  True)

    cpu.mem.write_word(0x1000, 0xFFFFFFFF)
    cpu.RR[2] = 0x00000000
    cpu.execute(C.encode(C.OP_EOR, r=2, addr=word_addr(0x1000)))
    tr.check("EOR invert",        cpu.RR[2],  0xFFFFFFFF)
    tr.check_bool("EOR CC4 neg",  cc_neg(cpu),   True)


# ---------------------------------------------------------------------------
# Tests: Doubleword
# ---------------------------------------------------------------------------
def test_doubleword(tr):
    cpu = Sigma7CPU()
    C = Sigma7CPU

    BASE = 0x2000

    # --- LD ---
    cpu.mem.write_word(BASE,     0x00000001)
    cpu.mem.write_word(BASE + 4, 0x00000002)
    cpu.execute(C.encode(C.OP_LD, r=2, addr=word_addr(BASE)))
    tr.check("LD hi",             cpu.RR[2],  0x00000001)
    tr.check("LD lo",             cpu.RR[3],  0x00000002)
    tr.check_bool("LD CC3 pos",   cc_pos(cpu),   True)

    cpu.mem.write_word(BASE,     0x00000000)
    cpu.mem.write_word(BASE + 4, 0x00000000)
    cpu.execute(C.encode(C.OP_LD, r=2, addr=word_addr(BASE)))
    tr.check_bool("LD zero CC",   cc_zero(cpu),  True)
    tr.check_bool("LD AWZ",       cpu.AWZ,       True)

    cpu.mem.write_word(BASE,     0x80000000)
    cpu.mem.write_word(BASE + 4, 0x00000001)
    cpu.execute(C.encode(C.OP_LD, r=2, addr=word_addr(BASE)))
    tr.check_bool("LD CC4 neg",   cc_neg(cpu),   True)
    tr.check_bool("LD AWZ=F",     cpu.AWZ,       False)

    # AWZ set but high non-zero → CC3 (positive)
    cpu.mem.write_word(BASE,     0x00000001)
    cpu.mem.write_word(BASE + 4, 0x00000000)
    cpu.execute(C.encode(C.OP_LD, r=2, addr=word_addr(BASE)))
    tr.check_bool("LD AWZ+hi≠0 CC3", cc_pos(cpu), True)

    # --- STD ---
    cpu.RR[4] = 0xDEADBEEF
    cpu.RR[5] = 0xCAFEBABE
    cpu.execute(C.encode(C.OP_STD, r=4, addr=word_addr(BASE)))
    tr.check("STD hi",            cpu.mem.read_word(BASE),     0xDEADBEEF)
    tr.check("STD lo",            cpu.mem.read_word(BASE + 4), 0xCAFEBABE)

    # --- AD ---
    cpu.mem.write_word(BASE,     0x00000001)
    cpu.mem.write_word(BASE + 4, 0xFFFFFFFE)
    cpu.RR[2] = 0x00000000; cpu.RR[3] = 0x00000002
    cpu.execute(C.encode(C.OP_AD, r=2, addr=word_addr(BASE)))
    tr.check("AD lo wrap",        cpu.RR[3],  0x00000000)
    tr.check("AD hi+carry",       cpu.RR[2],  0x00000002)
    tr.check_bool("AD CC3 pos",   cc_pos(cpu),   True)

    cpu.mem.write_word(BASE,     mask32(-1))
    cpu.mem.write_word(BASE + 4, mask32(-1))
    cpu.RR[2] = 0x00000000; cpu.RR[3] = 0x00000001
    cpu.execute(C.encode(C.OP_AD, r=2, addr=word_addr(BASE)))
    tr.check_bool("AD 64b zero",  cc_zero(cpu),  True)

    # --- SD ---
    cpu.mem.write_word(BASE,     0x00000000)
    cpu.mem.write_word(BASE + 4, 0x00000001)
    cpu.RR[2] = 0x00000000; cpu.RR[3] = 0x00000003
    cpu.execute(C.encode(C.OP_SD, r=2, addr=word_addr(BASE)))
    tr.check("SD lo",             cpu.RR[3],  0x00000002)
    tr.check("SD hi",             cpu.RR[2],  0x00000000)

    cpu.mem.write_word(BASE,     0x00000000)
    cpu.mem.write_word(BASE + 4, 0x00000005)
    cpu.RR[2] = 0x00000001; cpu.RR[3] = 0x00000003
    cpu.execute(C.encode(C.OP_SD, r=2, addr=word_addr(BASE)))
    tr.check("SD borrow lo",      cpu.RR[3],  mask32(-2))
    tr.check("SD borrow hi",      cpu.RR[2],  0x00000000)

    # --- CD ---
    cpu.mem.write_word(BASE,     0x00000001)
    cpu.mem.write_word(BASE + 4, 0x00000002)
    cpu.RR[2] = 0x00000001; cpu.RR[3] = 0x00000002
    cpu.execute(C.encode(C.OP_CD, r=2, addr=word_addr(BASE)))
    tr.check_bool("CD equal",     cc_equal(cpu), True)
    tr.check("CD no write hi",    cpu.RR[2],  0x00000001)
    tr.check("CD no write lo",    cpu.RR[3],  0x00000002)

    cpu.mem.write_word(BASE,     0x00000000)
    cpu.mem.write_word(BASE + 4, 0x00000001)
    cpu.RR[2] = 0x00000000; cpu.RR[3] = 0x00000002
    cpu.execute(C.encode(C.OP_CD, r=2, addr=word_addr(BASE)))
    tr.check_bool("CD greater CC3", cc_gt(cpu),  True)

    cpu.mem.write_word(BASE,     0x00000000)
    cpu.mem.write_word(BASE + 4, 0x00000005)
    cpu.RR[2] = 0x00000000; cpu.RR[3] = 0x00000002
    cpu.execute(C.encode(C.OP_CD, r=2, addr=word_addr(BASE)))
    tr.check_bool("CD less CC4",  cc_lt(cpu),    True)

    # --- LCD ---
    cpu.mem.write_word(BASE,     0x00000000)
    cpu.mem.write_word(BASE + 4, 0x00000001)
    cpu.execute(C.encode(C.OP_LCD, r=2, addr=word_addr(BASE)))
    tr.check("LCD lo",            cpu.RR[3],  mask32(-1))
    tr.check("LCD hi",            cpu.RR[2],  mask32(-1))
    tr.check_bool("LCD CC4",      cc_neg(cpu),   True)

    cpu.mem.write_word(BASE,     0x00000000)
    cpu.mem.write_word(BASE + 4, 0x00000000)
    cpu.execute(C.encode(C.OP_LCD, r=2, addr=word_addr(BASE)))
    tr.check_bool("LCD zero CC",  cc_zero(cpu),  True)

    # LCD overflow: negate most-negative 64-bit value
    cpu.mem.write_word(BASE,     0x80000000)
    cpu.mem.write_word(BASE + 4, 0x00000000)
    cpu.execute(C.encode(C.OP_LCD, r=2, addr=word_addr(BASE)))
    tr.check_bool("LCD OVF CC2",  cpu.CC2,       True)
    tr.check_bool("LCD OVF CC4",  cpu.CC4,       True)

    # --- LAD ---
    cpu.mem.write_word(BASE,     mask32(-1))
    cpu.mem.write_word(BASE + 4, mask32(-1))
    cpu.execute(C.encode(C.OP_LAD, r=2, addr=word_addr(BASE)))
    tr.check("LAD neg hi",        cpu.RR[2],  0x00000000)
    tr.check("LAD neg lo",        cpu.RR[3],  0x00000001)
    tr.check_bool("LAD CC3",      cc_pos(cpu),   True)
    tr.check_bool("LAD CC4=F",    cc_neg(cpu),   False)

    cpu.mem.write_word(BASE,     0x00000000)
    cpu.mem.write_word(BASE + 4, 0x00000007)
    cpu.execute(C.encode(C.OP_LAD, r=2, addr=word_addr(BASE)))
    tr.check("LAD pos hi",        cpu.RR[2],  0x00000000)
    tr.check("LAD pos lo",        cpu.RR[3],  0x00000007)
    tr.check_bool("LAD pos CC3",  cc_pos(cpu),   True)


# ---------------------------------------------------------------------------
# Tests: Addressing modes (using LW as the vehicle)
# ---------------------------------------------------------------------------
def test_addressing_modes(tr):
    cpu = Sigma7CPU()
    C = Sigma7CPU

    cpu.mem.write_word(0x1000, 0x11111111)
    cpu.execute(C.encode(C.OP_LW, r=1, addr=word_addr(0x1000)))
    tr.check("Addr direct",       cpu.RR[1],  0x11111111)

    cpu.mem.write_word(0x1008, 0x22222222)
    cpu.RR[3] = 2
    cpu.execute(C.encode(C.OP_LW, r=1, x=3, addr=word_addr(0x1000)))
    tr.check("Addr indexed",      cpu.RR[1],  0x22222222)

    cpu.mem.write_word(0x2000, word_addr(0x1000))
    cpu.mem.write_word(0x1000, 0x33333333)
    cpu.execute(C.encode(C.OP_LW, r=1, addr=word_addr(0x2000), i=1))
    tr.check("Addr indirect",     cpu.RR[1],  0x33333333)

    cpu.mem.write_word(0x2000, word_addr(0x1000))
    cpu.mem.write_word(0x1004, 0x44444444)
    cpu.RR[3] = 1
    cpu.execute(C.encode(C.OP_LW, r=1, x=3, addr=word_addr(0x2000), i=1))
    tr.check("Addr indir+idx",    cpu.RR[1],  0x44444444)



def test_word_arithmetic(tr):
    cpu = Sigma7CPU()
    C = Sigma7CPU

    # --- AW: basic add ---
    cpu.mem.write_word(0x1000, 0x00000005)
    cpu.RR[2] = 0x00000003
    cpu.execute(C.encode(C.OP_AW, r=2, addr=word_addr(0x1000)))
    tr.check("AW basic",        cpu.RR[2],  0x00000008)
    tr.check_bool("AW CC_Z=F",  cpu.CC3 == False and cpu.CC4 == False,   False)
    tr.check_bool("AW CC_N=F",  cpu.CC4,   False)

    # AW: result zero
    cpu.mem.write_word(0x1000, mask32(-3))
    cpu.RR[2] = 0x00000003
    cpu.execute(C.encode(C.OP_AW, r=2, addr=word_addr(0x1000)))
    tr.check("AW zero",         cpu.RR[2],  0x00000000)
    tr.check_bool("AW CC_Z=T",  cpu.CC3 == False and cpu.CC4 == False,   True)

    # AW: negative result
    cpu.mem.write_word(0x1000, mask32(-10))
    cpu.RR[2] = 0x00000003
    cpu.execute(C.encode(C.OP_AW, r=2, addr=word_addr(0x1000)))
    tr.check("AW negative",     cpu.RR[2],  mask32(-7))
    tr.check_bool("AW CC_N=T",  cpu.CC4,   True)

    # --- SW: basic subtract ---
    cpu.mem.write_word(0x1000, 0x00000003)
    cpu.RR[2] = 0x00000008
    cpu.execute(C.encode(C.OP_SW, r=2, addr=word_addr(0x1000)))
    tr.check("SW basic",        cpu.RR[2],  0x00000005)

    # SW: subtract to zero
    cpu.mem.write_word(0x1000, 0x00000005)
    cpu.RR[2] = 0x00000005
    cpu.execute(C.encode(C.OP_SW, r=2, addr=word_addr(0x1000)))
    tr.check("SW zero",         cpu.RR[2],  0x00000000)
    tr.check_bool("SW CC_Z=T",  cpu.CC3 == False and cpu.CC4 == False,   True)

    # --- CW: compare equal (CC_Z) ---
    cpu.mem.write_word(0x1000, 0x00000005)
    cpu.RR[2] = 0x00000005
    cpu.execute(C.encode(C.OP_CW, r=2, addr=word_addr(0x1000)))
    tr.check("CW no write",     cpu.RR[2],  0x00000005)   # result not written back
    tr.check_bool("CW CC_Z=T",  cpu.CC3 == False and cpu.CC4 == False,   True)

    # CW: reg < mem → negative
    cpu.mem.write_word(0x1000, 0x0000000A)
    cpu.RR[2] = 0x00000003
    cpu.execute(C.encode(C.OP_CW, r=2, addr=word_addr(0x1000)))
    tr.check_bool("CW CC_N=T",  cpu.CC4,   True)
    tr.check("CW no write2",    cpu.RR[2],  0x00000003)

    # --- AI: add immediate positive ---
    cpu.RR[3] = 0x00000010
    cpu.execute(C.encode_imm(C.OP_AI, r=3, imm=5))
    tr.check("AI pos",          cpu.RR[3],  0x00000015)

    # AI: add negative immediate
    cpu.RR[3] = 0x00000010
    cpu.execute(C.encode_imm(C.OP_AI, r=3, imm=-3))
    tr.check("AI neg imm",      cpu.RR[3],  0x0000000D)

    # --- CI: compare immediate ---
    cpu.RR[3] = 0x00000005
    cpu.execute(C.encode_imm(C.OP_CI, r=3, imm=5))
    tr.check_bool("CI equal Z", cpu.CC3 == False and cpu.CC4 == False,   True)
    tr.check("CI no write",     cpu.RR[3],  0x00000005)

    cpu.RR[3] = 0x00000003
    cpu.execute(C.encode_imm(C.OP_CI, r=3, imm=5))
    tr.check_bool("CI less N",  cpu.CC4,   True)

    # --- LI: load immediate ---
    cpu.execute(C.encode_imm(C.OP_LI, r=4, imm=42))
    tr.check("LI pos",          cpu.RR[4],  42)

    cpu.execute(C.encode_imm(C.OP_LI, r=4, imm=-1))
    tr.check("LI neg",          cpu.RR[4],  mask32(-1))
    tr.check_bool("LI CC_N",    cpu.CC4,   True)

    cpu.execute(C.encode_imm(C.OP_LI, r=4, imm=0))
    tr.check_bool("LI zero Z",  cpu.CC3 == False and cpu.CC4 == False,   True)


# ---------------------------------------------------------------------------
# Tests: Word Load / Store
# ---------------------------------------------------------------------------
def test_word_load_store(tr):
    cpu = Sigma7CPU()
    C = Sigma7CPU

    # --- LW: direct ---
    cpu.mem.write_word(0x2000, 0xDEADBEEF)
    cpu.execute(C.encode(C.OP_LW, r=1, addr=word_addr(0x2000)))
    tr.check("LW direct",       cpu.RR[1],  0xDEADBEEF)
    tr.check_bool("LW CC_N",    cpu.CC4,   True)   # 0xDEADBEEF has bit 0 set

    # LW: zero value
    cpu.mem.write_word(0x2000, 0x00000000)
    cpu.execute(C.encode(C.OP_LW, r=1, addr=word_addr(0x2000)))
    tr.check_bool("LW CC_Z",    cpu.CC3 == False and cpu.CC4 == False,   True)

    # LW: indexed (word index)
    cpu.mem.write_word(0x2010, 0x12345678)   # byte 0x2010 = word index 0x804, offset 2 from base
    cpu.RR[3] = 2                             # index register = 2 (word units)
    cpu.execute(C.encode(C.OP_LW, r=1, x=3, addr=word_addr(0x2008)))
    tr.check("LW indexed",      cpu.RR[1],  0x12345678)

    # LW: indirect
    cpu.mem.write_word(0x3000, word_addr(0x2000))   # pointer at 0x3000 → word index of 0x2000
    cpu.mem.write_word(0x2000, 0xCAFEBABE)
    cpu.execute(C.encode(C.OP_LW, r=1, addr=word_addr(0x3000), i=1))
    tr.check("LW indirect",     cpu.RR[1],  0xCAFEBABE)

    # --- STW: store ---
    cpu.RR[5] = 0xABCDEF01
    cpu.execute(C.encode(C.OP_STW, r=5, addr=word_addr(0x4000)))
    tr.check("STW",             cpu.mem.read_word(0x4000), 0xABCDEF01)

    # --- LCW: load complemented ---
    cpu.mem.write_word(0x2000, 0x00000001)
    cpu.execute(C.encode(C.OP_LCW, r=2, addr=word_addr(0x2000)))
    tr.check("LCW pos",         cpu.RR[2],  mask32(-1))
    tr.check_bool("LCW CC_N",   cpu.CC4,   True)

    cpu.mem.write_word(0x2000, mask32(-5))
    cpu.execute(C.encode(C.OP_LCW, r=2, addr=word_addr(0x2000)))
    tr.check("LCW neg",         cpu.RR[2],  0x00000005)

    # --- LAW: load absolute ---
    cpu.mem.write_word(0x2000, mask32(-7))
    cpu.execute(C.encode(C.OP_LAW, r=2, addr=word_addr(0x2000)))
    tr.check("LAW neg→pos",     cpu.RR[2],  0x00000007)
    tr.check_bool("LAW CC_N=F", cpu.CC4,   False)

    cpu.mem.write_word(0x2000, 0x00000007)
    cpu.execute(C.encode(C.OP_LAW, r=2, addr=word_addr(0x2000)))
    tr.check("LAW pos→pos",     cpu.RR[2],  0x00000007)

    cpu.mem.write_word(0x2000, 0x00000000)
    cpu.execute(C.encode(C.OP_LAW, r=2, addr=word_addr(0x2000)))
    tr.check_bool("LAW zero Z", cpu.CC3 == False and cpu.CC4 == False,   True)


# ---------------------------------------------------------------------------
# Tests: Halfword Arithmetic
# ---------------------------------------------------------------------------
def test_halfword_arithmetic(tr):
    cpu = Sigma7CPU()
    C = Sigma7CPU

    # --- AH: add halfword (sign-extended) ---
    cpu.mem.write_halfword(0x1000, 0x0005)
    cpu.RR[2] = 0x00000003
    cpu.execute(C.encode(C.OP_AH, r=2, addr=word_addr(0x1000)))
    tr.check("AH basic",        cpu.RR[2],  0x00000008)

    # AH: negative halfword sign-extended
    cpu.mem.write_halfword(0x1000, 0xFFFE)   # -2 in 16-bit
    cpu.RR[2] = 0x00000003
    cpu.execute(C.encode(C.OP_AH, r=2, addr=word_addr(0x1000)))
    tr.check("AH neg hw",       cpu.RR[2],  0x00000001)   # 3 + (-2) = 1

    # --- SH: subtract halfword ---
    cpu.mem.write_halfword(0x1000, 0x0003)
    cpu.RR[2] = 0x00000008
    cpu.execute(C.encode(C.OP_SH, r=2, addr=word_addr(0x1000)))
    tr.check("SH basic",        cpu.RR[2],  0x00000005)

    # --- CH: compare halfword ---
    cpu.mem.write_halfword(0x1000, 0x0005)
    cpu.RR[2] = 0x00000005
    cpu.execute(C.encode(C.OP_CH, r=2, addr=word_addr(0x1000)))
    tr.check_bool("CH equal Z", cpu.CC3 == False and cpu.CC4 == False,   True)
    tr.check("CH no write",     cpu.RR[2],  0x00000005)

    cpu.mem.write_halfword(0x1000, 0x000A)
    cpu.RR[2] = 0x00000003
    cpu.execute(C.encode(C.OP_CH, r=2, addr=word_addr(0x1000)))
    tr.check_bool("CH less N",  cpu.CC4,   True)


# ---------------------------------------------------------------------------
# Tests: Halfword Load / Store
# ---------------------------------------------------------------------------
def test_halfword_load_store(tr):
    cpu = Sigma7CPU()
    C = Sigma7CPU

    # --- LH: sign extension ---
    cpu.mem.write_halfword(0x1000, 0x7FFF)   # max positive
    cpu.execute(C.encode(C.OP_LH, r=1, addr=word_addr(0x1000)))
    tr.check("LH pos",          cpu.RR[1],  0x00007FFF)
    tr.check_bool("LH CC_N=F",  cpu.CC4,   False)

    cpu.mem.write_halfword(0x1000, 0x8000)   # min negative
    cpu.execute(C.encode(C.OP_LH, r=1, addr=word_addr(0x1000)))
    tr.check("LH neg sext",     cpu.RR[1],  0xFFFF8000)
    tr.check_bool("LH CC_N=T",  cpu.CC4,   True)

    # --- STH: store low halfword ---
    cpu.RR[5] = 0xABCD1234
    cpu.execute(C.encode(C.OP_STH, r=5, addr=word_addr(0x4000)))
    tr.check("STH low hw",      cpu.mem.read_halfword(0x4000), 0x1234)

    # --- LCH: load complemented halfword ---
    cpu.mem.write_halfword(0x1000, 0x0001)
    cpu.execute(C.encode(C.OP_LCH, r=2, addr=word_addr(0x1000)))
    tr.check("LCH pos→neg",     cpu.RR[2],  mask32(-1))

    cpu.mem.write_halfword(0x1000, 0xFFFF)   # -1 in 16-bit
    cpu.execute(C.encode(C.OP_LCH, r=2, addr=word_addr(0x1000)))
    tr.check("LCH neg→pos",     cpu.RR[2],  0x00000001)

    # --- LAH: load absolute halfword ---
    cpu.mem.write_halfword(0x1000, 0xFFFB)   # -5 in 16-bit
    cpu.execute(C.encode(C.OP_LAH, r=2, addr=word_addr(0x1000)))
    tr.check("LAH neg→pos",     cpu.RR[2],  0x00000005)

    cpu.mem.write_halfword(0x1000, 0x0005)
    cpu.execute(C.encode(C.OP_LAH, r=2, addr=word_addr(0x1000)))
    tr.check("LAH pos→pos",     cpu.RR[2],  0x00000005)

    # --- MTH: modify and test halfword ---
    cpu.mem.write_halfword(0x1000, 0x000A)   # value = 10
    cpu.execute(C.encode(C.OP_MTH, r=2, addr=word_addr(0x1000)))   # R=2 → +2 increment
    tr.check("MTH +2",          cpu.mem.read_halfword(0x1000), 0x000C)

    cpu.mem.write_halfword(0x1000, 0x000A)
    cpu.execute(C.encode(C.OP_MTH, r=0xF, addr=word_addr(0x1000)))  # R=0xF → -1 increment
    tr.check("MTH -1",          cpu.mem.read_halfword(0x1000), 0x0009)


# ---------------------------------------------------------------------------
# Tests: Byte Load / Store
# ---------------------------------------------------------------------------
def test_byte_load_store(tr):
    cpu = Sigma7CPU()
    C = Sigma7CPU

    # --- LB: zero extend (no sign extension) ---
    cpu.mem.write_byte(0x1000, 0xFF)
    cpu.execute(C.encode(C.OP_LB, r=1, addr=word_addr(0x1000)))
    tr.check("LB 0xFF zero ext", cpu.RR[1], 0x000000FF)   # upper 24 bits = 0
    tr.check_bool("LB CC_N=F",   cpu.CC4,  False)        # zero extended, not negative

    cpu.mem.write_byte(0x1000, 0x00)
    cpu.execute(C.encode(C.OP_LB, r=1, addr=word_addr(0x1000)))
    tr.check_bool("LB zero Z",   cpu.CC3 == False and cpu.CC4 == False,  True)

    cpu.mem.write_byte(0x1000, 0x41)
    cpu.execute(C.encode(C.OP_LB, r=1, addr=word_addr(0x1000)))
    tr.check("LB value",         cpu.RR[1], 0x00000041)

    # --- STB: store low byte ---
    cpu.RR[5] = 0xABCD1234
    cpu.execute(C.encode(C.OP_STB, r=5, addr=word_addr(0x4000)))
    tr.check("STB low byte",     cpu.mem.read_byte(0x4000), 0x34)

    # --- CB: compare byte (zero extended) ---
    cpu.mem.write_byte(0x1000, 0x05)
    cpu.RR[2] = 0x00000005
    cpu.execute(C.encode(C.OP_CB, r=2, addr=word_addr(0x1000)))
    tr.check_bool("CB equal Z",  cpu.CC3 == False and cpu.CC4 == False,  True)
    tr.check("CB no write",      cpu.RR[2], 0x00000005)

    cpu.mem.write_byte(0x1000, 0x0A)
    cpu.RR[2] = 0x00000003
    cpu.execute(C.encode(C.OP_CB, r=2, addr=word_addr(0x1000)))
    tr.check_bool("CB less N",   cpu.CC4,  True)

    # --- MTB: modify and test byte ---
    cpu.mem.write_byte(0x1000, 0x0A)
    cpu.execute(C.encode(C.OP_MTB, r=3, addr=word_addr(0x1000)))    # R=3 → +3 increment
    tr.check("MTB +3",           cpu.mem.read_byte(0x1000), 0x0D)

    cpu.mem.write_byte(0x1000, 0x01)
    cpu.execute(C.encode(C.OP_MTB, r=0xF, addr=word_addr(0x1000)))  # R=0xF → -1 increment
    tr.check("MTB -1",           cpu.mem.read_byte(0x1000), 0x00)
    tr.check_bool("MTB zero Z",  cpu.CC3 == False and cpu.CC4 == False,  True)


# ---------------------------------------------------------------------------
# Tests: Logical
# ---------------------------------------------------------------------------
def test_logical(tr):
    cpu = Sigma7CPU()
    C = Sigma7CPU

    # --- AND ---
    cpu.mem.write_word(0x1000, 0xFF00FF00)
    cpu.RR[2] = 0xFFFFFFFF
    cpu.execute(C.encode(C.OP_AND, r=2, addr=word_addr(0x1000)))
    tr.check("AND mask",         cpu.RR[2], 0xFF00FF00)

    cpu.mem.write_word(0x1000, 0xFF00FF00)
    cpu.RR[2] = 0x00FF00FF
    cpu.execute(C.encode(C.OP_AND, r=2, addr=word_addr(0x1000)))
    tr.check("AND zero",         cpu.RR[2], 0x00000000)
    tr.check_bool("AND CC_Z",    cpu.CC3 == False and cpu.CC4 == False,  True)

    # --- OR ---
    cpu.mem.write_word(0x1000, 0xFF000000)
    cpu.RR[2] = 0x00FFFFFF
    cpu.execute(C.encode(C.OP_OR, r=2, addr=word_addr(0x1000)))
    tr.check("OR full",          cpu.RR[2], 0xFFFFFFFF)
    tr.check_bool("OR CC_N",     cpu.CC4,  True)

    cpu.mem.write_word(0x1000, 0x00000000)
    cpu.RR[2] = 0x00000000
    cpu.execute(C.encode(C.OP_OR, r=2, addr=word_addr(0x1000)))
    tr.check_bool("OR zero Z",   cpu.CC3 == False and cpu.CC4 == False,  True)

    # --- EOR ---
    cpu.mem.write_word(0x1000, 0xFFFFFFFF)
    cpu.RR[2] = 0xFFFFFFFF
    cpu.execute(C.encode(C.OP_EOR, r=2, addr=word_addr(0x1000)))
    tr.check("EOR self→0",       cpu.RR[2], 0x00000000)
    tr.check_bool("EOR CC_Z",    cpu.CC3 == False and cpu.CC4 == False,  True)

    cpu.mem.write_word(0x1000, 0xFFFFFFFF)
    cpu.RR[2] = 0x00000000
    cpu.execute(C.encode(C.OP_EOR, r=2, addr=word_addr(0x1000)))
    tr.check("EOR invert",       cpu.RR[2], 0xFFFFFFFF)


# ---------------------------------------------------------------------------
# Tests: Doubleword
# ---------------------------------------------------------------------------
def test_doubleword(tr):
    cpu = Sigma7CPU()
    C = Sigma7CPU

    BASE = 0x2000   # doubleword-aligned

    # --- LD: load doubleword ---
    cpu.mem.write_word(BASE,     0x00000001)   # high
    cpu.mem.write_word(BASE + 4, 0x00000002)   # low
    cpu.execute(C.encode(C.OP_LD, r=2, addr=word_addr(BASE)))
    tr.check("LD hi",            cpu.RR[2],    0x00000001)
    tr.check("LD lo",            cpu.RR[3],    0x00000002)
    tr.check_bool("LD CC_Z=F",   cpu.CC3 == False and cpu.CC4 == False,     False)

    # LD: zero value
    cpu.mem.write_word(BASE,     0x00000000)
    cpu.mem.write_word(BASE + 4, 0x00000000)
    cpu.execute(C.encode(C.OP_LD, r=2, addr=word_addr(BASE)))
    tr.check_bool("LD zero Z",   cpu.CC3 == False and cpu.CC4 == False,     True)
    tr.check_bool("LD AWZ",      cpu.AWZ,      True)

    # LD: negative (high word MSB set)
    cpu.mem.write_word(BASE,     0x80000000)
    cpu.mem.write_word(BASE + 4, 0x00000001)
    cpu.execute(C.encode(C.OP_LD, r=2, addr=word_addr(BASE)))
    tr.check_bool("LD CC_N",     cpu.CC4,     True)
    tr.check_bool("LD AWZ=F",    cpu.AWZ,      False)

    # LD: AWZ set, high non-zero → not zero
    cpu.mem.write_word(BASE,     0x00000001)
    cpu.mem.write_word(BASE + 4, 0x00000000)
    cpu.execute(C.encode(C.OP_LD, r=2, addr=word_addr(BASE)))
    tr.check_bool("LD AWZ+hi≠0", cpu.CC3 == False and cpu.CC4 == False,     False)

    # --- STD: store doubleword ---
    cpu.RR[4] = 0xDEADBEEF
    cpu.RR[5] = 0xCAFEBABE
    cpu.execute(C.encode(C.OP_STD, r=4, addr=word_addr(BASE)))
    tr.check("STD hi",           cpu.mem.read_word(BASE),     0xDEADBEEF)
    tr.check("STD lo",           cpu.mem.read_word(BASE + 4), 0xCAFEBABE)

    # --- AD: add doubleword ---
    cpu.mem.write_word(BASE,     0x00000001)
    cpu.mem.write_word(BASE + 4, 0xFFFFFFFE)
    cpu.RR[2] = 0x00000000; cpu.RR[3] = 0x00000002
    cpu.execute(C.encode(C.OP_AD, r=2, addr=word_addr(BASE)))
    tr.check("AD lo",            cpu.RR[3],    0x00000000)   # 2 + 0xFFFFFFFE wraps
    tr.check("AD hi+carry",      cpu.RR[2],    0x00000002)   # 0 + 1 + carry(1) = 2

    # AD: zero result
    cpu.mem.write_word(BASE,     mask32(-1))
    cpu.mem.write_word(BASE + 4, mask32(-1))  # -1 as 64-bit
    cpu.RR[2] = 0x00000000; cpu.RR[3] = 0x00000001
    cpu.execute(C.encode(C.OP_AD, r=2, addr=word_addr(BASE)))
    tr.check_bool("AD 64b zero Z", cpu.CC3 == False and cpu.CC4 == False,  True)

    # --- SD: subtract doubleword ---
    cpu.mem.write_word(BASE,     0x00000000)
    cpu.mem.write_word(BASE + 4, 0x00000001)
    cpu.RR[2] = 0x00000000; cpu.RR[3] = 0x00000003
    cpu.execute(C.encode(C.OP_SD, r=2, addr=word_addr(BASE)))
    tr.check("SD lo",            cpu.RR[3],    0x00000002)
    tr.check("SD hi",            cpu.RR[2],    0x00000000)

    # SD with borrow
    cpu.mem.write_word(BASE,     0x00000000)
    cpu.mem.write_word(BASE + 4, 0x00000005)
    cpu.RR[2] = 0x00000001; cpu.RR[3] = 0x00000003
    cpu.execute(C.encode(C.OP_SD, r=2, addr=word_addr(BASE)))
    tr.check("SD borrow lo",     cpu.RR[3],    mask32(-2))   # 3 - 5 = -2
    tr.check("SD borrow hi",     cpu.RR[2],    0x00000000)   # 1 - 0 - borrow = 0

    # --- CD: compare doubleword ---
    cpu.mem.write_word(BASE,     0x00000001)
    cpu.mem.write_word(BASE + 4, 0x00000002)
    cpu.RR[2] = 0x00000001; cpu.RR[3] = 0x00000002
    cpu.execute(C.encode(C.OP_CD, r=2, addr=word_addr(BASE)))
    tr.check_bool("CD equal Z",  cpu.CC3 == False and cpu.CC4 == False,     True)
    tr.check("CD no write hi",   cpu.RR[2],    0x00000001)
    tr.check("CD no write lo",   cpu.RR[3],    0x00000002)

    # --- LCD: load complemented doubleword ---
    cpu.mem.write_word(BASE,     0x00000000)
    cpu.mem.write_word(BASE + 4, 0x00000001)   # 64-bit value = 1
    cpu.execute(C.encode(C.OP_LCD, r=2, addr=word_addr(BASE)))
    tr.check("LCD lo",           cpu.RR[3],    mask32(-1))   # ~1+1 = -1
    tr.check("LCD hi",           cpu.RR[2],    mask32(-1))   # ~0+carry(0) = -1

    # LCD: negate zero → zero
    cpu.mem.write_word(BASE,     0x00000000)
    cpu.mem.write_word(BASE + 4, 0x00000000)
    cpu.execute(C.encode(C.OP_LCD, r=2, addr=word_addr(BASE)))
    tr.check_bool("LCD zero Z",  cpu.CC3 == False and cpu.CC4 == False,     True)

    # --- LAD: load absolute doubleword ---
    # Negative value
    cpu.mem.write_word(BASE,     mask32(-1))   # high = -1
    cpu.mem.write_word(BASE + 4, mask32(-1))   # low  = -1  → 64-bit -1
    cpu.execute(C.encode(C.OP_LAD, r=2, addr=word_addr(BASE)))
    tr.check("LAD neg hi",       cpu.RR[2],    0x00000000)
    tr.check("LAD neg lo",       cpu.RR[3],    0x00000001)
    tr.check_bool("LAD CC_N=F",  cpu.CC4,     False)

    # Positive value (unchanged)
    cpu.mem.write_word(BASE,     0x00000000)
    cpu.mem.write_word(BASE + 4, 0x00000007)
    cpu.execute(C.encode(C.OP_LAD, r=2, addr=word_addr(BASE)))
    tr.check("LAD pos hi",       cpu.RR[2],    0x00000000)
    tr.check("LAD pos lo",       cpu.RR[3],    0x00000007)


# ---------------------------------------------------------------------------
# Tests: Addressing modes (using LW as the vehicle)
# ---------------------------------------------------------------------------
def test_addressing_modes(tr):
    cpu = Sigma7CPU()
    C = Sigma7CPU

    # Direct, non-indexed
    cpu.mem.write_word(0x1000, 0x11111111)
    cpu.execute(C.encode(C.OP_LW, r=1, addr=word_addr(0x1000)))
    tr.check("Addr direct",      cpu.RR[1],    0x11111111)

    # Direct, word-indexed: base=0x1000, RR[3]=2 → EA=0x1008
    cpu.mem.write_word(0x1008, 0x22222222)
    cpu.RR[3] = 2
    cpu.execute(C.encode(C.OP_LW, r=1, x=3, addr=word_addr(0x1000)))
    tr.check("Addr indexed",     cpu.RR[1],    0x22222222)

    # Indirect, non-indexed: ptr at 0x2000 → 0x1000
    cpu.mem.write_word(0x2000, word_addr(0x1000))
    cpu.mem.write_word(0x1000, 0x33333333)
    cpu.execute(C.encode(C.OP_LW, r=1, addr=word_addr(0x2000), i=1))
    tr.check("Addr indirect",    cpu.RR[1],    0x33333333)

    # Indirect + indexed: ptr at 0x2000 → 0x1000, RR[3]=1 → EA=0x1004
    cpu.mem.write_word(0x2000, word_addr(0x1000))
    cpu.mem.write_word(0x1004, 0x44444444)
    cpu.RR[3] = 1
    cpu.execute(C.encode(C.OP_LW, r=1, x=3, addr=word_addr(0x2000), i=1))
    tr.check("Addr indir+idx",   cpu.RR[1],    0x44444444)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run_all_tests():
    tr = TestRunner()

    print("Running word arithmetic tests...")
    test_word_arithmetic(tr)

    print("Running word load/store tests...")
    test_word_load_store(tr)

    print("Running halfword arithmetic tests...")
    test_halfword_arithmetic(tr)

    print("Running halfword load/store tests...")
    test_halfword_load_store(tr)

    print("Running byte load/store tests...")
    test_byte_load_store(tr)

    print("Running logical tests...")
    test_logical(tr)

    print("Running doubleword tests...")
    test_doubleword(tr)

    print("Running addressing mode tests...")
    test_addressing_modes(tr)

    tr.summary()


if __name__ == '__main__':
    run_all_tests()
