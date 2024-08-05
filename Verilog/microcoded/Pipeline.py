
BEGIN_MARKER = '---- BEGIN Pipeline definitions DO NOT EDIT'
END_MARKER = '---- END Pipeline definitions DO NOT EDIT'

class Pipeline(object):
    def __init__(self, width, fields, overlaps):
        self.width = width
        self.fields = fields
        self.overlaps = overlaps

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
            end = start + width-1
            if n % 4 == 0:
                lines.append(markers)
            if width == 1:
                lines.append(f'{spaces}| - {name}[{start}]')
            else:
                lines.append(f'{spaces}| - {name}[{start}:{end}] {width} bits')
            start += width
            n += 1
        for name, (start, width) in self.overlaps.items():
            spaces = ' '*start
            end = start + width-1
            if width == 1:
                lines.append(f'{spaces}| - {name}[{start}]')
            else:
                lines.append(f'{spaces}| - {name}[{start}:{end}] {width} bits')
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
    fields['seq_address_mux'] = 2
    fields['seq_op'] = 2
    fields['seq_condition'] = 3
    fields['sxop'] = 4
    fields['ende'] = 1
    fields['testa'] = 1
    fields['rrxa'] = 1
    fields['wd_en'] = 1
    fields['dx1'] = 1
    fields['axrr'] = 1
    fields['axs'] = 1
    fields['exconst8'] = 1
    fields['e_count'] = 2
    fields['pxqxp'] = 1
    fields['pxd'] = 1
    fields['rrxs'] = 1
    fields['uc_debug'] = 1
    fields['__unused'] = 19
    fields['seq_address'] = 12

    overlaps = {}
    overlaps['_const8'] = (width-8, 8)


    p = Pipeline(width, fields, overlaps)
    p.writeVerilog(sys.argv[1])
    p.writeMicro(sys.argv[2])
