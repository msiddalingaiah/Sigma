
import unittest

from Assembler import AParser

class TestAssembler(unittest.TestCase):
    def test_cf_af(self):
        p = AParser()
        tree = p.parse('    LI,1    3', 1)
        self.assertEqual(len(tree), 3)
        self.assertEqual(str(tree), '(stat lf (cf ID(LI) INT(1)) (af INT(3)))')

    def test_lf_cf_af(self):
        p = AParser()
        tree = p.parse(' loop     WD,2     5', 1)
        self.assertEqual(len(tree), 3)
        self.assertEqual(str(tree), '(stat (lf ID(loop)) (cf ID(WD) INT(2)) (af INT(5)))')

    def test_lf_cf_af_s(self):
        p = AParser()
        tree = p.parse('     LW,3     *foo, 1', 1)
        self.assertEqual(len(tree), 3)
        self.assertEqual(str(tree), '(stat lf (cf ID(LW) INT(3)) (af * ID(foo) INT(1)))')

    def test_comment(self):
        p = AParser()
        tree = p.parse('     LW,3     *foo, 1 ; Load word indirect, indexed', 1)
        self.assertEqual(len(tree), 4)
        self.assertEqual(str(tree), '(stat lf (cf ID(LW) INT(3)) (af * ID(foo) INT(1)) (comment "(Load word indirect, indexed)))')

    def test_no_af(self):
        p = AParser()
        tree = p.parse('     LW,3     ; Load word', 1)
        self.assertEqual(len(tree), 4)
        self.assertEqual(str(tree), '(stat lf (cf ID(LW) INT(3)) af (comment "(Load word)))')

    def test_no_cf(self):
        try:
            p = AParser()
            tree = p.parse(' loop     ', 1)
            self.fail()
        except Exception as e:
            self.assertEqual(str(e), 'line 1: Command field cannot be empty')

if __name__ == '__main__':
    unittest.main()
