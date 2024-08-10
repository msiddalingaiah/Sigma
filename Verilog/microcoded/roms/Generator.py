
BIG_ENDIAN = -1
LITTLE_ENDIAN = 1

SEQ_OP_NEXT = 0
SEQ_OP_JUMP = 1
SEQ_OP_CALL = 2
SEQ_OP_RETURN = 3

from collections import defaultdict

class Globals(object):
    def __init__(self):
        self.fields = {}
        self.constants = { 'BIG':BIG_ENDIAN, 'LITTLE':LITTLE_ENDIAN }
        self.labeledWords = {}
        self.procStartWords = {}
        self.procReferenceWords = defaultdict(list)
        self.labelReferenceWords = defaultdict(list)

    def pass1(self, tree):
        procedureTrees = {}
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
                procedureTrees[name] = t[1]
        self.seq_width = self.constants['seq.width']
        self.big_endian = self.constants['seq.endian'] == BIG_ENDIAN
        return procedureTrees

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

    def resolveRefs(self):
        for label, refWordList in self.labelReferenceWords.items():
            if label not in self.labeledWords:
                raise Exception(f'line {refWord.lineNumber}: no such label {label}')
            target = self.labeledWords[label]
            for refWord in refWordList:
                refWord.update('seq.address', target.pc - refWord.pc - 1)

        for name, refWordList in self.procReferenceWords.items():
            if name not in self.procStartWords:
                raise Exception(f'line {refWord.lineNumber}: no such procedure {name}')
            target = self.procStartWords[name]
            for refWord in refWordList:
                refWord.update('seq.address', target.pc - refWord.pc - 1)

class MicroWord(object):
    def __init__(self, _globals, lineNumber=-1):
        self.globals = _globals
        self.lineNumber = lineNumber
        self.word = 0
        self.used_bits = 0
        self.field_values = defaultdict(int)
        self.pc = 0
        self.comment = ''

    def update(self, field_name, value):
        if field_name not in self.globals.fields:
            raise Exception(f'line {self.lineNumber}, No such field: {field_name}')
        self.field_values[field_name] = value
        i1, i2 = self.globals.fields[field_name]
        width = abs(i1-i2)+1
        mask = ~(-1 << width)
        value = value & mask
        if self.globals.big_endian:
            shift = self.globals.seq_width - (i1+width)
        else:
            shift = i2
        mask <<= shift
        if mask & self.used_bits != 0:
            raise Exception(f"line {self.lineNumber}: field '{field_name}' already assigned")
        self.used_bits |= mask
        value <<= shift
        self.word &= ~mask
        self.word |= value
        return value

    def is_branch(self):
        return self.field_values['seq.op'] != 0 or self.field_values['seq.condition'] != 0

    def genComment(self):
        fields = [f'{name}={value}' for name, value in self.field_values.items()]
        assigns = ', '.join(fields)
        branch = ''
        op = self.field_values['seq.op']
        condition = self.field_values['seq.condition']
        address = self.field_values['seq.address']
        address_mux = self.field_values['seq.address_mux']
        if op == SEQ_OP_JUMP and condition == 0 and address_mux == 0:
            branch = f'; jump {address} ({self.pc + address + 1})'
        if op == SEQ_OP_JUMP and condition != 0:
            branch = f'; if not condition[{condition}] jump {address} ({self.pc + address + 1})'
        if op == SEQ_OP_JUMP and address_mux != 0:
            branch = f'; switch address_mux[{address_mux}]'
        if op == 0 and condition != 0:
            branch = f'; if condition[{condition}] jump {address} ({self.pc + address + 1})'
        if op == SEQ_OP_CALL:
            branch = f'; call {address} ({self.pc + address + 1})'
        if op == SEQ_OP_RETURN:
            branch = f'; return'
        return f'{assigns}{branch}'

