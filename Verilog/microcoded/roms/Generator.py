
BIG_ENDIAN = -1
LITTLE_ENDIAN = 1

SEQ_OP_NEXT = 0
SEQ_OP_JUMP = 1
SEQ_OP_CALL = 2
SEQ_OP_RETURN = 3

from collections import defaultdict

class MicroWord(object):
    def __init__(self, fields, big_endian, seq_width):
        self.fields = fields
        self.big_endian = big_endian
        self.seq_width = seq_width
        self.word = 0
        self.used_bits = 0
        self.field_values = defaultdict(int)
        self.dest_proc_name = None

    def update(self, field_name, value, lineNumber=-1, check=True):
        if field_name not in self.fields:
            raise Exception(f'line {lineNumber}, No such field: {field_name}')
        self.field_values[field_name] = value
        i1, i2 = self.fields[field_name]
        width = abs(i1-i2)+1
        mask = ~(-1 << width)
        value = value & mask
        if self.big_endian:
            shift = self.seq_width - (i1+width)
        else:
            shift = i2
        mask <<= shift
        if mask & self.used_bits != 0 and check:
            raise Exception(f"line {lineNumber}: field '{field_name}' already assigned")
        self.used_bits |= mask
        value <<= shift
        self.word &= ~mask
        self.word |= value
        return value

    def updateAddress(self, offset):
        value = self.field_values['seq.address'] + offset
        self.update('seq.address', value, check=False)

    def is_branch(self):
        return self.field_values['seq.op'] != 0 or self.field_values['seq.condition'] != 0

    def updateCall(self, procAddresses):
        if self.dest_proc_name != None:
            if self.dest_proc_name not in procAddresses:
                raise Exception(f'Nonexistent procedure: {self.dest_proc_name}')
            value = procAddresses[self.dest_proc_name]
            self.update('seq.address', value, check=False)

    def genComment(self):
        fields = [f'{name}={value}' for name, value in self.field_values.items()]
        assigns = ', '.join(fields)
        branch = ''
        op = self.field_values['seq.op']
        condition = self.field_values['seq.condition']
        address = self.field_values['seq.address']
        if op == SEQ_OP_JUMP and condition == 0:
            branch = f'; jump {address}'
        if op == SEQ_OP_JUMP and condition != 0:
            branch = f'; if not condition[{condition}] jump {address}'
        if op == 0 and condition != 0:
            branch = f'; if condition[{condition}] jump {address}'
        if op == SEQ_OP_CALL:
            branch = f'; call {address}'
        if op == SEQ_OP_RETURN:
            branch = f'; return'
        return f'{assigns}{branch}'

