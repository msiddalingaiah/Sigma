
BEGIN_MARKER = '---- BEGIN Pipeline definitions DO NOT EDIT'
END_MARKER = '---- END Pipeline definitions DO NOT EDIT'

class Pipeline(object):
    def __init__(self, width, fields, overlaps, constants):
        self.width = width
        self.fields = fields
        self.overlaps = overlaps
        self.constants = constants
        start = 0
        for name, w in fields.items():
            end = start + w
            if end > width:
                raise Exception(f'field {name} exceeds width of {width} bits by {end-width} bit(s)')
            start += w
        for name, (start, w) in self.overlaps.items():
            end = start + w
            if end > width:
                raise Exception(f'field {name} exceeds width of {width} bits by {end-width} bit(s)')

    def getDocs(self):
        lines = []
        lines.append('Microcode pipeline register')
        arr = []
        for i in range(0, self.width+8, 8):
            arr.append('%-8d' % i)
        lines.append(''.join(arr))
        arr = []
        for i in range(0, self.width, 8):
            arr.append('-------')
        markers = '|' + '|'.join(arr) + '|'
        start = 0
        n = 0
        for name, width in self.fields.items():
            spaces = ' '*start
            space_w = '_'*(width-2)
            end = start + width-1
            if n % 4 == 0:
                lines.append(markers)
            if width == 1:
                lines.append(f'{spaces}| - {name}[{start}]')
            else:
                lines.append(f'{spaces}|{space_w}| - {name}[{start}:{end}] {width} bits')
            start += width
            n += 1
        for name, (start, width) in self.overlaps.items():
            spaces = ' '*start
            space_w = '_'*(width-2)
            end = start + width-1
            if width == 1:
                lines.append(f'{spaces}| - {name}[{start}]')
            else:
                lines.append(f'{spaces}|{space_w}| - {name}[{start}:{end}] {width} bits')
        return lines

    def getVerilog(self):
        lines = []
        lines.append(f'reg [0:{self.width-1}] pipeline;')
        start = 0
        for name, width in self.fields.items():
            end = start + width-1
            if width == 1:
                lines.append(f'wire {name} = pipeline[{start}];')
            else:
                lines.append(f'wire [0:{width-1}] {name} = pipeline[{start}:{end}];')
            start += width
        for name, (start, width) in self.overlaps.items():
            end = start + width-1
            if width == 1:
                lines.append(f'wire {name} = pipeline[{start}];')
            else:
                lines.append(f'wire [0:{width-1}] {name} = pipeline[{start}:{end}];')
            start += width
        lines.append('')
        for name, value in self.constants.items():
            lines.append(f'localparam {name} = {value};')
        return lines

    def getMicroLines(self):
        lines = []
        lines.append('const seq.endian = BIG;')
        lines.append(f'const seq.width = {self.width};')
        lines.append('')
        start = 0
        for name, width in self.fields.items():
            if name.startswith('seq_'):
                name = name.replace('seq_', 'seq.')
            end = start + width-1
            lines.append(f'field {name} = {start}:{end};')
            start += width
        for name, (start, width) in self.overlaps.items():
            end = start + width-1
            lines.append(f'field {name} = {start}:{end};')
        lines.append('')
        for name, value in self.constants.items():
            lines.append(f'const {name} = {value};')
        return lines

    def writeVerilog(self, filename):
        with open(filename) as f:
            sourcelines = f.readlines()
        with open(filename, "w") as f:
            for lineIndex in range(len(sourcelines)):
                if BEGIN_MARKER in sourcelines[lineIndex]:
                    break
                f.write(sourcelines[lineIndex])
            while lineIndex < len(sourcelines):
                if END_MARKER in sourcelines[lineIndex]:
                    break
                lineIndex += 1
            lineIndex += 1

            f.write(f'    // {BEGIN_MARKER}\n\n')
            for line in p.getDocs():
                f.write(f'    // {line}\n')
            f.write('\n')
            for line in self.getVerilog():
                f.write(f'    {line}\n')
            f.write(f'\n    // {END_MARKER}\n')
            while lineIndex < len(sourcelines):
                f.write(sourcelines[lineIndex])
                lineIndex += 1

    def writeMicro(self, filename):
        with open(filename) as f:
            sourcelines = f.readlines()
        with open(filename, "w") as f:
            for lineIndex in range(len(sourcelines)):
                if BEGIN_MARKER in sourcelines[lineIndex]:
                    break
                f.write(sourcelines[lineIndex])
            while lineIndex < len(sourcelines):
                if END_MARKER in sourcelines[lineIndex]:
                    break
                lineIndex += 1
            lineIndex += 1

            f.write(f'# {BEGIN_MARKER}\n\n')
            # for line in p.getDocs():
            #     f.write(f'# {line}\n')
            # f.write('\n')
            for line in self.getMicroLines():
                f.write(f'{line}\n')
            f.write(f'\n# {END_MARKER}\n')
            while lineIndex < len(sourcelines):
                f.write(sourcelines[lineIndex])
                lineIndex += 1

import sys

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('usage: python Pipeline.py <verilog-file> <micro-def-file>')
        sys.exit(1)

    width = 56

    fields = {}
    fields['seq_op'] = 2
    fields['seq_address_mux'] = 2
    fields['seq_condition'] = 3
    fields['ax'] = 4
    fields['dx'] = 3
    fields['px'] = 3
    fields['qx'] = 1
    fields['rrx'] = 4
    fields['sxop'] = 4
    fields['ende'] = 1
    fields['testa'] = 1
    fields['wd_en'] = 1
    fields['uc_debug'] = 1
    fields['__unused'] = 14
    fields['seq_address'] = 12

    overlaps = {}
    overlaps['_const8'] = (width-8, 8)

    constants = {}
    constants['SX_ADD'] = 0
    constants['SX_SUB'] = 1
    constants['SX_D'] = 2

    constants['AX_NONE'] = 0
    constants['AX_D'] = 1
    constants['AX_S'] = 2
    constants['AX_RR'] = 3

    constants['DX_NONE'] = 0
    constants['DX_1'] = 1

    constants['PX_NONE'] = 0
    constants['PX_D'] = 1
    constants['PX_Q'] = 2

    constants['QX_NONE'] = 0
    constants['QX_P'] = 1

    constants['RRX_NONE'] = 0
    constants['RRX_S'] = 1

    constants['COND_NONE'] = 0
    constants['COND_S_GT_ZERO'] = 1
    constants['COND_S_LT_ZERO'] = 2

    constants['ADDR_MUX_SEQ'] = 0
    constants['ADDR_MUX_OPCODE'] = 1

    p = Pipeline(width, fields, overlaps, constants)
    p.writeVerilog(sys.argv[1])
    p.writeMicro(sys.argv[2])
