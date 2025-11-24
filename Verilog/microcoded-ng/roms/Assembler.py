
import re
from Compiler import Terminal, Tree, Pattern

OPCODES = ['NAO00', 'NAO01', 'LCFI', 'NAO03', 'CAL1', 'CAL2', 'CAL3', 'CAL4', 'PLW', 'PSW', 'PLM', 'PSM', 'NAO0C',
           'NAO0D', 'LPSD', 'XPSD', 'AD', 'CD', 'LD', 'MSP', 'NAO14', 'STD', 'NAO16', 'NAO17', 'SD', 'CLM', 'LCD',
           'LAD', 'FSL', 'FAL', 'FDL', 'FML', 'AI', 'CI', 'LI', 'MI', 'SF', 'S', 'NAO26', 'NAO27', 'CVS', 'CVA',
           'LM', 'STM', 'NAO2C', 'NAO2D', 'WAIT', 'LRP', 'AW', 'CW', 'LW', 'MTW', 'NAO34', 'STW', 'DW', 'MW', 'SW',
           'CLR', 'LCW', 'LAW', 'FSS', 'FAS', 'FDS', 'FMS', 'TTBS', 'TBS', 'NAO42', 'NAO43', 'ANLZ', 'CS', 'XW',
           'STS', 'EOR', 'OR', 'LS', 'AND', 'SIO', 'TIO', 'TDV', 'HIO', 'AH', 'CH', 'LH', 'MTH', 'NAO54', 'STH',
           'DH', 'MH', 'SH', 'NAO59', 'LCH', 'LAH', 'NAO5C', 'NAO5D', 'NAO5E', 'NAO5F', 'CBS', 'MBS', 'NAO62', 'EBS',
           'BDR', 'BIR', 'AWM', 'EXU', 'BCR', 'BCS', 'BAL', 'INT', 'RD', 'WD', 'AIO', 'MMC', 'LCF', 'CB', 'LB',
           'MTB', 'STFC', 'STB', 'PACK', 'UNPK', 'DS', 'DA', 'DD', 'DM', 'DSA', 'DC', 'DL', 'DST']

OPCODE_MAP = {
    'NAO00': 0x0,'NAO01': 0x1,'LCFI': 0x2,'NAO03': 0x3,'CAL1': 0x4,'CAL2': 0x5,'CAL3': 0x6,'CAL4': 0x7,'PLW': 0x8,
    'PSW': 0x9,'PLM': 0xa,'PSM': 0xb,'NAO0C': 0xc,'NAO0D': 0xd,'LPSD': 0xe,'XPSD': 0xf,'AD': 0x10,'CD': 0x11,
    'LD': 0x12,'MSP': 0x13,'NAO14': 0x14,'STD': 0x15,'NAO16': 0x16,'NAO17': 0x17,'SD': 0x18,'CLM': 0x19,'LCD': 0x1a,
    'LAD': 0x1b,'FSL': 0x1c,'FAL': 0x1d,'FDL': 0x1e,'FML': 0x1f,'AI': 0x20,'CI': 0x21,'LI': 0x22,'MI': 0x23,
    'SF': 0x24,'S': 0x25,'NAO26': 0x26,'NAO27': 0x27,'CVS': 0x28,'CVA': 0x29,'LM': 0x2a,'STM': 0x2b,'NAO2C': 0x2c,
    'NAO2D': 0x2d,'WAIT': 0x2e,'LRP': 0x2f,'AW': 0x30,'CW': 0x31,'LW': 0x32,'MTW': 0x33,'NAO34': 0x34,'STW': 0x35,
    'DW': 0x36,'MW': 0x37,'SW': 0x38,'CLR': 0x39,'LCW': 0x3a,'LAW': 0x3b,'FSS': 0x3c,'FAS': 0x3d,'FDS': 0x3e,
    'FMS': 0x3f,'TTBS': 0x40,'TBS': 0x41,'NAO42': 0x42,'NAO43': 0x43,'ANLZ': 0x44,'CS': 0x45,'XW': 0x46,'STS': 0x47,
    'EOR': 0x48,'OR': 0x49,'LS': 0x4a,'AND': 0x4b,'SIO': 0x4c,'TIO': 0x4d,'TDV': 0x4e,'HIO': 0x4f,'AH': 0x50,
    'CH': 0x51,'LH': 0x52,'MTH': 0x53,'NAO54': 0x54,'STH': 0x55,'DH': 0x56,'MH': 0x57,'SH': 0x58,'NAO59': 0x59,
    'LCH': 0x5a,'LAH': 0x5b,'NAO5C': 0x5c,'NAO5D': 0x5d,'NAO5E': 0x5e,'NAO5F': 0x5f,'CBS': 0x60,'MBS': 0x61,
    'NAO62': 0x62,'EBS': 0x63,'BDR': 0x64,'BIR': 0x65,'AWM': 0x66,'EXU': 0x67,'BCR': 0x68,'BCS': 0x69,
    'BAL': 0x6a,'INT': 0x6b,'RD': 0x6c,'WD': 0x6d,'AIO': 0x6e,'MMC': 0x6f,'LCF': 0x70,'CB': 0x71,'LB': 0x72,
    'MTB': 0x73,'STFC': 0x74,'STB': 0x75,'PACK': 0x76,'UNPK': 0x77,'DS': 0x78,'DA': 0x79,'DD': 0x7a,'DM': 0x7b,
    'DSA': 0x7c,'DC': 0x7d,'DL': 0x7e,'DST': 0x7f
}

