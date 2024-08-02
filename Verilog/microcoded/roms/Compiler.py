
from collections import defaultdict
import re

import Generator as gen

class Pattern(object):
    def __init__(self, name, regex):
        self.name = name
        self.pattern = re.compile(regex)
        
    def match(self, input, index):
        return self.pattern.match(input, index)
    
class Terminal(object):
    def __init__(self, name, value, lineNumber=0):
        self.name = name
        self.value = value
        self.lineNumber = lineNumber

    def __eq__(self, other):
        return other == self.name

    def __str__(self):
        if self.name.lower() == self.value:
            return self.name
        return '%s(%s)' % (self.name, self.value)
        
class Tree(object):
    def __init__(self, *values):
        self.value = None
        if len(values) > 0:
            self.value = values[0]
        if len(values) > 1:
            self.children = [x for x in values[1:]]
        else:
            self.children = []

    def add(self, value):
        if isinstance(value, Tree):
            self.children.append(value)
        else:
            self.children.append(Tree(value))
        return self
        
    def __len__(self):
        return len(self.children)

    def __getitem__(self, index):
        return self.children[index]

    def isLeaf(self):
        return len(self.children) == 0

    def __str__(self):
        if self.isLeaf():
            return str(self.value)
        result = '(%s' % self.value
        for c in self.children:
            result = '%s %s' % (result, c)
        return '%s)' % result

class Scanner(object):
    def __init__(self, patterns):
        self.patterns = patterns

    def setInput(self, input):
        self.lineNumber = 1
        self.input = input
        self.index = 0
        self.terminal = None
        self.lookAhead = self.next()

    def next(self):
        while self.index < len(self.input) and self.input[self.index].isspace():
            if self.input[self.index] == '\n':
                self.lineNumber += 1
            self.index += 1
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

