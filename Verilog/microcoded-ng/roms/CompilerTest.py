
import unittest

from Compiler import Parser

class TestStringMethods(unittest.TestCase):
    def test_const(self):
        p = Parser()
        self.assertEqual(str(p.parse('const control = 7')), '(None (const ID(control) INT(7)))')

    def test_loop(self):
        p = Parser()
        tree = p.parse('''
def main:
    loop:
        a=1
''')
        self.assertEqual(str(tree), '(None (def ID(main) (INDENT(    ) (stat loop (INDENT(        ) (stat (= ID(a) INT(1))))))))')

if __name__ == '__main__':
    unittest.main()
