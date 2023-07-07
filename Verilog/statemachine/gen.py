
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

all_insts = '''
AD AH AI AIO AND ANLZ AW AWM BAL BCR BCS BDR BIR CAL1 CAL2 CAL3 CAL4 CB CBS CD CH CI CLM CLR CS CVA CVS CW
DA DC DD DH DL DM DS DSA DST DW EBS EOR EXU FAL FAS FDL FDS FML FMS FSL FSS HIO INT LAD LAH LAW LB LCD
LCF LCFI LCH LCW LD LH LI LM LPSD LRP LS LW MBS MH MI MMC MSP MTB MTH MTW MW OR PACK PLM PLW PSM PSW RD
S SD SF SH SIO STB STD STFC STH STM STS STW SW TBS TDV TIO TTBS UNPK WAIT WD XPSD XW
'''

if __name__ == '__main__':
    # gen_ol()
    # gen_ou()
    for i in all_insts.split():
        #print(f'{i}: exec_{i};')
        print(f'    task automatic exec_{i}; begin')
        print(f'        phase <= PCP2;')
        print(f'    end endtask;')
        print()
