
import unittest

from Compiler import Parser

class TestStringMethods(unittest.TestCase):
    def test_const(self):
        p = Parser()
        self.assertEqual(str(p.parse('const control = 7;')), '(None (const ID(control) INT(7)))')

    def test_loop(self):
        p = Parser()
        tree = p.parse('''def main {
                       loop { a=1; }
                       do { b=1; } while 1;
                       c=1, call X;
                       d=1, return;
                       e=1, while 1 {
                            f=1;
                       }
                       g=1;
                       h=1, if 1 { i=1; }
                       }''')
        stat_list = tree[0][1]
        tailBranches = [self.isTailBranch(stat) for stat in stat_list]
        self.assertEqual(tailBranches, [True, True, True, True, True, False, False])
        headBranches = [self.isHeadBranch(stat) for stat in stat_list]
        self.assertEqual(headBranches, [False, False, True, True, True, False, True])

    def getBranch(self, stat):
        if stat[0].value.name in ('loop', 'do'):
            return stat[0].value.name
        for op in stat:
            if op.value.name in ('call', 'return', 'while', 'if'):
                return op.value.name
        return ''

    def isHeadBranch(self, stat):
        return self.getBranch(stat) in ('call', 'return', 'while', 'if')

    def isTailBranch(self, stat):
        return self.getBranch(stat) in ('loop', 'do', 'call', 'return', 'while')

    def test_loop_error(self):
        p = Parser()
        try:
            tree = p.parse('''def main {
                        loop { loop { a=1; } }
                        }''')
            self.fail()
        except Exception as e:
            self.assertEqual(str(e), 'line 2: loop not allowed here')

    def test_while_error(self):
        p = Parser()
        try:
            tree = p.parse('''def main {
                        loop { while 1 { a=1; } }
                        }''')
            self.fail()
        except Exception as e:
            self.assertEqual(str(e), 'line 2: while not allowed here')

    def test_do_error(self):
        p = Parser()
        try:
            tree = p.parse('''def main {
                        loop { do { a=1; } while 1; } }
                        }''')
            self.fail()
        except Exception as e:
            self.assertEqual(str(e), 'line 2: do not allowed here')

    def test_call_error(self):
        p = Parser()
        try:
            tree = p.parse('''def main {
                        loop { call X; } }
                        }''')
            self.fail()
        except Exception as e:
            self.assertEqual(str(e), 'line 2: call not allowed here')

    def test_return_error(self):
        p = Parser()
        try:
            tree = p.parse('''def main {
                        loop { return; } }
                        }''')
            self.fail()
        except Exception as e:
            self.assertEqual(str(e), 'line 2: return not allowed here')

    def test_if_error(self):
        p = Parser()
        tree = p.parse('''def main {
                    loop { if 1 { a=1; } }
                    }''')

if __name__ == '__main__':
    unittest.main()
