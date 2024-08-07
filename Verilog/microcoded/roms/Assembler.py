
import re
from Compiler import *

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

ESCAPE_CHARS = {'n': '\n', 'r': '\r', 't': '\t', 'f': '\f'}

class AParser(object):
    def __init__(self):
        patterns = []
        patterns.append(Pattern('ID', r'[a-zA-Z_][a-zA-Z0-9_\.]*'))
        patterns.append(Pattern('INT', r'(0x)?[0-9a-fA-F]+'))
        patterns.append(Pattern(';', r'\;'))
        patterns.append(Pattern(',', r'\,'))
        patterns.append(Pattern(':', r'\:'))
        patterns.append(Pattern('{', r'\{'))
        patterns.append(Pattern('}', r'\}'))
        patterns.append(Pattern('[', r'\['))
        patterns.append(Pattern(']', r'\]'))
        patterns.append(Pattern('(', r'\('))
        patterns.append(Pattern(')', r'\)'))
        patterns.append(Pattern('+', r'\+'))
        patterns.append(Pattern('-', r'\-'))
        patterns.append(Pattern('*', r'\*'))
        patterns.append(Pattern('/', r'\/'))
        patterns.append(Pattern('<<', r'\<\<'))
        patterns.append(Pattern('>>', r'\>\>'))
        patterns.append(Pattern('<=', r'\<\='))
        patterns.append(Pattern('>=', r'\>\='))
        patterns.append(Pattern('==', r'\=\='))
        patterns.append(Pattern('!=', r'\!\='))
        patterns.append(Pattern('&', r'\&'))
        patterns.append(Pattern('|', r'\|'))
        patterns.append(Pattern('^', r'\^'))
        patterns.append(Pattern('=', r'\='))
        patterns.append(Pattern('<', r'\<'))
        patterns.append(Pattern('>', r'\>'))
        patterns.append(Pattern('%', r'\%'))
        patterns.append(Pattern(',', r'\,'))
        patterns.append(Pattern('!', r'\!'))
        patterns.append(Pattern("'", r"'(?:[^'\\]|\\.)'"))
        patterns.append(Pattern('"', r'"(?:[^"\\]|\\.)*"'))
        self.sc = Scanner(patterns)
        self.prec = [('&','|','^'), ('>>', '<<'), ('==','!=','>','<','>=','<='), ('+','-'), ('*','/','%')]

    def parse(self, input, lineNumber):
        tree = Tree('stat')
        inputs = input.split(';')
        input = inputs[0]
        if len(input.strip()) == 0:
            return tree
        fields = input.split('    ')
        for i, fn in enumerate(['lf', 'cf', 'af']):
            if i < len(fields):
                self.sc.setInput(fields[i])
                tree.add(self.parseExpList(fn))
            else:
                tree.add(Tree(fn))
        if not self.sc.atEnd():
            raise Exception(f'line {lineNumber}: Unexpected input: %s' % self.sc.terminal)
        if len(tree[1]) == 0:
            raise Exception(f'line {lineNumber}: Command field cannot be empty')
        if len(inputs) > 1:
            comment = ';'.join(inputs[1:]).strip()
            tree.add(Tree('comment', Terminal('"', comment, lineNumber)))
        return tree

    def parseExpList(self, name):
        tree = Tree(name)
        if self.sc.atEnd():
            return tree
        if name == 'af' and self.sc.matches('*'):
            tree.add(Tree(self.sc.terminal))
        tree.add(self.parseExp())
        while self.sc.matches(','):
            tree.add(self.parseExp())
        return tree

    def parseExp(self, index=0):
        result = self.parseTail(index)
        while self.sc.matches(*self.prec[index]):
            result = Tree(self.sc.terminal, result, self.parseTail(index))
        return result

    def parseTail(self, index):
        if index >= len(self.prec)-1:
            return self.parsePrim()
        return self.parseExp(index + 1)

    def escape(self, string):
        result = ''
        esc = False
        for c in string:
            if esc:
                result += ESCAPE_CHARS.get(c, c)
                esc = False
            elif c == '\\':
                esc = True
            else:
                result += c
        return result

    def parsePrim(self):
        if self.sc.matches('('):
            tree = self.parseExp()
            self.sc.expect(')')
            return tree
        if self.sc.matches('-'):
            return Tree(Terminal('NEG', '-'), self.parsePrim())
        if self.sc.matches('!'):
            return Tree(self.sc.terminal, self.parsePrim())
        if self.sc.matches('INT'):
            t = self.sc.terminal
            if t.value.startswith('0x'):
                t.value = int(t.value[2:], 16)
            else:
                t.value = int(t.value)
            return Tree(t)
        if self.sc.matches("'"):
            t = self.sc.terminal
            t.name = 'INT'
            t.value = ord(self.escape(t.value[1:-1]))
            return Tree(t)
        if self.sc.matches('"'):
            t = self.sc.terminal
            string = self.escape(t.value[1:-1])
            t.value = ''
            result = Tree(t)
            for c in string:
                result.add(ord(c))
            return result
        return Tree(self.sc.expect('ID'))

class Generator(object):
    def __init__(self, defs, tree, lineNumber, pc):
        self.defs = defs
        self.tree = tree
        self.lineNumber = lineNumber
        self.pc = pc

    def getWords(self):
        raise Exception(f'line: {self.lineNumber}: Unimplemented abstract method.')
    
    @staticmethod
    def new(defs, tree, lineNumber, pc):
        # TODO check immediate mode
        if tree[1][0].value.value in OPCODE_MAP:
            return ImmInstruction(defs, tree, lineNumber, pc)

class ImmInstruction(Generator):
    def __init__(self, defs, tree, lineNumber, pc):
        super().__init__(defs, tree, lineNumber, pc)

    def getWords(self):
        cf = self.tree[1]
        if len(cf) != 2:
            raise Exception(f'line: {self.lineNumber}: One register is required.')
        af = self.tree[2]
        if len(af) != 1:
            raise Exception(f'line: {self.lineNumber}: One operand is required.')
        op = OPCODE_MAP[cf[0].value.value]
        # TODO evaluate expression(s)
        reg = int(cf[1].value.value)
        arg = int(af[0].value.value)
        word = (op << 24) | (reg << 20) | (arg & 0xfffff)
        return ['%08x' % word]

if __name__ == '__main__':
    p = AParser()
    tree = p.parse('    LI,1    35', 1)
    inst = Generator.new(None, tree, 1, 0)
    for w in inst.getWords():
        print(w)
