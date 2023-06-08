
class Generator(object):
    def __init__(self, tree):
        self.output = []
        self.constants = { 'big':1, 'little':-1 }
        self.fields = {}
        self.procedures = {}
        self.generate(tree)
        #print(self.constants)
        #print(self.fields)

    def write(self, file_name):
        seq_width = self.constants['seq.width'] >> 2
        format = f'{{0:0{seq_width}x}}\n'
        #print(format.format(1))
        a1, a2 = self.fields['seq.address']
        w = abs(a1-a2)+1
        word_count = 1 << w
        with open(file_name, 'wt') as f:
            for value in self.output:
                f.write(format.format(value))

    def eval(self, tree):
        if tree.value.name == 'INT':
            return tree.value.value
        if tree.value.name == 'ID':
            name = tree.value.value
            if name not in self.constants:
                raise Exception(f"No such constant '{name}'")
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
        raise Exception(f"Unknown operator '{op}'")

    def generate(self, tree):
        for t in tree.children:
            if t.value == 'const':
                name = t[0].value.value
                self.constants[name] = self.eval(t[1])
            if t.value == 'field':
                name = t[0].value.value
                i1 = self.eval(t[1])
                i2 = self.eval(t[2])
                self.fields[name] = [i1, i2]
            if t.value == 'def':
                name = t[0].value.value
                self.procedures[name] = self.gen_proc(t[1])

    def gen_proc(self, tree):
        for stat in tree.children:
            if stat.value.name == 'stat':
                self.gen_stat(stat)

    def gen_stat(self, stat):
        print(stat)
        # TODO stopped here