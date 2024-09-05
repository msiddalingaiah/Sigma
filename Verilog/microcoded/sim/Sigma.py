
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
            print(f'CardReader: command addr 0x{addr:x} read {n} bytes to word address 0x{ba>>2:x} + {ba&3} bytes, flags: 0x{c1>>24:02x}')
            while n > 0:
                self.memory.writeB(ba >> 2, ba & 3, self.bytes[self.index])
                ba += 1
                self.index += 1
                n -= 1
        else:
            raise Exception(f'Unexpected IOP command: 0x{c0:08x}')

    def testIO(self, daddr):
        if self.index >= len(self.bytes):
            return 0x40 # busy
        return 0

class CPU(object):
    def __init__(self, memory, iops):
        self.a = 0
        self.c = 0
        self.d = 0
        self.o = 0
        self.p = 0x26 << 2
        self.q = 0
        self.r = 0
        self.x = 0
        self.rr = [0]*16
        self.memory = memory
        self.iops = iops

    def readW(self, addr):
        if addr < 16:
            return self.rr[addr]
        return self.memory.readW(addr)

    def writeW(self, addr, value):
        if addr < 16:
            self.rr[addr] = value
        self.memory.writeW(addr, value)

    def run(self):
        self.ende()
        while True:
            self.execOne()
            self.ende()

    def ende(self):
        self.c = self.readW(self.p >> 2)
        self.iword = self.c
        self.cc = 0
        self.p += 4
        self.q = self.p >> 2
        self.o = (self.c >> 24) & 0x7f
        self.r = (self.c >> 20) & 0xf
        if (self.o & 0x1c) == 0:
            if self.c & 0x80000000:
                self.trap(0x40)
            self.d = self.c & 0xfffff
            return
        self.x = (self.c >> 17) & 7
        if self.c & 0x80000000:
            self.c = self.readW(self.c & 0x1ffff)
        self.p = (self.c & 0x1ffff) << 2
        # p contains effective BYTE address
        if self.o >> 4 == 7 and self.x:
            self.p += self.rr[self.x]
        elif (self.o ^ 0x40) >> 4 == 7 and self.x:
            self.p += self.rr[self.x] << 1
        elif self.x:
            self.p += self.rr[self.x] << 2

    def execOne(self):
        if self.o == 0x00: # ?.00
            self.trap(0x40)
        elif self.o == 0x01: # ?.01
            self.trap(0x40)
        elif self.o == 0x02: # LCFI
            self.trap(0x40)
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
            self.trap(0x40)
        elif self.o == 0x0f: # XPSD
            dw0 = self.readW(self.p >> 2)
            dw1 = self.readW((self.p >> 2) + 1)
            print(f'XPSD dw0: 0x{dw0:08x}')
            print(f'XPSD dw1: 0x{dw1:08x}')
            self.trap(0x40)
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
            self.trap(0x40)
        elif self.o == 0x21: # CI
            self.trap(0x40)
        elif self.o == 0x22: # LI
            self.rr[self.r] = self.d
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
            self.trap(0x40)
        elif self.o == 0x2f: # LRP
            self.trap(0x40)
        elif self.o == 0x30: # AW
            self.trap(0x40)
        elif self.o == 0x31: # CW
            self.trap(0x40)
        elif self.o == 0x32: # LW
            self.rr[self.r] = self.readW(self.p >> 2)
            self.p = self.q << 2
        elif self.o == 0x33: # MTW
            self.trap(0x40)
        elif self.o == 0x34: # ?.34
            self.trap(0x40)
        elif self.o == 0x35: # STW
            self.writeW(self.p >> 2, self.rr[self.r])
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
            self.trap(0x40)
        elif self.o == 0x49: # OR
            self.trap(0x40)
        elif self.o == 0x4a: # LS
            self.trap(0x40)
        elif self.o == 0x4b: # AND
            self.trap(0x40)
        elif self.o == 0x4c: # SIO
            iop = self.iops[self.p >> 2]
            # TODO registers other than zero mean something
            iop.startIO(self.rr[self.r])
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
            self.rr[self.r] -= 1
            if self.rr[self.r] <= 0:
                self.p = self.q << 2
        elif self.o == 0x65: # BIR
            self.rr[self.r] += 1
            if self.rr[self.r] >= 0:
                self.p = self.q << 2
        elif self.o == 0x66: # AWM
            self.trap(0x40)
        elif self.o == 0x67: # EXU
            self.trap(0x40)
        elif self.o == 0x68: # BCR
            if self.cc & self.r != 0:
                self.p = self.q << 2
        elif self.o == 0x69: # BCS
            if self.cc & self.r == 0:
                self.p = self.q << 2
        elif self.o == 0x6a: # BAL
            self.trap(0x40)
        elif self.o == 0x6b: # INT
            self.trap(0x40)
        elif self.o == 0x6c: # RD
            self.trap(0x40)
        elif self.o == 0x6d: # WD
            self.trap(0x40)
        elif self.o == 0x6e: # AIO
            self.trap(0x40)
        elif self.o == 0x6f: # MMC
            self.trap(0x40)
        elif self.o == 0x70: # LCF
            self.trap(0x40)
        elif self.o == 0x71: # CB
            self.trap(0x40)
        elif self.o == 0x72: # LB
            self.trap(0x40)
        elif self.o == 0x73: # MTB
            self.trap(0x40)
        elif self.o == 0x74: # STFC
            self.trap(0x40)
        elif self.o == 0x75: # STB
            self.trap(0x40)
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
        raise Exception(f'Trap 0x{addr:02x} - q: 0x{self.q-1:x}, {OPCODES[self.o]} 0x{self.iword:08x}')

if __name__ == '__main__':
    memory = Memory()
    iops = [None, CardReader(memory, 'programs/sighcp')]
    cpu = CPU(memory, iops)
    cpu.run()