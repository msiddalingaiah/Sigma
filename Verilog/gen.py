
def gen_ol():
    for o in range(16):
        mask = 8
        line = []
        for bit in range(4, 8):
            inv = '' if mask & o else '~'
            line.append(f'{inv}o[{bit}]')
            mask >>= 1
        print(f'    wire ol{o:x} = ' + ' & '.join(line) + ';')

def gen_ou():
    for o in range(8):
        mask = 4
        line = []
        for bit in range(1, 4):
            inv = '' if mask & o else '~'
            line.append(f'{inv}o[{bit}]')
            mask >>= 1
        print(f'    wire ou{o:x} = ' + ' & '.join(line) + ';')

if __name__ == '__main__':
    # gen_ol()
    gen_ou()