class Scanner(object):
    def __init__(self, patterns):
        self.patterns = patterns

    def setInput(self, input):
        self.lineNumber = 1
        self.input = input
        self.index = 0
        self.terminal = None
        self.lookAhead = self.next()

    def skipWhiteSpace(self):
        while self.index < len(self.input) and self.input[self.index].isspace():
            if self.input[self.index] == '\n':
                self.lineNumber += 1
            self.index += 1

    def skipComment(self):
        if self.index < len(self.input) and self.input[self.index] == '#':
            while self.index < len(self.input) and self.input[self.index] != '\n':
                self.index += 1
            self.lineNumber += 1
            return True
        return False

    def next(self):
        self.skipWhiteSpace()
        while self.skipComment():
            self.skipWhiteSpace()
        if self.index >= len(self.input):
            return None
        for p in self.patterns:
            match = p.match(self.input, self.index)
            if match:
                self.index = match.end()
                return Terminal(p.name, match.group(), self.lineNumber)
        raise Exception(f'line: {self.lineNumber}: unrecognized input: {self.input[self.index]}')
        
    def matches(self, *types):
        if self.lookAhead == None:
            return False
        for t in types:
            if t == self.lookAhead.name:
                self.terminal = self.lookAhead
                self.lookAhead = self.next()
                return True
        return False

    def expect(self, *types):
        if self.matches(*types):
            return self.terminal
        raise Exception(f'line: {self.lineNumber}: expected {",".join(types)}, found {self.lookAhead}')

    def atEnd(self):
        return self.lookAhead == None

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
        tree = Tree(self.sc.expect('ID'))
        if self.sc.matches('('):
            if self.sc.matches(')'):
                return tree
            tree.add(self.parseExp())
            while self.sc.matches(','):
                tree.add(self.parseExp())
            self.sc.expect(')')
        return tree

class TextCLiteral(object):
    def __init__(self, value, line):
        self.value = value
        self.line = line
        self.pc = 0

    def getNextPC(self, pc):
        self.pc = pc
        return pc + ((len(self.value) + 4) >> 2)

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
    
    def __len__(self):
        return len(self.value)

class GEN32Literal(object):
    def __init__(self, value, line):
        self.value = value
        self.line = line
        self.pc = 0

    def getNextPC(self, pc):
        self.pc = pc
        return pc + 1

    def getWords(self):
        return [f'{self.value:08x} // {self.pc:04x} {self.line}']
    
class Defines(object):
    def __init__(self):
        self.constants = {}
        self.literals = {}
        self.unescape_chars = {}
        for key, value in ESCAPE_CHARS.items():
            self.unescape_chars[value] = key

    def eval(self, tree, ignore_constants=False):
        if tree.value.name == 'INT':
            return tree.value.value
        if tree.value.name == 'ID':
            name = tree.value.value
            if name.upper() == 'TEXTC':
                if len(tree) != 1 or tree[0].value.name != '"':
                    raise Exception(f"line {tree.value.lineNumber}, exactly one string argument expected")
                text = tree[0].value.value
                if text in self.literals:
                    return self.literals[text].pc
                utext = self.unescape(text)
                self.literals[text] = TextCLiteral(text, f'    TEXTC    "{utext}" ; Generated constant')
                return 0
            if name.upper() == 'GEN32':
                if len(tree) != 1:
                    raise Exception(f"line {tree.value.lineNumber}, exactly one integer argument expected")
                value = self.eval(tree[0])
                if value in self.literals:
                    return self.literals[value].pc
                self.literals[value] = GEN32Literal(value, f'    GEN,32    {value} ; Generated constant')
                return 0
            if ignore_constants:
                return
            if len(tree) != 0:
                raise Exception(f"line {tree.value.lineNumber}, No such function '{name}'")
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

    def unescape(self, string):
        result = ''
        for c in string:
            if c in self.unescape_chars:
                result += '\\' + self.unescape_chars[c]
            else:
                result += c
        return result

