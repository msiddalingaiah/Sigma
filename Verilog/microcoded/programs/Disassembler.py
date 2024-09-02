
OPCODES = ['?.00', '?.01', 'LCFI', '?.03', 'CAL1', 'CAL2', 'CAL3', 'CAL4', 'PLW', 'PSW', 'PLM', 'PSM', '?.0C',
           '?.0D', 'LPSD', 'XPSD', 'AD', 'CD', 'LD', 'MSP', '?.14', 'STD', '?.16', '?.17', 'SD', 'CLM', 'LCD',
           'LAD', 'FSL', 'FAL', 'FDL', 'FML', 'AI', 'CI', 'LI', 'MI', 'SF', 'S', '?.26', '?.27', 'CVS', 'CVA',
           'LM', 'STM', '?.2C', '?.2D', 'WAIT', 'LRP', 'AW', 'CW', 'LW', 'MTW', '?.34', 'STW', 'DW', 'MW', 'SW',
           'CLR', 'LCW', 'LAW', 'FSS', 'FAS', 'FDS', 'FMS', 'TTBS', 'TBS', '?.42', '?.43', 'ANLZ', 'CS', 'XW',
           'STS', 'EOR', 'OR', 'LS', 'AND', 'SIO', 'TIO', 'TDV', 'HIO', 'AH', 'CH', 'LH', 'MTH', '?.54', 'STH',
           'DH', 'MH', 'SH', '?.59', 'LCH', 'LAH', '?.5C', '?.5D', '?.5E', '?.5F', 'CBS', 'MBS', '?.62', 'EBS',
           'BDR', 'BIR', 'AWM', 'EXU', 'BCR', 'BCS', 'BAL', 'INT', 'RD', 'WD', 'AIO', 'MMC', 'LCF', 'CB', 'LB',
           'MTB', 'STFC', 'STB', 'PACK', 'UNPK', 'DS', 'DA', 'DD', 'DM', 'DSA', 'DC', 'DL', 'DST']

def disassemble(filename, pc):
    with open(filename, 'rb') as f:
        bytes = f.read()
        i = 0
        while i < 2*88:
            if i % 88 == 0:
                print()
            word = bytes[i]<<24 | bytes[i+1]<<16 | bytes[i+2]<<8 | bytes[i+3]
            i += 4
            o = (word >> 24) & 0x7f
            r = (word >> 20) & 0xf
            cf = f'{OPCODES[o]},{r}'
            if (o & 0x1c) == 0:
                imm = word & 0xfffff
                print(f'{pc:08x}: {word:08x}    {cf:7s}    {imm} (0x{imm:x})')
            else:
                star = ''
                if word & 0x80000000:
                    star = '*'
                x = (word >> 17) & 7
                x_str = ''
                if x:
                    x_str = f',{x}'
                addr = word & 0x1ffff
                print(f'{pc:08x}: {word:08x}    {cf:7s}    {star}0x{addr:x}{x_str}')
            pc += 1

if __name__ == '__main__':
    disassemble('programs/sighcp', 0x2a)