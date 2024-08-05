
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
        lines.append('const seq.width = 40;')
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

if __name__ == '__main__':
    fields = {}
    fields['seq_address_mux'] = 2
    fields['seq_op'] = 2
    fields['seq_condition'] = 3
    fields['sxop'] = 4
    fields['ende'] = 1
    fields['testa'] = 1
    fields['__blank1'] = 1
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
    fields['__blank2'] = 2
    fields['seq_address'] = 12

    overlaps = {}
    overlaps['_const8'] = (40-8, 8)


    p = Pipeline(40, fields, overlaps)
    print(f'    // {BEGIN_MARKER}')
    print()
    for line in p.getDocs():
        print(f'    // {line}')
    print()
    for line in p.getVerilog():
        print(f'    {line}')
    print()
    print(f'    // {END_MARKER}')

    print()
    print()
    print(f'# {BEGIN_MARKER}')
    print()
    for line in p.getMicroLines():
        print(line)
    print()
    print(f'# {END_MARKER}')
