
import unittest

from Compiler import Parser

class TestStringMethods(unittest.TestCase):
    def test_const(self):
        p = Parser()
        self.assertEqual(str(p.parse('const control = 7')), '(None (const ID(control) INT(7)))')

    # ----
    def test_loop(self):
        p = Parser()
        tree = p.parse('''
def main:
    loop:
        a=1
''')
        self.assertEqual(str(tree), '(None (def ID(main) (INDENT(    ) (stat loop (INDENT(        ) (stat (= ID(a) INT(1))))))))')


    # ----
    def test_scan(self):
        input = '''a
    b
        c
d'''
        p = Parser()
        p.sc.setInput(input)
        expected = "ID(a),EOL(),INDENT(    ),ID(b),EOL(),INDENT(        ),ID(c),EOL(),DEDENT(),DEDENT(),ID(d),EOL()"
        self.assertEqual(','.join([str(x) for x in p.sc.terminals]), expected)

    # ----
    def test_indent(self):
        input = '''def foo:
    if b:
        c=1

const d=2'''
        p = Parser()
        tree = p.parse(input)
        expected = "(None (def ID(foo) (INDENT(    ) (stat if ID(b) (INDENT(        ) (stat (= ID(c) INT(1))))))) (const ID(d) INT(2)))"
        self.assertEqual(str(tree), expected)

if __name__ == '__main__':
    unittest.main()
