
import unittest

from Compiler import Parser

class TestStringMethods(unittest.TestCase):
    def test_const(self):
        p = Parser()
        self.assertEqual(str(p.parse('const control = 7;')), '(None (const ID(control) INT(7)))')

if __name__ == '__main__':
    unittest.main()
