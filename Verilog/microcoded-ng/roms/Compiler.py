
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
    def next(self):
        raise NotImplementedError()
        
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

class LineScanner(Scanner):
    def __init__(self, patterns):
        self.patterns = patterns
        self.spaces = Pattern('SPACES', r'[ \t]+')

    def setInput(self, input):
        self.lines = input.split('\n')
        self.index = 0
        self.indentStack = ['']
        self.terminal = None
        self.terminals = []
        self.collectTerminals()
        self.index = 0
        self.lookAhead = self.next()

    def next(self):
        if self.index < len(self.terminals):
            t = self.terminals[self.index]
            self.index += 1
            return t
        return None

    def collectTerminals(self):
        self.lineNumber = 1
        for line in self.lines:
            ls = line.strip()
            if len(ls) > 0 and ls[0] != '#':
                line = line.rstrip()
                self.index = 0
                while self.index < len(line):
                    self.nextLine(line)
                self.terminals.append(Terminal('EOL', '', self.lineNumber))
            self.lineNumber += 1
        while len(self.indentStack) > 1:
            self.terminals.append(Terminal('DEDENT', '', self.lineNumber))
            self.indentStack.pop()

    def nextLine(self, line):
        match = self.spaces.match(line, self.index)
        if match:
            if self.index == 0:
                self.index = match.end()
                text = match.group()
                if len(text) > len(self.indentStack[-1]):
                    self.indentStack.append(text)
                    self.terminals.append(Terminal('INDENT', text, self.lineNumber))
                    return
                if len(self.indentStack) and len(text) < len(self.indentStack[-1]):
                    while len(self.indentStack) and len(text) < len(self.indentStack[-1]):
                        self.terminals.append(Terminal('DEDENT', text, self.lineNumber))
                        self.indentStack.pop()
                    return
            self.index = match.end()
        if line[self.index] == '#':
            self.index = len(line)
            return
        for p in self.patterns:
            match = p.match(line, self.index)
            if match:
                self.index = match.end()
                self.terminals.append(Terminal(p.name, match.group(), self.lineNumber))
                return
        raise Exception(f'line: {self.lineNumber}: unrecognized input: {line[self.index:]}')

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
        patterns.append(Pattern('nswitch', r'nswitch'))
        patterns.append(Pattern('romswitch', r'romswitch'))
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
        self.sc = LineScanner(patterns)
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
            self.sc.expect('EOL')
            return tree
        if self.sc.matches('field'):
            tree = Tree(self.sc.terminal)
            tree.add(self.sc.expect('ID'))
            self.sc.expect('=')
            tree.add(self.parseExp())
            self.sc.expect(':')
            tree.add(self.parseExp())
            self.sc.expect('EOL')
            return tree
        tree = Tree(self.sc.expect('def'))
        tree.add(self.sc.expect('ID'))
        tree.add(self.parseStatList())
        return tree

    def parseStatList(self):
        colon = self.sc.expect(':')
        if self.sc.matches('EOL'):
            tree = Tree(self.sc.expect('INDENT'))
            while not self.sc.matches('DEDENT'):
                tree.add(self.parseStatement())
            return tree
        tree = Tree(Terminal('INDENT', '', colon.lineNumber))
        tree.add(self.parseStatement())
        return tree

    def parseStatement(self):
        tree = Tree(Terminal('stat', 'stat'))
        if self.sc.matches('loop'):
            tree.add(self.sc.terminal)
            tree.add(self.parseStatList())
            return tree
        if self.sc.matches('do'):
            tree.add(self.sc.terminal)
            tree.add(self.parseStatList())
            self.sc.expect('while')
            if self.sc.matches('not'):
                tree.add(self.sc.terminal)
            tree.add(self.parseExp())
            self.sc.expect('EOL')
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
                if self.sc.matches('EOL'):
                    return tree
                self.sc.expect(',')
            while self.sc.matches('ID'):
                lhs = self.sc.terminal
                t2 = Tree(self.sc.expect('='))
                t2.add(lhs)
                t2.add(self.parseExp())
                tree.add(t2)
                if self.sc.matches('EOL'):
                    return tree
                self.sc.expect(',')
        if self.sc.matches('"'):
            tree.add(self.sc.terminal)
            if self.sc.matches('EOL'):
                return tree
            self.sc.expect(',')
        if self.sc.matches('if'):
            tree.add(self.sc.terminal)
            if self.sc.matches('not'):
                tree.add(self.sc.terminal)
            tree.add(self.parseExp())
            if self.sc.matches('continue'):
                tree.add(self.sc.terminal)
                tree.add(self.sc.expect('ID'))
                self.sc.expect('EOL')
                return tree
            tree.add(self.parseStatList())
            if self.sc.matches('else'):
                tree.add(self.parseStatList())
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
            tree.add(self.parseSwitchBlock('switch'))
            return tree
        if self.sc.matches('nswitch'):
            tree.add(self.sc.terminal)
            tree.add(self.parseExp())
            tree.add(self.parseExp())
            tree.add(self.parseSwitchBlock('nswitch'))
            return tree
        if self.sc.matches('romswitch'):
            tree.add(self.sc.terminal)
            tree.add(self.parseExp())
            t = self.sc.expect('"')
            t.value = self.escape(t.value[1:-1])
            tree.add(t)            
            tree.add(self.parseSwitchBlock('romswitch'))
            return tree
        if self.sc.matches('call'):
            tree.add(self.sc.terminal)
            tree.add(self.sc.expect('ID'))
            self.sc.expect('EOL')
            return tree
        if self.sc.matches('return'):
            tree.add(self.sc.terminal)
            self.sc.expect('EOL')
            return tree
        if self.sc.matches('continue'):
            tree.add(self.sc.terminal)
            tree.add(self.sc.expect('ID'))
            self.sc.expect('EOL')
            return tree
        self.sc.expect('if', 'do', 'while', 'loop', 'switch', 'call', 'return', 'continue')

    def parseSwitchBlock(self, stat_name):
        tree = Tree(self.sc.expect('{'))
        while not self.sc.matches('}'):
            tree.add(self.parseExp())
            self.sc.expect(':')
            tree.add(self.parseStatList(stat_name))
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

import sys

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('usage: python Compiler.py <source-file> <microcode-file>')
        sys.exit(1)

    cp = Parser()
    with open(sys.argv[1]) as f:
        tree = cp.parse(f.read())
    g = gen.Generator(tree)
    g.write(sys.argv[2])

