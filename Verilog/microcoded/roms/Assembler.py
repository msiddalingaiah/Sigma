
import re

PATTERN = re.compile(r'\s+')
OPCODES = ['?.00', '?.01', 'LCFI', '?.03', 'CAL1', 'CAL2', 'CAL3', 'CAL4', 'PLW', 'PSW', 'PLM', 'PSM', '?.0C',
           '?.0D', 'LPSD', 'XPSD', 'AD', 'CD', 'LD', 'MSP', '?.14', 'STD', '?.16', '?.17', 'SD', 'CLM', 'LCD',
           'LAD', 'FSL', 'FAL', 'FDL', 'FML', 'AI', 'CI', 'LI', 'MI', 'SF', 'S', '?.26', '?.27', 'CVS', 'CVA',
           'LM', 'STM', '?.2C', '?.2D', 'WAIT', 'LRP', 'AW', 'CW', 'LW', 'MTW', '?.34', 'STW', 'DW', 'MW', 'SW',
           'CLR', 'LCW', 'LAW', 'FSS', 'FAS', 'FDS', 'FMS', 'TTBS', 'TBS', '?.42', '?.43', 'ANLZ', 'CS', 'XW',
           'STS', 'EOR', 'OR', 'LS', 'AND', 'SIO', 'TIO', 'TDV', 'HIO', 'AH', 'CH', 'LH', 'MTH', '?.54', 'STH',
           'DH', 'MH', 'SH', '?.59', 'LCH', 'LAH', '?.5C', '?.5D', '?.5E', '?.5F', 'CBS', 'MBS', '?.62', 'EBS',
           'BDR', 'BIR', 'AWM', 'EXU', 'BCR', 'BCS', 'BAL', 'INT', 'RD', 'WD', 'AIO', 'MMC', 'LCF', 'CB', 'LB',
           'MTB', 'STFC', 'STB', 'PACK', 'UNPK', 'DS', 'DA', 'DD', 'DM', 'DSA', 'DC', 'DL', 'DST']
OPCODE_MAP = {
    '?.00': 0x0,'?.01': 0x1,'LCFI': 0x2,'?.03': 0x3,'CAL1': 0x4,'CAL2': 0x5,'CAL3': 0x6,'CAL4': 0x7,'PLW': 0x8,
    'PSW': 0x9,'PLM': 0xa,'PSM': 0xb,'?.0C': 0xc,'?.0D': 0xd,'LPSD': 0xe,'XPSD': 0xf,'AD': 0x10,'CD': 0x11,
    'LD': 0x12,'MSP': 0x13,'?.14': 0x14,'STD': 0x15,'?.16': 0x16,'?.17': 0x17,'SD': 0x18,'CLM': 0x19,'LCD': 0x1a,
    'LAD': 0x1b,'FSL': 0x1c,'FAL': 0x1d,'FDL': 0x1e,'FML': 0x1f,'AI': 0x20,'CI': 0x21,'LI': 0x22,'MI': 0x23,
    'SF': 0x24,'S': 0x25,'?.26': 0x26,'?.27': 0x27,'CVS': 0x28,'CVA': 0x29,'LM': 0x2a,'STM': 0x2b,'?.2C': 0x2c,
    '?.2D': 0x2d,'WAIT': 0x2e,'LRP': 0x2f,'AW': 0x30,'CW': 0x31,'LW': 0x32,'MTW': 0x33,'?.34': 0x34,'STW': 0x35,
    'DW': 0x36,'MW': 0x37,'SW': 0x38,'CLR': 0x39,'LCW': 0x3a,'LAW': 0x3b,'FSS': 0x3c,'FAS': 0x3d,'FDS': 0x3e,
    'FMS': 0x3f,'TTBS': 0x40,'TBS': 0x41,'?.42': 0x42,'?.43': 0x43,'ANLZ': 0x44,'CS': 0x45,'XW': 0x46,'STS': 0x47,
    'EOR': 0x48,'OR': 0x49,'LS': 0x4a,'AND': 0x4b,'SIO': 0x4c,'TIO': 0x4d,'TDV': 0x4e,'HIO': 0x4f,'AH': 0x50,
    'CH': 0x51,'LH': 0x52,'MTH': 0x53,'?.54': 0x54,'STH': 0x55,'DH': 0x56,'MH': 0x57,'SH': 0x58,'?.59': 0x59,
    'LCH': 0x5a,'LAH': 0x5b,'?.5C': 0x5c,'?.5D': 0x5d,'?.5E': 0x5e,'?.5F': 0x5f,'CBS': 0x60,'MBS': 0x61,
    '?.62': 0x62,'EBS': 0x63,'BDR': 0x64,'BIR': 0x65,'AWM': 0x66,'EXU': 0x67,'BCR': 0x68,'BCS': 0x69,
    'BAL': 0x6a,'INT': 0x6b,'RD': 0x6c,'WD': 0x6d,'AIO': 0x6e,'MMC': 0x6f,'LCF': 0x70,'CB': 0x71,'LB': 0x72,
    'MTB': 0x73,'STFC': 0x74,'STB': 0x75,'PACK': 0x76,'UNPK': 0x77,'DS': 0x78,'DA': 0x79,'DD': 0x7a,'DM': 0x7b,
    'DSA': 0x7c,'DC': 0x7d,'DL': 0x7e,'DST': 0x7f
}

class Directive(object):
    def __init__(self, line, lineNumber):
        self.lineNumber = lineNumber
        cols = PATTERN.split(line)
        if len(cols) != 3:
            raise Exception(f'line {lineNumber}: Expecting 3 columns, found {len(cols)}')
        self.lf, self.cf, self.af = cols
        self.pc = 0

    def __str__(self):
        op, reg = self.cf.split(',')
        op, reg = OPCODE_MAP[op], int(reg)
        af = int(self.af)
        word = (op << 24) | (reg << 20) | af
        return f'{word:08x}'

if __name__ == '__main__':
    print(Directive(' LI,1 3', 0))
    print(Directive('loop WD,2 0', 0))