class MicroWordBlock(object):
    def __init__(self, fields, expr, big_endian, seq_width, stat_list):
        self.fields = fields
        self.expr = expr
        self.big_endian = big_endian
        self.seq_width = seq_width
        self.outputWords = []
        self.branchWords = []
        self.callWords = []
        for stat in stat_list:
            lineNumber = stat[0].value.lineNumber
            if stat[0].value.name == 'loop':
                top = len(self.outputWords)
                block = MicroWordBlock(self.fields, self.expr, self.big_endian, self.seq_width, stat[1])
                self.outputWords.extend(block.outputWords)
                self.callWords.extend(block.callWords)
                self.outputWords[-1].update('seq.op', SEQ_OP_JUMP, lineNumber)
                self.outputWords[-1].update('seq.address', top, lineNumber)
                self.branchWords.append(self.outputWords[-1])
                block.updateAddresses(top)
            elif stat[0].value.name == 'do':
                top = len(self.outputWords)
                block = MicroWordBlock(self.fields, self.expr, self.big_endian, self.seq_width, stat[1])
                self.outputWords.extend(block.outputWords)
                self.callWords.extend(block.callWords)
                tail_word = self.outputWords[-1]
                tail_word.update('seq.address', top, lineNumber)
                block.updateAddresses(top)
                exp_index = 2
                # invert branch
                if len(stat) == 4 and stat[2].value.name == 'not':
                    tail_word.update('seq.op', SEQ_OP_JUMP, lineNumber)
                    exp_index += 1
                tail_word.update('seq.condition', self.expr.eval(stat[exp_index]), lineNumber)
                self.branchWords.append(tail_word)
            else:
                self.gen_stat(stat)

    def gen_stat(self, stat):
        word = MicroWord(self.fields, self.big_endian, self.seq_width)
        op_index = 0
        while op_index < len(stat):
            op = stat[op_index]
            op_index += 1
            lineNumber = op.value.lineNumber
            if op.value.name == '=':
                field_name = op[0].value.value
                word.update(field_name, self.expr.eval(op[1]), lineNumber)
            if op.value.name == 'return':
                word.update('seq.op', SEQ_OP_RETURN, lineNumber)
            if op.value.name == 'call':
                word.update('seq.op', SEQ_OP_CALL, lineNumber)
                op = stat[op_index]
                op_index += 1
                word.dest_proc_name = op.value.value
                self.callWords.append(word)
            if op.value.name == 'while':
                if stat[op_index].value.name == 'not':
                    op_index += 1
                else:
                    word.update('seq.op', SEQ_OP_JUMP, lineNumber)
                condition = self.expr.eval(stat[op_index])
                word.update('seq.condition', condition, lineNumber)
                self.branchWords.append(word)
                op_index += 1
                top = len(self.outputWords)
                self.outputWords.append(word)
                stat_list = stat[op_index]
                op_index += 1
                btop = len(self.outputWords)
                block = MicroWordBlock(self.fields, self.expr, self.big_endian, self.seq_width, stat_list)
                self.outputWords.extend(block.outputWords)
                self.callWords.extend(block.callWords)
                tail_word = self.outputWords[-1]
                tail_word.update('seq.op', SEQ_OP_JUMP, lineNumber)
                tail_word.update('seq.address', top, lineNumber)
                self.branchWords.append(tail_word)
                next = len(self.outputWords)
                word.update('seq.address', next, lineNumber, check=False)
                block.updateAddresses(btop)
                return
            if op.value.name == 'if':
                if stat[op_index].value.name == 'not':
                    op_index += 1
                else:
                    word.update('seq.op', SEQ_OP_JUMP, lineNumber)
                condition = self.expr.eval(stat[op_index])
                word.update('seq.condition', condition, lineNumber)
                self.branchWords.append(word)
                op_index += 1
                self.outputWords.append(word)
                stat_list = stat[op_index]
                op_index += 1
                iftop = len(self.outputWords)
                block = MicroWordBlock(self.fields, self.expr, self.big_endian, self.seq_width, stat_list)
                self.outputWords.extend(block.outputWords)
                self.callWords.extend(block.callWords)
                if len(stat) > op_index:
                    elsetop = len(self.outputWords)
                    word.update('seq.address', elsetop, lineNumber, check=False)
                    word = self.outputWords[-1]
                    word.update('seq.op', SEQ_OP_JUMP, lineNumber)
                    self.branchWords.append(word)
                    stat_list = stat[op_index]
                    op_index += 1
                    elseblock = MicroWordBlock(self.fields, self.expr, self.big_endian, self.seq_width, stat_list)
                    self.outputWords.extend(elseblock.outputWords)
                    self.callWords.extend(elseblock.callWords)
                    elseblock.updateAddresses(elsetop)
                next = len(self.outputWords)
                word.update('seq.address', next, lineNumber, check=False)
                block.updateAddresses(iftop)
                return
        self.outputWords.append(word)

    def updateAddresses(self, startAddress):
        for word in self.branchWords:
            word.updateAddress(startAddress)
    
    def updateCalls(self, procAddresses):
        for word in self.callWords:
            word.updateCall(procAddresses)

    def getOutput(self, startAddress, procAddresses):
        self.updateAddresses(startAddress)
        self.updateCalls(procAddresses)
        format = f'{{0:0{self.seq_width >> 2}x}}'
        results = []
        for i, mc in enumerate(self.outputWords):
            code = format.format(mc.word)
            comment = mc.genComment()
            results.append(f'{code} // {i+startAddress:4d}: {comment}')
        return results
    
    def __len__(self):
        return len(self.outputWords)


class Generator(object):
    def __init__(self, tree):
        self.constants = { 'BIG':BIG_ENDIAN, 'LITTLE':LITTLE_ENDIAN }
        self.fields = {}
        self.procedures = {}
        self.procedureBlocks = {}
        self.proc_address = {}
        self.expr = Expression(self.constants)
        self.pass1(tree)
        self.seq_width = self.constants['seq.width']
        self.big_endian = self.constants['seq.endian'] == BIG_ENDIAN
        for name, stat_list in self.procedures.items():
            self.procedureBlocks[name] = MicroWordBlock(self.fields, self.expr, self.big_endian, self.seq_width, stat_list)

    def write(self, file_name):
        a1, a2 = self.fields['seq.address']
        w = abs(a1-a2)+1
        word_count = 1 << w
        with open(file_name, 'wt') as f:
            names = list(self.procedureBlocks.keys())
            names.remove('main')
            names = ['main'] + names
            procAddresses = {}
            address = 0
            for name in names:
                block = self.procedureBlocks[name]
                procAddresses[name] = address
                address += len(block)
            address = 0
            for name in names:
                block = self.procedureBlocks[name]
                output = block.getOutput(address, procAddresses)
                for line in output:
                    f.write(line + '\n')
                address += len(output)
            format = f'{{0:0{self.seq_width >> 2}x}}'
            for i in range(word_count-address):
                f.write(format.format(0) + '\n')

    def pass1(self, tree):
        for t in tree.children:
            if t.value == 'const':
                name = t[0].value.value
                self.constants[name] = self.expr.eval(t[1])
            if t.value == 'field':
                name = t[0].value.value
                i1 = self.expr.eval(t[1])
                i2 = self.expr.eval(t[2])
                self.fields[name] = [i1, i2]
            if t.value == 'def':
                name = t[0].value.value
                self.procedures[name] = t[1]

class Expression(object):
    def __init__(self, constants):
        self.constants = constants

    def eval(self, tree):
        if tree.value.name == 'INT':
            return tree.value.value
        if tree.value.name == 'ID':
            name = tree.value.value
            if name not in self.constants:
                raise Exception(f"line {tree.value.lineNumber}, No such constant '{name}'")
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
        raise Exception(f"line {tree.value.lineNumber}, Unknown operator '{op}'")
