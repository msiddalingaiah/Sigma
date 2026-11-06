"""A user-mode Sigma CPU: the instructions a slave-mode program executes. See
docs/interpreter.md.

The semantics are ported from Robert M Supnik's Sigma simulator in simh,
sigma/sigma_cpu.c (comments of the form ``:NNN`` point at it), under its license:

    Copyright (c) 2007-2008, Robert M Supnik

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the "Software"),
    to deal in the Software without restriction, including without limitation
    the rights to use, copy, modify, merge, publish, distribute, sublicense,
    and/or sell copies of the Software, and to permit persons to whom the
    Software is furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in
    all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
    ROBERT M SUPNIK BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
    IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
    CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

    Except as contained in this notice, the name of Robert M Supnik shall not be
    used in advertising or otherwise to promote the sale, use or other dealings
    in this Software without prior written authorization from Robert M Supnik.

Only slave mode: privileged instructions trap, and so do the floating point, decimal
and SF instructions for now (as unimplemented, the machine without the option). Every
trap, a CAL included, stops the CPU and goes to the Python monitor.
"""

from dataclasses import dataclass

# The opcodes, in order (sigma_defs.h:445)
OPCODES = """
00 01 LCFI 03 CAL1 CAL2 CAL3 CAL4 PLW PSW PLM PSM PLS PSS LPSD XPSD
AD CD LD MSP 14 STD 16 17 SD CLM LCD LAD FSL FAL FDL FML
AI CI LI MI SF S LAS 27 CVS CVA LM STM LRA LMS WAIT LRP
AW CW LW MTW LVAW STW DW MW SW CLR LCW LAW FSS FAS FDS FMS
TTBS TBS 42 43 ANLZ CS XW STS EOR OR LS AND SIO TIO TDV HIO
AH CH LH MTH 54 STH DH MH SH 59 LCH LAH 5C 5D 5E 5F
CBS MBS 62 EBS BDR BIR AWM EXU BCR BCS BAL INT RD WD AIO MMC
LCF CB LB MTB STCF STB PACK UNPK DS DA DD DM DSA DC DL DST
""".split()
OP = {name: i for i, name in enumerate(OPCODES)}

CC1, CC2, CC3, CC4 = 8, 4, 2, 1
WMASK, WSIGN, HMASK, HSIGN, BMASK = 0xFFFFFFFF, 0x80000000, 0xFFFF, 0x8000, 0xFF
VAMASK, BVAMASK = 0x1FFFF, 0x7FFFF                     # 17-bit word, 19-bit byte addresses
BY, HW, WD, DW = 0, 1, 2, 3                            # length codes: bytes = 1 << code
S_MCNT, S_ADDRINC = 0xFF000000, 0xFF000001             # S_MCNT + 1: count - 1, address + 1
SP_TS, SP_TW, SP_M = 0x80000000, 0x8000, 0x7FFF        # stack pointer word 2 (:281)
EXU_LIMIT = 32                                         # exu_lim (:179), a simulator guard

PRIVILEGED = {"LPSD", "XPSD", "LRP", "MMC", "WAIT", "RD", "WD", "AIO", "SIO", "TIO", "TDV",
              "HIO"}
NXI_PRV = {"LRA", "LMS", "PSS", "PLS"}                 # TR_NXI|TR_PRV in slave mode (:1567)
OPTIONAL = {"FAS", "FSS", "FMS", "FDS", "FAL", "FSL", "FML", "FDL", "SF",
            "DL", "DST", "DA", "DS", "DM", "DD", "DC", "DSA", "PACK", "UNPK", "EBS"}
DOUBLE_REG = {"AD", "SD", "TBS", "TTBS", "FAL", "FSL", "FML", "FDL"}   # odd R: TR_INVREG on S8/9

# ANLZ's table (:374): CC1, CC2, CC4 and the operand length
ANLZ_TAB = ([0x9] * 4 + [0x8] * 4 + [0xC] * 24 + [0x9] * 4 + [0x8] * 28 + [0x1] * 4 +
            [0x8] * 12 + [0x4] * 16 + [0x1] * 4 + [0x8] * 12 + [0x0] * 16)


