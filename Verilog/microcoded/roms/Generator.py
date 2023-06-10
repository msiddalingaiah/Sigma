
BIG_ENDIAN = -1
LITTLE_ENDIAN = 1

SEQ_OP_NEXT = 0
SEQ_OP_JUMP = 1
SEQ_OP_CALL = 2
SEQ_OP_RETURN = 3

class Generator(object):
    def __init__(self, tree):
        self.output = []
        self.constants = { 'big':BIG_ENDIAN, 'little':LITTLE_ENDIAN }
        self.fields = {}
        self.procedures = {}
        self.patch = {}
        self.proc_address = {}
        self.pass1(tree)
        self.seq_width = self.constants['seq.width']
        self.big_endian = self.constants['seq.endian'] == BIG_ENDIAN
        self.output = []
        self.gen_stat_list(self.procedures['main'])
        for name, stat_list in self.procedures.items():
            if name != 'main':
                self.proc_address[name] = self.gen_bit_field('seq.address', len(self.output))
                self.gen_stat_list(stat_list)
        for address, name in self.patch.items():
            self.output[address] |= self.proc_address[name]

    def write(self, file_name):
        format = f'{{0:0{self.seq_width >> 2}x}}\n'
        a1, a2 = self.fields['seq.address']
        w = abs(a1-a2)+1
        word_count = 1 << w
        output = self.output + ([0]*(word_count-len(self.output)))
        with open(file_name, 'wt') as f:
            for value in output:
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

    def pass1(self, tree):
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
                self.procedures[name] = t[1]

    def gen_stat_list(self, stat_list):
        for stat in stat_list:
            if stat[0].value.name == 'loop':
                top = len(self.output)
                self.gen_stat_list(stat[1])
                jump = self.gen_bit_field('seq.op', SEQ_OP_JUMP) | self.gen_bit_field('seq.address', top)
                self.output[-1] |= jump
            else:
                self.gen_stat(stat)

    def gen_bit_field(self, field_name, value):
        i1, i2 = self.fields[field_name]
        width = abs(i1-i2)+1
        mask = ~(-1 << width)
        value = value & mask
        if self.big_endian:
            shift = self.seq_width - (i1+width)
        else:
            shift = i2
        #print(f'{i1}:{i2} = {value}, seq_width: {self.seq_width}, width: {width}, shift: {shift}')
        return value << shift

    def gen_stat(self, stat):
        # print('----')
        word = 0
        op_index = 0
        while op_index < len(stat):
            op = stat[op_index]
            op_index += 1
            if op.value.name == '=':
                field_name = op[0].value.value
                if field_name not in self.fields:
                    raise Exception(f'No such field: {field_name}')
                word |= self.gen_bit_field(field_name, self.eval(op[1]))
            if op.value.name == 'return':
                word |= self.gen_bit_field('seq.op', SEQ_OP_RETURN)
            if op.value.name == 'call':
                word |= self.gen_bit_field('seq.op', SEQ_OP_CALL)
                op = stat[op_index]
                op_index += 1
                proc = op.value.value
                self.patch[len(self.output)] = proc
        self.output.append(word)
