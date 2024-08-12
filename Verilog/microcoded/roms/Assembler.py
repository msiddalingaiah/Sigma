
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
        fields = re.split('    +', input)
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
            t.value = self.escape(t.value[1:-1])
            return Tree(t)
        return Tree(self.sc.expect('ID'))

class Defines(object):
    def __init__(self):
        self.constants = {}

    def eval(self, tree):
        if tree.value.name == 'INT':
            return tree.value.value
        if tree.value.name == 'ID':
            name = tree.value.value
            if name not in self.constants:
                raise Exception(f"line {tree.value.lineNumber}, No such constant '{name}'")
            return self.constants[name]
        op = tree.value.name
        a = self.eval(tree.children[0])
        if op == 'NEG':
            return -a
        b = self.eval(tree.children[1])
        if op == '+':
            return a + b
        if op == '-':
            return a - b
        if op == '*':
            return a * b
        if op == '/':
            return a / b
        raise Exception(f"line {tree.value.lineNumber}, Unknown operator '{op}'")

class Directive(object):
    def __init__(self, defs, line, tree, lineNumber, pc):
        self.defs = defs
        self.line = line
        self.tree = tree
        self.lineNumber = lineNumber
        self.pc = pc

    def getLabels(self):
        labels = []
        for t in self.tree[0]:
            if t.value.name != 'ID':
                raise Exception(f'line {self.lineNumber}: expected label, found {t.value.value}')
            labels.append(t.value.value)
        return labels

    def getNextPC(self):
        return self.pc

    def getWords(self):
        return []
    
    @staticmethod
    def new(defs, line, tree, lineNumber, pc):
        lf, cf, af = tree[0],tree[1], tree[2]
        cf0 = cf[0].value.value.upper()
        if cf0 == 'DEF':
            return DEF(defs, line, tree, lineNumber, pc)
        if cf0 == 'TEXTC':
            return TextC(defs, line, tree, lineNumber, pc)
        if cf0 == 'ORG':
            return ORG(defs, line, tree, lineNumber, pc)
        if cf0 in OPCODE_MAP:
            if (OPCODE_MAP[cf0] & 0x1c) == 0:
                return ImmInstruction(defs, line, tree, lineNumber, pc)
            return Instruction(defs, line, tree, lineNumber, pc)

class DEF(Directive):
    def __init__(self, defs, line, tree, lineNumber, pc):
        super().__init__(defs, line, tree, lineNumber, pc)
        value = defs.eval(tree[2][0])
        for label in self.getLabels():
            defs.constants[label] = value

class TextC(Directive):
    def __init__(self, defs, line, tree, lineNumber, pc):
        super().__init__(defs, line, tree, lineNumber, pc)
        af = tree[2]
        if len(af) != 1 or af[0].value.name != '"':
            raise Exception(f'line {lineNumber}: one string argument expected')
        self.value = tree[2][0].value.value

    def getNextPC(self):
        for label in self.getLabels():
            self.defs.constants[label] = self.pc
        return self.pc + ((len(self.value) + 4) >> 2)

    def getWords(self):
        length = len(self.value)
        padLen = (4 - ((len(self.value)+1) & 3)) & 3
        value = self.value + (' '*(padLen))
        words = []
        words.append(f'{length:02x}{ord(value[0]):02x}{ord(value[1]):02x}{ord(value[2]):02x} // {self.pc:04x} {self.line}')
        i = 3
        while i < length:
            words.append(f'{ord(value[i+0]):02x}{ord(value[i+1]):02x}{ord(value[i+2]):02x}{ord(value[i+3]):02x}')
            i += 4
        return words

class Instruction(Directive):
    def __init__(self, defs, line, tree, lineNumber, pc):
        super().__init__(defs, line, tree, lineNumber, pc)

    def getNextPC(self):
        self.setLabels()
        return self.pc + 1

    def setLabels(self):
        for label in self.getLabels():
            self.defs.constants[label] = self.pc

    def getWords(self):
        cf = self.tree[1]
        if len(cf) != 2:
            raise Exception(f'line: {self.lineNumber}: One register is required.')
        op = OPCODE_MAP[cf[0].value.value]
        reg = self.defs.eval(cf[1])
        word = (op << 24) | (reg << 20)

        af = self.tree[2]
        index = 0
        if index >= len(af):
            raise Exception(f'line {self.lineNumber}: missing address')
        if af[index].value.name == '*':
            word |= 0x80000000
            index += 1
        if index >= len(af):
            raise Exception(f'line {self.lineNumber}: missing address')
        addr = self.defs.eval(af[index])
        index += 1
        word |= addr & 0x1ffff
        if index < len(af):
            ix = self.defs.eval(af[index])
            index += 1
            word |= (ix & 7) << 17
        return [f'{word:08x} // {self.pc:04x} {self.line}']

class ImmInstruction(Instruction):
    def __init__(self, defs, line, tree, lineNumber, pc):
        super().__init__(defs, line, tree, lineNumber, pc)

    def getWords(self):
        cf = self.tree[1]
        if len(cf) != 2:
            raise Exception(f'line: {self.lineNumber}: One register is required.')
        af = self.tree[2]
        if len(af) != 1:
            raise Exception(f'line: {self.lineNumber}: One operand is required.')
        op = OPCODE_MAP[cf[0].value.value]
        reg = self.defs.eval(cf[1])
        arg = self.defs.eval(af[0])
        word = (op << 24) | (reg << 20) | (arg & 0xfffff)
        return [f'{word:08x} // {self.pc:04x} {self.line}']

class ORG(Directive):
    def __init__(self, defs, line, tree, lineNumber, pc):
        super().__init__(defs, line, tree, lineNumber, pc)
        self.af = tree[2]
        if len(self.af) != 1:
            raise Exception(f'line {lineNumber}: address argument expected')

    def getNextPC(self):
        self.pc = self.defs.eval(self.af[0])
        for label in self.getLabels():
            self.defs.constants[label] = self.pc
        return self.pc

MAX_WORD_LEN = 128

class Assembler(object):
    def __init__(self):
        self.defs = Defines()
    
    def parse(self, fasm):
        p = AParser()
        self.genList = []
        pc = 0
        with open(fasm) as f:
            lines = f.readlines()
            for lineNumber, line in enumerate(lines):
                lineNumber += 1
                line = line.replace('\n', '')
                tree = p.parse(line, lineNumber)
                if len(tree) >= 3:
                    gen = Directive.new(self.defs, line, tree, lineNumber, pc)
                    pc = gen.getNextPC()
                    self.genList.append(gen)

    def write(self, fout):
        outputWords = ['00000000']*MAX_WORD_LEN
        for gen in self.genList:
            words = gen.getWords()
            for i, w in enumerate(words):
                outputWords[gen.pc + i] = w
        with open(fout, 'wt') as f:
            for word in outputWords:
                f.write(word + '\n')

import sys

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('usage: python Assembler.py <asm-file> <code-file>')
        sys.exit(1)

    asm = Assembler()
    asm.parse(sys.argv[1])
    asm.write(sys.argv[2])
