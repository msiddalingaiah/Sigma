
class Generator(object):
    def __init__(self, tree):
        self.output = []
        self.constants = {}
        self.fields = {}
        self.generate(tree)
        print(self.constants)
        print(self.fields)

    def write(self, file_name):
        with open(file_name, 'wt') as f:
            for line in self.output:
                f.write(line + '\n')

    def generate(self, tree):
        for t in tree.children:
            if t.value == 'const':
                name = t[0].value.value
                value = t[1].value.value
                if name == 'endian':
                    self.endian = value
                else:
                    self.constants[name] = value
            if t.value == 'field':
                name = t[0].value.value
                i1 = int(t[1].value.value)
                i2 = int(t[2].value.value)
                self.fields[name] = [i1, i2]