@dataclass
class Trap:
    """A trap: its location (X'40'-X'4D') and the CC it ORs in (:351-:373)."""
    vector: int
    cc: int = 0
    pc: int = 0                                        # the instruction that trapped

    @property
    def name(self):
        if self.vector == 0x40:
            return {CC1: "non-existent instruction", CC2: "non-existent memory",
                    CC3: "privileged instruction", CC4: "memory protection",
                    CC1 | CC3: "non-existent and privileged instruction"}.get(self.cc, "X'40'")
        return {0x41: "unimplemented instruction", 0x42: "push-down overflow",
                0x43: "fixed-point overflow", 0x44: "floating point", 0x45: "decimal",
                0x48: "CAL1", 0x49: "CAL2", 0x4A: "CAL3", 0x4B: "CAL4",
                0x4D: "invalid register"}.get(self.vector, f"X'{self.vector:02X}'")


class _Trap(Exception):
    def __init__(self, vector, cc=0):
        self.vector, self.cc = vector, cc


NXI, PRV, UNI, PSH, FIX = (0x40, CC1), (0x40, CC3), (0x41, 0), (0x42, 0), (0x43, 0)
INVREG = (0x4D, CC4)


def sext(x, bits):
    sign = 1 << (bits - 1)
    return (x | (WMASK & ~((1 << bits) - 1))) & WMASK if x & sign else x & ((1 << bits) - 1)


def neg(x):
    return (~x + 1) & WMASK


def neg_d(hi, lo):
    lo = neg(lo)
    return (~hi + (lo == 0)) & WMASK, lo


def cmp32(a, b):
    """Cmp32  :2246 - a signed compare: CC3 greater, CC4 less."""
    if a == b:
        return 0
    if (a ^ b) & WSIGN:
        return CC4 if a & WSIGN else CC3
    return CC4 if a < b else CC3


