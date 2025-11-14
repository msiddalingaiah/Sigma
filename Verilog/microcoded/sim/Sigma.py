
import time
import sys

OPCODES = ['?.00', '?.01', 'LCFI', '?.03', 'CAL1', 'CAL2', 'CAL3', 'CAL4', 'PLW', 'PSW', 'PLM', 'PSM', '?.0C',
           '?.0D', 'LPSD', 'XPSD', 'AD', 'CD', 'LD', 'MSP', '?.14', 'STD', '?.16', '?.17', 'SD', 'CLM', 'LCD',
           'LAD', 'FSL', 'FAL', 'FDL', 'FML', 'AI', 'CI', 'LI', 'MI', 'SF', 'S', '?.26', '?.27', 'CVS', 'CVA',
           'LM', 'STM', '?.2C', '?.2D', 'WAIT', 'LRP', 'AW', 'CW', 'LW', 'MTW', '?.34', 'STW', 'DW', 'MW', 'SW',
           'CLR', 'LCW', 'LAW', 'FSS', 'FAS', 'FDS', 'FMS', 'TTBS', 'TBS', '?.42', '?.43', 'ANLZ', 'CS', 'XW',
           'STS', 'EOR', 'OR', 'LS', 'AND', 'SIO', 'TIO', 'TDV', 'HIO', 'AH', 'CH', 'LH', 'MTH', '?.54', 'STH',
           'DH', 'MH', 'SH', '?.59', 'LCH', 'LAH', '?.5C', '?.5D', '?.5E', '?.5F', 'CBS', 'MBS', '?.62', 'EBS',
           'BDR', 'BIR', 'AWM', 'EXU', 'BCR', 'BCS', 'BAL', 'INT', 'RD', 'WD', 'AIO', 'MMC', 'LCF', 'CB', 'LB',
           'MTB', 'STFC', 'STB', 'PACK', 'UNPK', 'DS', 'DA', 'DD', 'DM', 'DSA', 'DC', 'DL', 'DST']

class Memory(object):
    def __init__(self):
        self.memory = [0]*65536
        self.memory[0x20] = 0x00000000 # Reserved for I/O
        self.memory[0x21] = 0x00000000 # Reserved for I/O
        self.memory[0x22] = 0x020000a8 # Bits 0 through 31 of I/O command doubleword. Specifies read order (02) and starting byte location X'A8'. Word location is X'A8' 1/4, or X'2A'
        self.memory[0x23] = 0x0e000058 # Bits 32 through 63 of I/O command doubleword. Contains flag bits OE, which specify halt on transmission error, interrupt on unusual end, and suppress incorrect length. X'581 specifies reading 88 bytes into consecutive memory locations
        self.memory[0x24] = 0x00000011 # Command address of I/O command doubleword (shifted one bit position to the left in lOP to specify word location X'221)
        self.memory[0x25] = 0x00000001 # 0x00000XXX Address of I/O unit. (XXX represents address taken from UNIT ADDRESS switches)
        self.memory[0x26] = 0x32000024 # Load Word instruction. Loads the contents of location X'241 (X'l1 I) into private memory register 0
        self.memory[0x27] = 0xcc000025 # Indirectly-addressed Start Input/Output instruction. Takes command doubleword from location specified in private memory register 0 and specifies device pointed to by address in location 25
        self.memory[0x28] = 0xcd000025 # Indirectly-addressed Test Input/Output instruction
        self.memory[0x29] = 0x69c0001c # Loop until I/O complete. Program execution continues at next instruction address at 0x2A

    def readW(self, addr):
        return self.memory[addr]
    
    def readB(self, addr, offset):
        return (self.memory[addr] >> 8*(3 - offset)) & 0xff
    
    def writeW(self, addr, value):
        # print(f'write 0x{value:x} to 0x{addr:x}')
        self.memory[addr] = value
    
    def writeB(self, addr, offset, value):
        word = self.memory[addr]
        mask = ~(0xff << 8*(3 - offset))
        word &= mask
        value &= 0xff
        value <<= 8*(3 - offset)
        word |= value
        # print(f'Write word 0x{word:08x} to WA 0x{addr:x}, offset {offset}')
        self.memory[addr] = word