class MicroWordBlock(object):
    def __init__(self, _globals, stat_list):
        self.globals = _globals
        self.outputWords = []
        for stat in stat_list:
            lineNumber = stat[0].value.lineNumber
            if stat[0].value.name == 'loop':
                block = MicroWordBlock(self.globals, stat[1])
                self.addBlock(block)
                self.outputWords[-1].update('seq.op', SEQ_OP_JUMP)
                self.outputWords[-1].update('seq.address', -len(block))
            elif stat[0].value.name == 'do':
                block = MicroWordBlock(self.globals, stat[1])
                self.addBlock(block)
                tail_word = self.outputWords[-1]
                tail_word.update('seq.address', -len(block))
                exp_index = 2
                # invert branch
                if len(stat) == 4 and stat[2].value.name == 'not':
                    tail_word.update('seq.op', SEQ_OP_JUMP)
                    exp_index += 1
                tail_word.update('seq.condition', self.globals.eval(stat[exp_index]))
            else:
                self.gen_stat(stat)

    def addBlock(self, block):
        self.outputWords.extend(block.outputWords)

    def gen_stat(self, stat):
        word = MicroWord(self.globals)
        op_index = 0
        while op_index < len(stat):
            op = stat[op_index]
            op_index += 1
            word.lineNumber = op.value.lineNumber
            if op.value.name == ':':
                label_name = op[0].value.value
                if label_name in self.globals.labeledWords:
                    raise Exception(f"line {word.lineNumber}: duplicate label definition '{label_name}'")
                self.globals.labeledWords[label_name] = word
            if op.value.name == '"':
                comment = op.value.value[1:-1]
                word.comment = comment
            if op.value.name == '=':
                field_name = op[0].value.value
                word.update(field_name, self.globals.eval(op[1]))
            if op.value.name == 'return':
                word.update('seq.op', SEQ_OP_RETURN)
            if op.value.name == 'call':
                word.update('seq.op', SEQ_OP_CALL)
                op = stat[op_index]
                op_index += 1
                self.globals.procReferenceWords[op.value.value].append(word)
            if op.value.name == 'while':
                if stat[op_index].value.name == 'not':
                    op_index += 1
                else:
                    word.update('seq.op', SEQ_OP_JUMP)
                condition = self.globals.eval(stat[op_index])
                word.update('seq.condition', condition)
                op_index += 1
                self.outputWords.append(word)
                stat_list = stat[op_index]
                op_index += 1
                block = MicroWordBlock(self.globals, stat_list)
                self.addBlock(block)
                tail_word = self.outputWords[-1]
                tail_word.update('seq.op', SEQ_OP_JUMP)
                tail_word.update('seq.address', -len(block)-1)
                word.update('seq.address', len(block))
                return
            if op.value.name == 'continue':
                label = stat[op_index].value.value
                op_index += 1
                word.update('seq.op', SEQ_OP_JUMP)
                self.globals.labelReferenceWords[label].append(word)
                self.outputWords.append(word)
                return
            if op.value.name == 'if':
                if stat[op_index].value.name == 'not':
                    op_index += 1
                else:
                    word.update('seq.op', SEQ_OP_JUMP)
                condition = self.globals.eval(stat[op_index])
                word.update('seq.condition', condition)
                op_index += 1
                self.outputWords.append(word)
                stat_list = stat[op_index]
                op_index += 1
                block = MicroWordBlock(self.globals, stat_list)
                self.addBlock(block)
                if len(stat) > op_index:
                    word.update('seq.address', len(block))
                    word = self.outputWords[-1]
                    word.update('seq.op', SEQ_OP_JUMP)
                    stat_list = stat[op_index]
                    op_index += 1
                    block = MicroWordBlock(self.globals, stat_list)
                    self.addBlock(block)
                word.update('seq.address', len(block))
                return
            if op.value.name == 'switch':
                addr_mux = self.globals.eval(stat[op_index])
                op_index += 1
                word.update('seq.address_mux', addr_mux)
                word.update('seq.op', SEQ_OP_JUMP)
                self.outputWords.append(word)
                tree = stat[op_index]
                n = len(tree)
                multi_blocks = []
                patch_tail = []
                for i in range(0, n, 2):
                    label = self.globals.eval(tree[i])
                    if i>>1 != label:
                        lineNumber = tree[i].value.lineNumber
                        raise Exception(f'line: {lineNumber}, label out of order ({label} != {i>>1})')
                    block = MicroWordBlock(self.globals, tree[i+1])
                    head = block.outputWords[0]
                    self.outputWords.append(head)
                    if len(block) == 1:
                        if head.field_values['seq.op'] == SEQ_OP_NEXT:
                            patch_tail.append((len(self.outputWords), head))
                    else:
                        multi_blocks.append((len(self.outputWords), block))
                for pc, block in multi_blocks:
                    top = len(self.outputWords)
                    head = block.outputWords[0]
                    head.update('seq.op', SEQ_OP_JUMP)
                    head.update('seq.address', top-pc)
                    tail = block.outputWords[-1]
                    self.outputWords.extend(block.outputWords[1:])
                    if tail.field_values['seq.op'] == SEQ_OP_NEXT:
                        patch_tail.append((len(self.outputWords), tail))
                next = len(self.outputWords)
                for pc, tail in patch_tail:
                    offset = next - pc
                    if offset != 0:
                        tail.update('seq.op', SEQ_OP_JUMP)
                        tail.update('seq.address', offset)
                return
        self.outputWords.append(word)

    def updatePC(self, startAddress):
        for i, mc in enumerate(self.outputWords):
            mc.pc = startAddress + i

    def getOutput(self):
        format = f'{{0:0{self.globals.seq_width >> 2}x}}'
        results = []
        for mc in self.outputWords:
            code = format.format(mc.word)
            comment = mc.genComment()
            results.append(f'{code} // {mc.pc:4d}: {comment}')
        return results
    
    def getComments(self):
        return [w.comment for w in self.outputWords]
    
    def __len__(self):
        return len(self.outputWords)

class Generator(object):
    def __init__(self, tree):
        self.globals = Globals()
        self.procedureBlocks = {}
        procedureTrees = self.globals.pass1(tree)
        for name, stat_list in procedureTrees.items():
            self.procedureBlocks[name] = MicroWordBlock(self.globals, stat_list)

    def write(self, file_name):
        names = list(self.procedureBlocks.keys())
        names.remove('main')
        names = ['main'] + names
        address = 0
        for name in names:
            block = self.procedureBlocks[name]
            block.updatePC(address)
            self.globals.procStartWords[name] = block.outputWords[0]
            address += len(block)

        self.globals.resolveRefs()

        a1, a2 = self.globals.fields['seq.address']
        w = abs(a1-a2)+1
        word_count = 1 << w
        commentSet = set()
        with open(file_name, 'wt') as f:
            address = 0
            for name in names:
                block = self.procedureBlocks[name]
                commentSet.update(block.getComments())
                output = block.getOutput()
                for line in output:
                    f.write(line + '\n')
                address += len(output)
            format = f'{{0:0{self.globals.seq_width >> 2}x}}'
            for i in range(word_count-address):
                f.write(format.format(0) + '\n')