class Directive(object):
    def __init__(self, defs, line, tree, lineNumber, pc):
        self.defs = defs
        self.line = line
        self.tree = tree
        self.lineNumber = lineNumber
        self.pc = pc

    def setLabels(self):
        for label in self.getLabels():
            self.defs.constants[label] = self.pc

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
        if cf0 == 'GEN':
            return GEN(defs, line, tree, lineNumber, pc)
        if cf0 in OPCODE_MAP:
            if (OPCODE_MAP[cf0] & 0x1c) == 0:
                return ImmInstruction(defs, line, tree, lineNumber, pc)
            return Instruction(defs, line, tree, lineNumber, pc)
        raise Exception(f"Unknown directive {cf0}, {line}")

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
        self.literal = TextCLiteral(tree[2][0].value.value, line)

    def getNextPC(self):
        self.setLabels()
        return self.literal.getNextPC(self.pc)

    def getWords(self):
        return self.literal.getWords()

class GEN(Directive):
    def __init__(self, defs, line, tree, lineNumber, pc):
        super().__init__(defs, line, tree, lineNumber, pc)

    def getNextPC(self):
        self.setLabels()
        return self.pc + 1

    def getWords(self):
        cf = self.tree[1]
        af = self.tree[2]
        if len(cf) < 2:
            raise Exception(f'line: {self.lineNumber}: Missing field widths.')
        widths = []
        totalWidth = 0
        for c in cf[1:]:
            w = self.defs.eval(c)
            widths.append(w)
            totalWidth += w
        values = []
        for a in af:
            values.append(self.defs.eval(a))
        if len(widths) != len(values):
            raise Exception(f"line: {self.lineNumber}: Number of fields is {len(widths)}, but number of values is {len(values)}.")
        if totalWidth != 32:
            raise Exception(f"line: {self.lineNumber}: Total width is {totalWidth} bits, expected 32 bits.")
        word = 0
        for w, v in zip(widths, values):
            word <<= w
            word |= v & ~(-1 << w)
        return [f'{word:08x} // {self.pc:04x} {self.line}']

class Instruction(Directive):
    def __init__(self, defs, line, tree, lineNumber, pc):
        super().__init__(defs, line, tree, lineNumber, pc)
        af = self.tree[2]
        index = 0
        if index >= len(af):
            raise Exception(f'line {self.lineNumber}: missing address')
        if af[index].value.name == '*':
            index += 1
        if index >= len(af):
            raise Exception(f'line {self.lineNumber}: missing address')
        # Define implicit literal if it exists
        self.defs.eval(af[index], ignore_constants=True)

    def getNextPC(self):
        self.setLabels()
        return self.pc + 1

    def getWords(self):
        cf = self.tree[1]
        if len(cf) != 2:
            raise Exception(f'line: {self.lineNumber}: One register is required.')
        op = OPCODE_MAP[cf[0].value.value]
        reg = self.defs.eval(cf[1])
        word = (op << 24) | (reg << 20)

        af = self.tree[2]
        index = 0
        if af[index].value.name == '*':
            word |= 0x80000000
            index += 1
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
        cf = self.tree[1]
        if len(cf) != 2:
            raise Exception(f'line: {self.lineNumber}: One register is required.')
        af = self.tree[2]
        if len(af) != 1:
            raise Exception(f'line: {self.lineNumber}: One operand is required.')
        # Define implicit literal if it exists
        self.defs.eval(af[0], ignore_constants=True)

    def getWords(self):
        cf = self.tree[1]
        af = self.tree[2]
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

MAX_WORD_LEN = 1024

class Assembler(object):
    def __init__(self):
        self.defs = Defines()
        self.genList = []
        self.parser = AParser()
    
    def parse(self, fasm):
        pc = 0
        with open(fasm) as f:
            lines = f.readlines()
            for lineNumber, line in enumerate(lines):
                lineNumber += 1
                line = line.replace('\n', '')
                tree = self.parser.parse(line, lineNumber)
                if len(tree) >= 3:
                    gen = Directive.new(self.defs, line, tree, lineNumber, pc)
                    pc = gen.getNextPC()
                    self.genList.append(gen)
        for key, literal in self.defs.literals.items():
            pc = literal.getNextPC(pc)

    def write(self, fout):
        outputWords = ['00000000']*MAX_WORD_LEN
        for gen in self.genList:
            words = gen.getWords()
            for i, w in enumerate(words):
                outputWords[gen.pc + i] = w
        for key, literal in self.defs.literals.items():
            words = literal.getWords()
            for i, w in enumerate(words):
                outputWords[literal.pc + i] = w
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