class Cpu:
    """One user's processor: its registers and memory (the Python monitor's uregs and
    umem, shared), the condition codes, the floating controls and AM, and the PC."""

    def __init__(self, regs, mem, pc=0, cc=0, model="sigma9"):
        self.R, self.M = regs, mem
        self.PC, self.CC = pc & VAMASK, cc
        self.FPC = 0                                   # FR FS FZ FN (PSD bits 4-7)
        self.AM = False                                # arithmetic trap mask
        self.DM = False                                # decimal mask (kept for the PSD only)
        self.s89 = model in ("sigma9", "x560", "sigma8")
        self.s567 = not self.s89

    # -- memory: word addresses 0-15 are the registers (sigma_map.c:168) --------------

    def rw(self, bva):
        a = (bva & BVAMASK) >> 2
        return self.R[a] if a < 16 else self.M.get(a, 0) & WMASK

    def ww(self, bva, v):
        a = (bva & BVAMASK) >> 2
        if a < 16:
            self.R[a] = v & WMASK
        else:
            self.M[a] = v & WMASK

    def rb(self, bva):
        return (self.rw(bva) >> (8 * (3 - (bva & 3)))) & BMASK

    def wb(self, bva, v):
        k = 8 * (3 - (bva & 3))
        self.ww(bva, (self.rw(bva) & ~(BMASK << k)) | ((v & BMASK) << k))

    def rh(self, bva):
        return (self.rw(bva) >> (0 if bva & 2 else 16)) & HMASK

    def wh(self, bva, v):
        k = 0 if bva & 2 else 16
        self.ww(bva, (self.rw(bva) & ~(HMASK << k)) | ((v & HMASK) << k))

    def rd(self, bva):
        a = bva & ~7
        return self.rw(a), self.rw(a + 4)              # forced alignment (:183)

    def wd(self, bva, hi, lo):
        a = bva & ~7
        self.ww(a, hi)
        self.ww(a + 4, lo)

    # -- decoding ---------------------------------------------------------------------

    def ea(self, ir, lnt):
        """Ea  :1897 - indirect first, then the index scaled by the operand length."""
        xr = (ir >> 17) & 7
        ad = (ir & VAMASK) << 2
        if ir & WSIGN:
            ad = (self.rw(ad) & VAMASK) << 2
        return (ad + ((self.R[xr] << lnt) if xr else 0)) & BVAMASK

    def imm(self, ir):
        """ImmOp  :1883 - an immediate instruction with the indirect bit is NXI."""
        if ir & WSIGN:
            raise _Trap(*NXI)
        return sext(ir & 0xFFFFF, 20)

    def cc34(self, x):
        """CC34_W  sigma_defs.h:435"""
        if x & WSIGN:
            self.CC = (self.CC & ~CC3) | CC4
        elif x:
            self.CC = (self.CC & ~CC4) | CC3
        else:
            self.CC &= ~(CC3 | CC4)

    def cc234(self, x, y):
        """CC234_CMP  sigma_defs.h:440"""
        self.CC = (self.CC & CC1) | cmp32(x, y) | (CC2 if x & y else 0)

    def add32(self, s1, s2, cin):
        """Add32  :2159 - CC1 carry, CC2 overflow."""
        t = (s1 + s2 + cin) & WMASK
        self.CC = CC4 if t & WSIGN else (CC3 if t else 0)
        if (t <= s1) if cin else (t < s1):
            self.CC |= CC1
        if ((s1 ^ ~s2) & (s1 ^ t)) & WSIGN:
            self.CC |= CC2
        return t

    def fix(self):
        if (self.CC & CC2) and self.AM:
            raise _Trap(*FIX)

    def overflow_if(self, cond):
        if cond:
            self.CC |= CC2
            if self.AM:
                raise _Trap(*FIX)
        else:
            self.CC &= ~CC2

    # -- running ----------------------------------------------------------------------

    def step(self):
        """One instruction. Returns None, or the Trap; on a trap the PC is back at the
        instruction (:495-:497)."""
        old = self.PC
        try:
            ir = self.rw(self.PC << 2)
            self.PC = (self.PC + 1) & VAMASK
            self.execute(ir, old)
        except _Trap as t:
            self.PC = old
            return Trap(t.vector, t.cc, old)
        return None

    def run(self, n):
        """Up to ``n`` instructions; returns (executed, trap or None)."""
        for i in range(n):
            t = self.step()
            if t is not None:
                return i, t
        return n, None

    def execute(self, ir, pc):
        exu = 0
        while True:
            op = OPCODES[(ir >> 24) & 0x7F]
            if op != "EXU":
                return self.op(op, ir, pc)
            exu += 1
            if exu > EXU_LIMIT:
                raise _Trap(*NXI)                      # STOP_EXULIM in simh
            ir = self.rw(self.ea(ir, WD))              # :1363

    def op(self, op, ir, pc):
        R, rn = self.R, (ir >> 20) & 0xF
        r1 = rn | 1
        if op in PRIVILEGED:
            raise _Trap(*PRV)
        if op in NXI_PRV:
            raise _Trap(0x40, CC1 | CC3)
        if op in DOUBLE_REG and self.s89 and rn & 1:
            raise _Trap(*INVREG)
        if op in OPTIONAL:
            raise _Trap(*UNI)

        # loads and stores  :541-:829
        if op == "LI":
            v = self.imm(ir)
            self.cc34(v)
            R[rn] = v
        elif op in ("LB", "LH", "LCH", "LAH"):
            a = self.ea(ir, BY if op == "LB" else HW)
            v = self.rb(a) if op == "LB" else self.rh(a)
            if op == "LH":
                v = sext(v, 16)
            elif op == "LCH":
                v = neg(sext(v, 16))
            elif op == "LAH" and v & HSIGN:
                v = neg(v) & HMASK
            self.cc34(v)
            R[rn] = v
        elif op in ("LW", "LCW", "LAW"):
            v = self.rw(self.ea(ir, WD))
            if op == "LCW" or (op == "LAW" and v & WSIGN):
                v = neg(v)
            self.cc34(v)
            R[rn] = v
            if op != "LW":
                self.overflow_if(v == WSIGN)
        elif op == "LS":
            v = self.rw(self.ea(ir, WD))
            v = (R[rn] & ~R[r1]) | (v & R[r1])
            self.cc34(v & WMASK)
            R[rn] = v & WMASK
        elif op in ("LD", "LCD", "LAD"):
            hi, lo = self.rd(self.ea(ir, DW))
            if op == "LCD" or (op == "LAD" and hi & WSIGN):
                hi, lo = neg_d(hi, lo)
            self.cc_d(hi, lo)
            R[r1], R[rn] = lo, hi
            if op != "LD":
                self.overflow_if(hi == WSIGN and lo == 0)
        elif op == "LM":
            lim = self.CC or 16
            a = self.ea(ir, WD)
            for _ in range(lim):
                R[rn] = self.rw(a)
                a, rn = (a + 4) & BVAMASK, (rn + 1) & 0xF
        elif op in ("LCFI", "LCF"):
            v = self.imm(ir) if op == "LCFI" else self.rb(self.ea(ir, BY))
            if ir & (1 << 21):                         # IRB(10): load the CC
                self.CC = (v >> 4) & 0xF
            if ir & (1 << 20):                         # IRB(11): the floating controls
                self.FPC = v & 0xF
        elif op == "XW":
            a = self.ea(ir, WD)
            v = self.rw(a)
            self.ww(a, R[rn])
            self.cc34(v)
            R[rn] = v
        elif op == "STB":
            self.wb(self.ea(ir, BY), R[rn])
        elif op == "STH":
            self.wh(self.ea(ir, HW), R[rn])
            if R[rn] == sext(R[rn] & HMASK, 16):
                self.CC &= ~CC2
            else:
                self.CC |= CC2
        elif op == "STW":
            self.ww(self.ea(ir, WD), R[rn])
        elif op == "STD":
            self.wd(self.ea(ir, DW), R[rn], R[r1])
        elif op == "STS":
            a = self.ea(ir, WD)
            self.ww(a, (self.rw(a) & ~R[r1]) | (R[rn] & R[r1]))
        elif op == "STM":
            lim = self.CC or 16
            a = self.ea(ir, WD)
            for _ in range(lim):
                self.ww(a, R[rn])
                a, rn = (a + 4) & BVAMASK, (rn + 1) & 0xF
        elif op == "STCF":
            self.wb(self.ea(ir, BY), (self.CC << 4) | self.FPC)
        elif op == "ANLZ":
            self.anlz(ir, rn)
        elif op == "INT":
            v = self.rw(self.ea(ir, WD))               # :870
            self.CC = (v >> 28) & 0xF
            R[rn] = (v >> 16) & 0xFFF
            R[r1] = v & 0xFFFF
        elif op == "LAS":                              # :642, map_las sigma_map.c:481
            if self.s567:
                raise _Trap(*NXI)                      # an option on the Sigma 5-7
            a = self.ea(ir, WD) >> 2
            v = self.M.get(a, 0) & WMASK               # memory, even below X'10'
            self.M[a] = v | WSIGN
            R[rn] = v
            self.cc34(v)
        elif op == "LVAW":
            raise _Trap(*NXI)                          # 5X0 only (:652)

        # arithmetic  :882-:1111
        elif op in ("AI", "AH", "AW", "SH", "SW"):
            if op == "AI":
                v = self.imm(ir)
            elif op in ("AH", "SH"):
                v = sext(self.rh(self.ea(ir, HW)), 16)
            else:
                v = self.rw(self.ea(ir, WD))
            if op in ("SH", "SW"):
                R[rn] = self.add32(R[rn], v ^ WMASK, 1)
            else:
                R[rn] = self.add32(R[rn], v, 0)
            self.fix()
        elif op in ("AD", "SD"):
            hi, lo = self.rd(self.ea(ir, DW))
            if op == "SD":
                lo1 = self.add32(R[r1], lo ^ WMASK, 1)
                hi1 = self.add32(R[rn], hi ^ WMASK, 1 if self.CC & CC1 else 0)
            else:
                lo1 = self.add32(R[r1], lo, 0)
                hi1 = self.add32(R[rn], hi, 1 if self.CC & CC1 else 0)
            if hi1 == 0 and lo1 != 0:
                self.CC = (self.CC & ~CC4) | CC3
            R[r1], R[rn] = lo1, hi1
            self.fix()
        elif op == "AWM":
            a = self.ea(ir, WD)
            self.ww(a, self.add32(R[rn], self.rw(a), 0))
            self.fix()
        elif op in ("MI", "MW"):
            v = self.imm(ir) if op == "MI" else self.rw(self.ea(ir, WD))
            R[rn], R[r1] = self.smul64(R[r1], v)
        elif op == "MH":
            v = sext(self.rh(self.ea(ir, HW)), 16)
            p = (signed(sext(R[rn] & HMASK, 16)) * signed(v)) & WMASK
            self.cc34(p)
            R[r1] = p
        elif op == "DH":
            v = self.rh(self.ea(ir, HW))
            if v == 0 or (R[rn] == WSIGN and v == HMASK):
                self.CC |= CC2
                if self.AM:
                    raise _Trap(*FIX)
            else:
                a, b = signed(R[rn]), signed(sext(v, 16))
                q = abs(a) // abs(b)                   # C division: toward zero
                q = (-q if (a < 0) != (b < 0) else q) & WMASK
                self.CC &= ~CC2
                self.cc34(q)
                R[rn] = q
        elif op == "DW":
            dvr = self.rw(self.ea(ir, WD))
            hi = (WMASK if R[rn] & WSIGN else 0) if rn & 1 else R[rn]
            res = self.sdiv64(hi, R[r1], dvr)
            if res is None:
                self.CC |= CC2
                if self.AM:
                    raise _Trap(*FIX)
            else:
                quo, rem = res
                self.CC &= ~CC2
                self.cc34(quo)
                R[rn], R[r1] = rem, quo
        elif op == "MTB":
            a = self.ea(ir, BY)
            v = self.rb(a)
            res = (v + (sext(rn, 4) & BMASK)) & BMASK
            self.CC = CC1 if res < v else 0
            self.cc34(res)
            if rn:
                self.wb(a, res)
        elif op == "MTH":
            a = self.ea(ir, HW)
            v = self.rh(a)
            m = sext(rn, 4) & HMASK
            res = v + m
            self.CC = 0 if not res & HMASK else (CC4 if res & HSIGN else CC3)
            if res & ~HMASK:
                self.CC |= CC1
            if ((v ^ ~m) & (v ^ res)) & HSIGN:
                self.CC |= CC2
            if rn:
                self.wh(a, res)
            self.fix()
        elif op == "MTW":
            a = self.ea(ir, WD)
            res = self.add32(self.rw(a), sext(rn, 4), 0)
            if rn:
                self.ww(a, res)
            self.fix()

        # logical and compare  :1115-:1222
        elif op in ("AND", "OR", "EOR"):
            v = self.rw(self.ea(ir, WD))
            v = R[rn] & v if op == "AND" else (R[rn] | v if op == "OR" else R[rn] ^ v)
            self.cc34(v)
            R[rn] = v
        elif op == "CI":
            self.cc234(R[rn], self.imm(ir))
        elif op == "CB":
            self.cc234(R[rn] & BMASK, self.rb(self.ea(ir, BY)))
        elif op == "CH":
            self.cc234(R[rn], sext(self.rh(self.ea(ir, HW)), 16))
        elif op == "CW":
            self.cc234(R[rn], self.rw(self.ea(ir, WD)))
        elif op == "CD":
            hi, lo = self.rd(self.ea(ir, DW))
            self.CC &= ~(CC3 | CC4)
            if R[rn] != hi:
                self.CC |= cmp32(R[rn], hi)
            elif R[r1] != lo:
                self.CC |= CC4 if R[r1] < lo else CC3
        elif op == "CS":
            v = self.rw(self.ea(ir, WD)) & R[r1]
            m = R[rn] & R[r1]
            self.CC = (self.CC & ~(CC3 | CC4)) | (CC4 if m < v else (CC3 if m > v else 0))
        elif op == "CLR":
            v = self.rw(self.ea(ir, WD))
            self.CC = cmp32(R[rn], v) | (cmp32(R[r1], v) << 2)
        elif op == "CLM":
            hi, lo = self.rd(self.ea(ir, DW))
            self.CC = cmp32(R[rn], hi) | (cmp32(R[rn], lo) << 2)

        # shift and convert  :1226-:1278
        elif op == "S":
            stype, sc = self.ea_shift(ir)
            if stype >= 6 and self.s567:
                stype = 4                              # searching: arithmetic on S5-7
            self.CC = (self.CC & ~(CC1 | CC2 | CC4)) | self.shift(rn, stype, sc)
        elif op == "CVA":
            a = self.ea(ir, WD)
            self.CC &= ~CC1
            res = 0
            for i in range(32):
                if (R[r1] >> (31 - i)) & 1:
                    v = self.rw((a + (i << 2)) & BVAMASK)
                    res = (res + v) & WMASK
                    if res < v:
                        self.CC |= CC1
            self.cc34(res)
            R[rn] = res
        elif op == "CVS":
            a = self.ea(ir, WD)
            res, bits = R[rn], 0
            for i in range(32):
                v = self.rw((a + (i << 2)) & BVAMASK)
                if v <= res:
                    res = (res - v) & WMASK
                    bits |= 1 << (31 - i)
            self.cc34(bits)
            R[rn], R[r1] = res, bits

        # the stack  :1282-:1359
        elif op in ("PSW", "PLW", "PSM", "PLM", "MSP"):
            self.stack(op, ir, rn)

        # control  :1373-:1441
        elif op in ("BCS", "BCR"):
            a = self.ea(ir, WD)
            if bool(self.CC & rn) == (op == "BCS"):
                self.PC = (a >> 2) & VAMASK
        elif op == "BIR":
            a = self.ea(ir, WD)
            res = (R[rn] + 1) & WMASK
            if res & WSIGN:
                self.PC = (a >> 2) & VAMASK
            R[rn] = res
        elif op == "BDR":
            a = self.ea(ir, WD)
            res = (R[rn] - 1) & WMASK
            if not res & WSIGN and res:
                self.PC = (a >> 2) & VAMASK
            R[rn] = res
        elif op == "BAL":
            a = self.ea(ir, WD)
            R[rn] = (pc + 1) & VAMASK
            self.PC = (a >> 2) & VAMASK
        elif op in ("CAL1", "CAL2", "CAL3", "CAL4"):
            raise _Trap(0x48 + int(op[3]) - 1, rn)

        # byte strings  :1607-:1720
        elif op in ("MBS", "CBS", "TBS", "TTBS"):
            self.string(op, ir, rn)
        else:
            raise _Trap(*NXI)                          # undefined (:1777)

    # -- helpers ------------------------------------------------------------------------

    def cc_d(self, hi, lo):
        if hi == 0 and lo != 0:
            self.CC = (self.CC & ~CC4) | CC3
        else:
            self.cc34(hi)

    def smul64(self, a, b):
        """SMul64  :2175 - the 64-bit product; CC2 if it doesn't fit in 32 bits."""
        self.CC &= CC1
        if a == 0 or b == 0:
            return 0, 0
        p = (signed(a) * signed(b)) & 0xFFFFFFFFFFFFFFFF
        hi, lo = p >> 32, p & WMASK
        if hi & WSIGN:
            self.CC |= CC4
        elif hi or lo:
            self.CC |= CC3
        if hi != (WMASK if lo & WSIGN else 0):
            self.CC |= CC2
        return hi, lo

    @staticmethod
    def sdiv64(hi, lo, dvr):
        """SDiv64  :2217 - (quotient, remainder), or None on overflow."""
        quos, rems = hi ^ dvr, hi
        if hi & WSIGN:
            hi, lo = neg_d(hi, lo)
        if dvr & WSIGN:
            dvr = neg(dvr)
        if hi >= dvr:
            return None
        quo = 0
        for _ in range(32):
            quo = (quo << 1) & WMASK
            hi = ((hi << 1) | (lo >> 31)) & WMASK
            lo = (lo << 1) & WMASK
            if hi >= dvr:
                hi = (hi - dvr) & WMASK
                quo += 1
        if quo & WSIGN:
            return None
        rem = neg(hi) if rems & WSIGN else hi
        return (neg(quo) if quos & WSIGN else quo), rem

    def ea_shift(self, ir):
        """EaSh  :1949 - the type in bits 21-23 and the count in 25-31 of the address."""
        ad = ir & VAMASK
        if ir & WSIGN:
            ad = self.rw(ad << 2) & VAMASK
        xr = (ir >> 17) & 7
        if xr:
            ad = (ad & ~0x7F) | ((ad + self.R[xr]) & 0x7F)
        return (ad >> 8) & 7, ad & 0x7F

    def shift(self, rn, stype, sc):
        """Shift  :1973 - returns the CC1, CC2 and CC4 bits."""
        R, r1 = self.R, rn | 1
        opnd, opnd1, cc = R[rn], R[r1], self.CC & CC4
        if sc & 0x40:                                  # right
            sc = 0x80 - sc
            if stype == 0:
                R[rn] = 0 if sc > 31 else R[rn] >> sc
            elif stype in (1, 5):
                t = WMASK if (stype == 5 and opnd & WSIGN) else 0
                d = (opnd << 32) | opnd1
                if t:
                    d = (d - (1 << 64)) >> sc if sc < 64 else -1
                else:
                    d = d >> sc if sc < 64 else 0
                d &= 0xFFFFFFFFFFFFFFFF
                R[rn], R[r1] = d >> 32, d & WMASK
            elif stype == 2:
                sc %= 32
                R[rn] = ((R[rn] >> sc) | (R[rn] << (32 - sc))) & WMASK
            elif stype == 3:
                sc %= 64
                d = (opnd << 32) | opnd1
                d = ((d >> sc) | (d << (64 - sc))) & 0xFFFFFFFFFFFFFFFF
                R[rn], R[r1] = d >> 32, d & WMASK
            elif stype == 4:
                t = WMASK if R[rn] & WSIGN else 0
                R[rn] = t if sc > 31 else ((R[rn] >> sc) | (t << (32 - sc))) & WMASK
            else:                                      # 6, 7: right search
                i = 0
                while i < sc and not opnd & WSIGN:
                    if stype == 6:
                        opnd = ((opnd >> 1) | (opnd << 31)) & WMASK
                    else:
                        opnd, opnd1 = (((opnd >> 1) | (opnd1 << 31)) & WMASK,
                                       ((opnd1 >> 1) | (opnd << 31)) & WMASK)
                    i += 1
                cc = (cc | CC4) if opnd & WSIGN else (cc & ~CC4)
                R[rn] = opnd
                if stype == 7:
                    R[r1] = opnd1
                R[1] = sc - i
        else:                                          # left
            orig = R[rn]
            double = stype in (1, 3, 5, 7)
            search = stype in (6, 7)
            i = 0
            while i < sc and not (search and opnd & WSIGN):
                top = opnd & WSIGN
                if not search and top:
                    cc ^= CC1                          # count the 1s shifted out
                if stype in (0, 4):
                    opnd = (opnd << 1) & WMASK
                elif stype in (1, 5):
                    opnd, opnd1 = ((opnd << 1) | (opnd1 >> 31)) & WMASK, (opnd1 << 1) & WMASK
                elif stype in (2, 6):
                    opnd = ((opnd << 1) | (opnd >> 31)) & WMASK
                else:                                  # 3, 7: circular double
                    opnd, opnd1 = (((opnd << 1) | (opnd1 >> 31)) & WMASK,
                                   ((opnd1 << 1) | (top >> 31)) & WMASK)
                if (opnd ^ orig) & WSIGN:
                    cc |= CC2
                i += 1
            if search:
                cc = (cc | CC4) if opnd & WSIGN else (cc & ~CC4)
                R[1] = sc - i
            R[rn] = opnd
            if double:
                R[r1] = opnd1
        return cc

    def test_sp(self, sp1, mod):
        """TestSP1  :2258 - None if the stack may change by ``mod``; else raise TR_PSH,
        or return False with the CC set (the trap disabled)."""
        spc, wds = (sp1 >> 16) & SP_M, sp1 & SP_M
        cc = 0
        if wds + mod > SP_M or wds + mod < 0:
            if not sp1 & SP_TW:
                raise _Trap(*PSH)
            cc |= CC3
        if spc - mod > SP_M or spc - mod < 0:
            if not sp1 & SP_TS:
                raise _Trap(*PSH)
            cc |= CC1
        self.CC = cc
        if cc or mod == 0:
            self.CC |= (0 if spc else CC2) | (0 if wds else CC4)
            return False
        return True

    def mod_sp(self, a, sp, sp1, mod):
        """ModWrSP  :2287"""
        sp = (sp + mod) & WMASK
        sp1 = ((sp1 & (SP_TS | SP_TW)) | (((((sp1 >> 16) & SP_M) - mod) & SP_M) << 16) |
               ((((sp1 & SP_M) + mod) & SP_M)))
        self.wd(a, sp, sp1)
        if mod > 0 and ((sp1 >> 16) & SP_M) == 0:
            self.CC |= CC2
        if mod < 0 and (sp1 & SP_M) == 0:
            self.CC |= CC4

    def stack(self, op, ir, rn):
        R = self.R
        a = self.ea(ir, DW)
        sp, sp1 = self.rd(a)
        if op == "PSW":
            if self.test_sp(sp1, 1):
                self.ww(((sp + 1) << 2) & BVAMASK, R[rn])
                self.mod_sp(a, sp, sp1, 1)
        elif op == "PLW":
            if self.test_sp(sp1, -1):
                v = self.rw(sp << 2)
                self.mod_sp(a, sp, sp1, -1)
                R[rn] = v
        elif op == "PSM":
            lim = self.CC or 16
            if self.test_sp(sp1, lim):
                for i in range(lim):
                    self.ww(((sp + i + 1) << 2) & BVAMASK, R[rn])
                    rn = (rn + 1) & 0xF
                self.mod_sp(a, sp, sp1, lim)
        elif op == "PLM":
            lim = self.CC or 16
            if self.test_sp(sp1, -lim):
                rn = (rn + lim - 1) & 0xF
                for i in range(lim):
                    R[rn] = self.rw(((sp - i) << 2) & BVAMASK)
                    rn = (rn - 1) & 0xF
                self.mod_sp(a, sp, sp1, -lim)
        else:                                          # MSP
            mod = signed(sext(R[rn] & HMASK, 16))
            if self.test_sp(sp1, mod):
                self.mod_sp(a, sp, sp1, mod)

    def string(self, op, ir, rn):
        """MBS, CBS, TBS, TTBS  :1607-:1720. R+1: the count (bits 0-7) and the
        destination byte address; R: the source (or the table, for TBS/TTBS)."""
        R, r1 = self.R, rn | 1
        disp = self.imm(ir)

        def count():
            return (R[r1] >> 24) & 0xFF

        def step_dst():
            R[r1] = (R[r1] + S_ADDRINC) & WMASK

        if op == "MBS":
            while count():
                c = self.rb((disp + (R[rn] if rn else 0)) & BVAMASK)
                self.wb(R[r1] & BVAMASK, c)
                if rn and not rn & 1:
                    R[rn] = (R[rn] + 1) & WMASK
                step_dst()
        elif op == "CBS":
            self.CC &= ~(CC3 | CC4)
            while count():
                c = self.rb((disp + (R[rn] if rn else 0)) & BVAMASK)
                c1 = self.rb(R[r1] & BVAMASK)
                if c != c1:
                    self.CC |= CC4 if c < c1 else CC3
                    break
                if rn and not rn & 1:
                    R[rn] = (R[rn] + 1) & WMASK
                step_dst()
        elif op == "TBS":
            while count():
                sa = (disp + (R[rn] if rn else 0)) & BVAMASK
                da = R[r1] & BVAMASK
                self.wb(da, self.rb((sa + self.rb(da)) & BVAMASK))
                step_dst()
        else:                                          # TTBS
            mask = ((R[rn] >> 24) & 0xFF) if rn else 0xFF
            self.CC &= ~CC4
            while count():
                sa = (disp + (R[rn] if rn else 0)) & BVAMASK
                da = R[r1] & BVAMASK
                t = self.rb((sa + self.rb(da)) & BVAMASK) & mask
                if t:
                    if rn:
                        R[rn] = (R[rn] & ~S_MCNT & WMASK) | (t << 24)
                    self.CC |= CC4
                    break
                step_dst()

    def anlz(self, ir, rn):
        """ANLZ  :833 - the instruction at the effective address: its class in the CC,
        and for a memory reference its operand's address in R."""
        w = self.rw(self.ea(ir, WD))
        t = ANLZ_TAB[(w >> 24) & 0x7F]
        self.CC = t & (CC1 | CC2 | CC4)
        if w & WSIGN:
            self.CC |= CC3
        if not t & CC4:
            lnt = t >> 2
            self.R[rn] = self.ea(w, lnt) >> lnt


def signed(x):
    x &= WMASK
    return x - (1 << 32) if x & WSIGN else x