class Parser(object):
    def __init__(self):
        patterns = []
        patterns.append(Pattern('def', r'def'))
        patterns.append(Pattern('if', r'if'))
        patterns.append(Pattern('else', r'else'))
        patterns.append(Pattern('loop', r'loop'))
        patterns.append(Pattern('while', r'while'))
        patterns.append(Pattern('do', r'do'))
        patterns.append(Pattern('const', r'const'))
        patterns.append(Pattern('field', r'field'))
        patterns.append(Pattern('call', r'call'))
        patterns.append(Pattern('return', r'return'))
        patterns.append(Pattern('not', r'not'))
        patterns.append(Pattern('switch', r'switch'))
        patterns.append(Pattern('continue', r'continue'))
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

    def parse(self, input):
        self.sc.setInput(input)
        tree = self.parseProgram()
        if not self.sc.atEnd():
            raise Exception('Unexpected input: %s' % self.sc.terminal)
        return tree

    def parseProgram(self):
        tree = Tree()
        tree.add(self.parseExternal())
        while not self.sc.atEnd():
            tree.add(self.parseExternal())
        return tree

    def parseExternal(self):
        if self.sc.matches('const'):
            tree = Tree(self.sc.terminal)
            tree.add(self.sc.expect('ID'))
            self.sc.expect('=')
            tree.add(self.parseExp())
            self.sc.expect(';')
            return tree
        if self.sc.matches('field'):
            tree = Tree(self.sc.terminal)
            tree.add(self.sc.expect('ID'))
            self.sc.expect('=')
            tree.add(self.parseExp())
            self.sc.expect(':')
            tree.add(self.parseExp())
            self.sc.expect(';')
            return tree
        tree = Tree(self.sc.expect('def'))
        tree.add(self.sc.expect('ID'))
        tree.add(self.parseStatList(noHeadBranch=False, noTailBranch=False))
        return tree

    def getBranch(self, stat):
        if stat[0].value.name in ('loop', 'do'):
            return stat[0].value.name
        for op in stat:
            if op.value.name in ('call', 'return', 'while', 'if', 'switch', 'continue'):
                return op.value.name
        return ''

    def getBranchLine(self, stat):
        if stat[0].value.name in ('loop', 'do'):
            return stat[0].value.lineNumber
        for op in stat:
            if op.value.name in ('call', 'return', 'while', 'if', 'switch', 'continue'):
                return op.value.lineNumber
        return ''

    def isHeadBranch(self, stat):
        return self.getBranch(stat) in ('call', 'return', 'while', 'if', 'switch', 'continue')

    def isTailBranch(self, stat):
        return self.getBranch(stat) in ('loop', 'do', 'call', 'return', 'while', 'switch', 'continue')

    def parseStatList(self, noHeadBranch=True, noTailBranch=True, stat_name=''):
        tree = Tree(self.sc.expect('{'))
        while not self.sc.matches('}'):
            tree.add(self.parseStatement())
        head, tail = tree[0], tree[-1]
        # switch blocks can start or end with continue statements
        if noHeadBranch and self.isHeadBranch(head):
            if stat_name == 'switch' and self.getBranch(head) != 'continue':
                raise Exception(f'line {self.getBranchLine(head)}: {self.getBranch(head)} not allowed here')
        if noTailBranch and self.isTailBranch(tail):
            if stat_name == 'switch' and self.getBranch(tail) != 'continue':
                raise Exception(f'line {self.getBranchLine(tail)}: {self.getBranch(tail)} not allowed here')
        return tree

    def parseStatement(self):
        tree = Tree(Terminal('stat', 'stat'))
        if self.sc.matches('loop'):
            tree.add(self.sc.terminal)
            tree.add(self.parseStatList(noHeadBranch=False))
            return tree
        if self.sc.matches('do'):
            tree.add(self.sc.terminal)
            tree.add(self.parseStatList(noHeadBranch=False))
            self.sc.expect('while')
            if self.sc.matches('not'):
                tree.add(self.sc.terminal)
            tree.add(self.parseExp())
            self.sc.expect(';')
            return tree
        if self.sc.matches('ID'):
            id = self.sc.terminal
            if self.sc.matches(':'):
                t2 = Tree(self.sc.terminal)
                t2.add(id)
                tree.add(t2)
            else:
                t2 = Tree(self.sc.expect('='))
                t2.add(id)
                t2.add(self.parseExp())
                tree.add(t2)
                if self.sc.matches(';'):
                    return tree
                self.sc.expect(',')
            while self.sc.matches('ID'):
                lhs = self.sc.terminal
                t2 = Tree(self.sc.expect('='))
                t2.add(lhs)
                t2.add(self.parseExp())
                tree.add(t2)
                if self.sc.matches(';'):
                    return tree
                self.sc.expect(',')
        if self.sc.matches('"'):
            tree.add(self.sc.terminal)
            if self.sc.matches(';'):
                return tree
            self.sc.expect(',')
        if self.sc.matches('if'):
            tree.add(self.sc.terminal)
            if self.sc.matches('not'):
                tree.add(self.sc.terminal)
            tree.add(self.parseExp())
            tree.add(self.parseStatList())
            if self.sc.matches('else'):
                tree.add(self.parseStatList(noTailBranch=False))
            return tree
        if self.sc.matches('while'):
            tree.add(self.sc.terminal)
            if self.sc.matches('not'):
                tree.add(self.sc.terminal)
            tree.add(self.parseExp())
            tree.add(self.parseStatList())
            return tree
        if self.sc.matches('switch'):
            tree.add(self.sc.terminal)
            tree.add(self.parseExp())
            tree.add(self.parseSwitchBlock())
            return tree
        if self.sc.matches('call'):
            tree.add(self.sc.terminal)
            tree.add(self.sc.expect('ID'))
            self.sc.expect(';')
            return tree
        if self.sc.matches('return'):
            tree.add(self.sc.terminal)
            self.sc.expect(';')
            return tree
        if self.sc.matches('continue'):
            tree.add(self.sc.terminal)
            tree.add(self.sc.expect('ID'))
            self.sc.expect(';')
            return tree
        self.sc.expect('if', 'do', 'while', 'loop', 'switch', 'call', 'return', 'continue')

    def parseSwitchBlock(self):
        tree = Tree(self.sc.expect('{'))
        while not self.sc.matches('}'):
            tree.add(self.parseExp())
            self.sc.expect(':')
            tree.add(self.parseStatList(stat_name='switch'))
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

if __name__ == '__main__':
    cp = Parser()
    with open('sigma.txt') as f:
        tree = cp.parse(f.read())
    g = gen.Generator(tree)
    g.write('sigma_microcode.txt')