class CardReader(object):
    def __init__(self, memory, filename):
        self.card = 0
        self.memory = memory
        with open(filename, 'rb') as f:
            self.bytes = f.read()
        self.index = 0

    def startIO(self, daddr):
        addr = daddr << 1
        c0 = self.memory.readW(addr)
        c1 = self.memory.readW(addr+1)
        # TODO handle flags
        if c0 >> 24 == 2:
            ba = c0 & 0xffffff
            n = c1 & 0xffff
            self.card += 1
            print(f'CardReader: reading {n} bytes into WA 0x{ba>>2:x} + {ba&3} bytes, CARD {self.card}, flags: 0x{c1>>24:02x}')
            # Binary cards are 120 bytes long
            for i in range(120):
                if n > 0 and self.index < len(self.bytes):
                    self.memory.writeB(ba >> 2, ba & 3, self.bytes[self.index])
                    ba += 1
                    n -= 1
                self.index += 1
            if self.index >= len(self.bytes):
                print(f'End of deck!')
            return 0
        else:
            raise Exception(f'Unexpected IOP command: 0x{c0:08x}')

    def testIO(self, daddr):
        # if self.index >= len(self.bytes):
        #     return 0xc # I/O address not recognized and no status information is returned to general registers.
        return 0

class CPU(object):
    def __init__(self, memory, iops):
        self.a = 0
        self.c = 0
        self.cc = 0
        self.d = 0
        self.ff = 0
        self.mask5 = 0
        self.o = 0
        self.p = 0x26 << 2
        self.psd1 = 0
        self.q = 0
        self.r = 0
        self.x = 0
        self.rr = [0]*16
        self.memory = memory
        self.iops = iops
        self.ia_trace = []
        self.armed = [False]*128
        self.enabled = [False]*128
        self.active = [False]*128
        self.inTrap = False
        self.sense_switches = 0

    def readB(self, addr):
        offset = addr & 3
        addr >>= 2
        if addr < 16:
            return (self.rr[addr] >> 8*(3 - offset)) & 0xff
        return self.memory.readB(addr, offset)

    def readW(self, addr):
        addr >>= 2
        if addr < 16:
            return self.rr[addr]
        return self.memory.readW(addr)

    def writeB(self, addr, value):
        offset = addr & 3
        addr >>= 2
        if addr < 16:
            word = self.rr[addr]
            word &= ~(0xff << 8*(3 - offset))
            word |= (value & 0xff) << (8*(3 - offset))
            self.rr[addr] = word
            return
        self.memory.writeB(addr, offset, value)

    def writeW(self, addr, value):
        addr >>= 2
        if addr < 16:
            self.rr[addr] = value
            return
        self.memory.writeW(addr, value)

    def run(self):
        self.ende()
        opcount = 0
        start_ns = time.time_ns()
        while True:
            if opcount % 1000000 == 0:
                print('1000000 instructions executed: ctrl-C to terminate.')
                self.debug()
            self.execOne()
            dt_ns = time.time_ns() - start_ns
            if dt_ns > 2e6:
                start_ns = time.time_ns()
                self.interrupt(0x54)
                self.interrupt(0x55)
            self.ende()
            opcount += 1

    def interrupt(self, loc):
        if self.enabled[loc] and not self.active[loc]:
            # print(f'Interrupt 0x{loc:x}')
            self.doTrap(loc)

    def doTrap(self, loc):
        if self.inTrap:
            print(f'Double trap 0x{loc:x}, execution terminated.')
            self.debug()
            sys.exit(0)
        p, q = self.p, self.q
        self.p = loc << 2
        self.ende()
        self.p, self.q = p, q
        self.inTrap = True
        self.execOne()
        self.inTrap = False

    def testa(self):
        self.cc &= 0xc
        a0 = self.a & 0x80000000
        if a0 == 0 and self.a != 0:
            self.cc |= 2
        if a0:
            self.cc |= 1
    
    def ende(self):
        self.c = self.readW(self.p)
        self.ia_trace.append((self.p >> 2, self.c))
        self.iword = self.c
        self.p += 4
        self.q = self.p >> 2
        self.o = (self.c >> 24) & 0x7f
        self.r = (self.c >> 20) & 0xf
        self.a = self.rr[self.r]
        if (self.o & 0x1c) == 0:
            # Immediate instruction
            if self.c & 0x80000000:
                self.trap(0x40)
            self.d = self.c & 0xfffff
            if self.d & 0x80000:
                self.d |= 0xfff00000
            return
        self.x = (self.c >> 17) & 7
        if self.c & 0x80000000:
            self.c = self.readW((self.c & 0x1ffff) << 2)
        self.p = (self.c & 0x1ffff) << 2
        # p contains effective BYTE address
        if self.o >> 4 == 7 and self.x:
            # Byte indexed
            self.p += self.rr[self.x]
        elif self.o >> 4 == 5 and self.x:
            # Halfword indexed
            self.p += self.rr[self.x] << 1
        elif self.o >= 0x08 and self.o <= 0x1f and self.x:
            # Doubleword indexed
            self.p += self.rr[self.x] << 3
        elif self.x:
            # Word indexed
            self.p += self.rr[self.x] << 2
        self.p &= 0x7ffff

    def execOne(self):
        if self.o == 0x00: # ?.00
            self.trap(0x40)
        elif self.o == 0x01: # ?.01
            self.trap(0x40)
        elif self.o == 0x02: # LCFI
            if self.r & 2:
                self.cc = (self.d >> 4) & 0xf
                self.ff = self.d & 0x7
        elif self.o == 0x03: # ?.03
            self.trap(0x40)
        elif self.o == 0x04: # CAL1
            self.trap(0x40)
        elif self.o == 0x05: # CAL2
            self.trap(0x40)
        elif self.o == 0x06: # CAL3
            self.trap(0x40)
        elif self.o == 0x07: # CAL4
            self.trap(0x40)
        elif self.o == 0x08: # PLW
            self.trap(0x40)
        elif self.o == 0x09: # PSW
            self.trap(0x40)
        elif self.o == 0x0a: # PLM
            self.trap(0x40)
        elif self.o == 0x0b: # PSM
            self.trap(0x40)
        elif self.o == 0x0c: # ?.0C
            self.trap(0x40)
        elif self.o == 0x0d: # ?.0D
            self.trap(0x40)
        elif self.o == 0x0e: # LPSD
            # TODO Flags
            dw0 = self.readW(self.p)
            dw1 = self.readW(self.p + 4) & 0xffc0ffff
            self.cc = (dw0 >> 28) & 0xf
            self.ff = (dw0 >> 24) & 0x7
            self.mask5 = (dw0 >> 19) & 0x1f
            self.psd1 = dw1
            self.q = dw0 & 0x1ffff
            self.p = self.q << 2
        elif self.o == 0x0f: # XPSD
            self.writeW(self.p, (self.cc << 28) | (self.ff << 24) | (self.mask5 << 19) | (self.q & 0x1ffff))
            self.writeW(self.p + 4, self.psd1)
            dw0 = self.readW(self.p + 8)
            dw1 = self.readW(self.p + 12)
            self.cc = (dw0 >> 28) & 0xf
            self.ff = (dw0 >> 24) & 0x7
            self.mask5 = (dw0 >> 19) & 0x1f
            self.psd1 = dw1
            self.q = dw0 & 0x1ffff
            self.p = self.q << 2
        elif self.o == 0x10: # AD
            self.trap(0x40)
        elif self.o == 0x11: # CD
            self.trap(0x40)
        elif self.o == 0x12: # LD
            self.trap(0x40)
        elif self.o == 0x13: # MSP
            self.trap(0x40)
        elif self.o == 0x14: # ?.14
            self.trap(0x40)
        elif self.o == 0x15: # STD
            self.trap(0x40)
        elif self.o == 0x16: # ?.16
            self.trap(0x40)
        elif self.o == 0x17: # ?.17
            self.trap(0x40)
        elif self.o == 0x18: # SD
            self.trap(0x40)
        elif self.o == 0x19: # CLM
            self.trap(0x40)
        elif self.o == 0x1a: # LCD
            self.trap(0x40)
        elif self.o == 0x1b: # LAD
            self.trap(0x40)
        elif self.o == 0x1c: # FSL
            self.trap(0x40)
        elif self.o == 0x1d: # FAL
            self.trap(0x40)
        elif self.o == 0x1e: # FDL
            self.trap(0x40)
        elif self.o == 0x1f: # FML
            self.trap(0x40)
        elif self.o == 0x20: # AI
            a0 = self.a & 0x80000000
            b0 = self.d & 0x80000000
            s = (self.a + self.d) & 0xffffffff
            c0 = s & 0x80000000
            self.cc &= 3
            if ((a0 != 0 or b0 != 0) and ((a0 != 0 and b0 != 0) or
                ((self.a & 0x7fffffff) + (self.d & 0x7fffffff) > 0x7fffffff))):
                self.cc |= 8
            if ((~(a0 ^ b0)) & (c0 ^ a0)) != 0:
                self.cc |= 4
            self.a = s
            self.rr[self.r] = self.a
            self.testa()
        elif self.o == 0x21: # CI
            s = self.a & self.d
            self.cc &= 0xb
            if s:
                self.cc |= 4
            self.a = self.a - self.d
            self.testa()
        elif self.o == 0x22: # LI
            self.a = self.d
            self.rr[self.r] = self.a
            self.testa()
        elif self.o == 0x23: # MI
            self.trap(0x40)
        elif self.o == 0x24: # SF
            self.trap(0x40)
        elif self.o == 0x25: # S
            self.trap(0x40)
        elif self.o == 0x26: # ?.26
            self.trap(0x40)
        elif self.o == 0x27: # ?.27
            self.trap(0x40)
        elif self.o == 0x28: # CVS
            self.trap(0x40)
        elif self.o == 0x29: # CVA
            self.trap(0x40)
        elif self.o == 0x2a: # LM
            self.trap(0x40)
        elif self.o == 0x2b: # STM
            self.trap(0x40)
        elif self.o == 0x2c: # ?.2C
            self.trap(0x40)
        elif self.o == 0x2d: # ?.2D
            self.trap(0x40)
        elif self.o == 0x2e: # WAIT
            self.debug()
            input("WAIT: press enter to continue...")
            self.p = self.q << 2
        elif self.o == 0x2f: # LRP
            self.trap(0x40)
        elif self.o == 0x30: # AW
            s = self.a + self.readW(self.p)
            self.a = s & 0xffffffff
            self.rr[self.r] = self.a
            self.cc &= 7
            if s & 0xf00000000:
                self.cc |= 8
            self.testa()
            self.p = self.q << 2
        elif self.o == 0x31: # CW
            self.d = self.readW(self.p)
            s = self.a & self.d
            self.cc &= 0xb
            if s:
                self.cc |= 4
            s = (self.a - self.d) & 0xffffffff
            self.a = s
            self.testa()
            self.p = self.q << 2
        elif self.o == 0x32: # LW
            self.a = self.readW(self.p)
            self.rr[self.r] = self.a
            self.testa()
            self.p = self.q << 2
        elif self.o == 0x33: # MTW
            self.a = self.r
            if self.a & 0x8:
                self.a |= 0xfffffff0
            self.d = self.readW(self.p)
            s = self.a + self.d
            su = (self.a & 0x7fffffff) + (self.d & 0x7fffffff)
            self.cc &= 3
            a0 = self.a & 0x80000000
            b0 = self.d & 0x80000000
            s0 = s & 0x80000000
            if (~(a0 ^ b0)) & (s0 ^ a0):
                self.cc |= 0x4
            self.a = s & 0xffffffff
            self.writeW(self.p, self.a)
            if ((a0 | b0) & (a0 & b0)) | (su & 0x80000000):
                self.cc |= 8
            self.testa()
            self.p = self.q << 2
        elif self.o == 0x34: # ?.34
            self.trap(0x40)
        elif self.o == 0x35: # STW
            self.writeW(self.p, self.a)
            self.p = self.q << 2
        elif self.o == 0x36: # DW
            self.trap(0x40)
        elif self.o == 0x37: # MW
            self.trap(0x40)
        elif self.o == 0x38: # SW
            self.trap(0x40)
        elif self.o == 0x39: # CLR
            self.trap(0x40)
        elif self.o == 0x3a: # LCW
            self.trap(0x40)
        elif self.o == 0x3b: # LAW
            self.trap(0x40)
        elif self.o == 0x3c: # FSS
            self.trap(0x40)
        elif self.o == 0x3d: # FAS
            self.trap(0x40)
        elif self.o == 0x3e: # FDS
            self.trap(0x40)
        elif self.o == 0x3f: # FMS
            self.trap(0x40)
        elif self.o == 0x40: # TTBS
            self.trap(0x40)
        elif self.o == 0x41: # TBS
            self.trap(0x40)
        elif self.o == 0x42: # ?.42
            self.trap(0x40)
        elif self.o == 0x43: # ?.43
            self.trap(0x40)
        elif self.o == 0x44: # ANLZ
            self.trap(0x40)
        elif self.o == 0x45: # CS
            self.trap(0x40)
        elif self.o == 0x46: # XW
            self.trap(0x40)
        elif self.o == 0x47: # STS
            self.trap(0x40)
        elif self.o == 0x48: # EOR
            self.d = self.readW(self.p)
            self.a = (self.a ^ self.d) & 0xffffffff
            self.rr[self.r] = self.a
            self.testa()
            self.p = self.q << 2
        elif self.o == 0x49: # OR
            self.trap(0x40)
        elif self.o == 0x4a: # LS
            self.trap(0x40)
        elif self.o == 0x4b: # AND
            self.d = self.readW(self.p)
            self.a = (self.a & self.d) & 0xffffffff
            self.rr[self.r] = self.a
            self.testa()
            self.p = self.q << 2
        elif self.o == 0x4c: # SIO
            iop = self.iops[self.p >> 2]
            # TODO registers other than zero mean something
            self.cc = iop.startIO(self.rr[self.r])
            self.p = self.q << 2
        elif self.o == 0x4d: # TIO
            iop = self.iops[self.p >> 2]
            # TODO registers other than zero mean something
            self.cc &= 1
            self.cc |= iop.testIO(self.rr[self.r])
            self.p = self.q << 2
        elif self.o == 0x4e: # TDV
            self.trap(0x40)
        elif self.o == 0x4f: # HIO
            self.trap(0x40)
        elif self.o == 0x50: # AH
            self.trap(0x40)
        elif self.o == 0x51: # CH
            self.trap(0x40)
        elif self.o == 0x52: # LH
            self.trap(0x40)
        elif self.o == 0x53: # MTH
            self.trap(0x40)
        elif self.o == 0x54: # ?.54
            self.trap(0x40)
        elif self.o == 0x55: # STH
            self.trap(0x40)
        elif self.o == 0x56: # DH
            self.trap(0x40)
        elif self.o == 0x57: # MH
            self.trap(0x40)
        elif self.o == 0x58: # SH
            self.trap(0x40)
        elif self.o == 0x59: # ?.59
            self.trap(0x40)
        elif self.o == 0x5a: # LCH
            self.trap(0x40)
        elif self.o == 0x5b: # LAH
            self.trap(0x40)
        elif self.o == 0x5c: # ?.5C
            self.trap(0x40)
        elif self.o == 0x5d: # ?.5D
            self.trap(0x40)
        elif self.o == 0x5e: # ?.5E
            self.trap(0x40)
        elif self.o == 0x5f: # ?.5F
            self.trap(0x40)
        elif self.o == 0x60: # CBS
            self.trap(0x40)
        elif self.o == 0x61: # MBS
            self.trap(0x40)
        elif self.o == 0x62: # ?.62
            self.trap(0x40)
        elif self.o == 0x63: # EBS
            self.trap(0x40)
        elif self.o == 0x64: # BDR
            self.a = (self.a - 1) & 0xffffffff
            self.rr[self.r] = self.a
            if not (self.a & 0x80000000 == 0 and self.a != 0):
                self.p = self.q << 2
        elif self.o == 0x65: # BIR
            self.a = (self.a + 1) & 0xffffffff
            self.rr[self.r] = self.a
            if not self.a & 0x80000000:
                self.p = self.q << 2
        elif self.o == 0x66: # AWM
            self.trap(0x40)
        elif self.o == 0x67: # EXU
            self.trap(0x40)
        elif self.o == 0x68: # BCR
            if (self.cc & self.r) != 0:
                self.p = self.q << 2
        elif self.o == 0x69: # BCS
            if (self.cc & self.r) == 0:
                self.p = self.q << 2
        elif self.o == 0x6a: # BAL
            self.rr[self.r] = self.q
        elif self.o == 0x6b: # INT
            self.trap(0x40)
        elif self.o == 0x6c: # RD
            # 0x0: Read sense switches
            # 0x48: Read interrupt inhibits
            # 0x49: Read snapshot sample register
            # 0x1x0x: Read interrupt control mode 1
            addr = (self.p >> 2) & 0xffff
            if addr == 0:
                self.cc = self.sense_switches
                self.p = self.q << 2
            elif addr == 0x48:
                if self.r:
                    self.rr[self.r] = (self.psd1 >> 24) & 7
                self.p = self.q << 2
            else:
                self.trap(0x40)
        elif self.o == 0x6d: # WD
            # self.debug()
            # TODO more interrupts
            wa = self.p >> 2
            code, group = (wa >> 8) & 7, wa & 0xf
            if code == 1 and group == 0:
                base = 0x52
                mask = 0x8000
                for i in range(12):
                    if self.a & mask:
                        # print(f'Disarm 0x{base+i:x}')
                        self.armed[base + i] = False
                        self.enabled[base + i] = False
                        self.active[base + i] = False
                    mask >>= 1
            if code == 2 and group == 0:
                base = 0x52
                mask = 0x8000
                for i in range(12):
                    if self.a & mask:
                        # print(f'Arm 0x{base+i:x}')
                        self.armed[base + i] = True
                        self.enabled[base + i] = True
                        self.active[base + i] = False
                    mask >>= 1
            self.p = self.q << 2
            if code == 3 and group == 0:
                base = 0x52
                mask = 0x8000
                for i in range(12):
                    if self.a & mask:
                        # print(f'Disarm 0x{base+i:x}')
                        self.armed[base + i] = False
                        self.enabled[base + i] = False
                        self.active[base + i] = False
                    mask >>= 1
            if code == 4 and group == 0:
                base = 0x52
                mask = 0x8000
                for i in range(12):
                    if self.a & mask:
                        # print(f'Arm 0x{base+i:x}')
                        self.armed[base + i] = True
                        self.enabled[base + i] = True
                        self.active[base + i] = False
                    mask >>= 1
            if wa & 0xfff8 == 0x0030:
                print(f'0x{(self.q-1):x} Set int. inhibits')
                mask = 4
                psd_bit = 1 << 26
                while mask:
                    if wa & mask:
                        self.psd1 |= psd_bit
                    mask >>= 1
                    psd_bit >>= 1
            if wa & 0xfff8 == 0x0020:
                print('Reset int. inhibits')
                mask = 4
                psd_bit = 1 << 26
                while mask:
                    if wa & mask:
                        self.psd1 &= ~psd_bit
                    mask >>= 1
                    psd_bit >>= 1
        elif self.o == 0x6e: # AIO
            self.trap(0x40)
        elif self.o == 0x6f: # MMC
            self.trap(0x40)
        elif self.o == 0x70: # LCF
            byte = self.readB(self.p)
            if self.r & 2:
                self.cc = (byte >> 4) & 0xf
                self.ff = byte & 0x7
            self.p = self.q << 2
        elif self.o == 0x71: # CB
            self.d = self.readB(self.p)
            self.cc &= 8
            if self.a & self.d:
                self.cc |= 4
            s = self.a - self.d
            self.a = s
            self.testa()
            self.p = self.q << 2
        elif self.o == 0x72: # LB
            self.a = self.readB(self.p)
            self.rr[self.r] = self.a
            self.testa()
            self.p = self.q << 2
        elif self.o == 0x73: # MTB
            self.a = self.r
            if self.a & 0x8:
                self.a |= 0xf0
            self.d = self.readB(self.p)
            s = self.a + self.d
            self.a = s & 0xff
            self.writeB(self.p, self.a)
            self.cc &= 3
            if s & 0x100:
                self.cc |= 8
            self.testa()
            self.p = self.q << 2
        elif self.o == 0x74: # STFC
            self.writeB(self.p, (self.cc << 4) | self.ff)
            self.p = self.q << 2
        elif self.o == 0x75: # STB
            self.writeB(self.p, self.a)
            self.p = self.q << 2
        elif self.o == 0x76: # PACK
            self.trap(0x40)
        elif self.o == 0x77: # UNPK
            self.trap(0x40)
        elif self.o == 0x78: # DS
            self.trap(0x40)
        elif self.o == 0x79: # DA
            self.trap(0x40)
        elif self.o == 0x7a: # DD
            self.trap(0x40)
        elif self.o == 0x7b: # DM
            self.trap(0x40)
        elif self.o == 0x7c: # DSA
            self.trap(0x40)
        elif self.o == 0x7d: # DC
            self.trap(0x40)
        elif self.o == 0x7e: # DL
            self.trap(0x40)
        elif self.o == 0x7f: # DST
            self.trap(0x40)

    def trap(self, addr):
        # for ia, c in self.ia_trace[-10:]:
        #     print(f'0x{ia:x}: 0x{c:08x} {OPCODES[(c >> 24) & 0x7f]}')
        # raise Exception(f'Trap 0x{addr:02x} - q: 0x{self.q-1:x}, {OPCODES[self.o]} 0x{self.iword:08x}')
        self.doTrap(0x40)

    def debug(self):
        print(f'0x{(self.q-1):x}: 0x{self.iword:08x} {OPCODES[self.o]} a: 0x{self.a:08x} d: 0x{self.d:08x} p: 0x{self.p>>2:08x} | {self.p&3} cc: 0x{self.cc:x}')
        result = ''
        for i in range(8):
            result += f' r{i:2d}: 0x{self.rr[i]:08x}'
        print(result)
        result = ''
        for i in range(8, 16, 1):
            result += f' r{i:2d}: 0x{self.rr[i]:08x}'
        print(result)

if __name__ == '__main__':
    memory = Memory()
    iops = [None, CardReader(memory, '../programs/sighcp')]
    cpu = CPU(memory, iops)
    cpu.run()
