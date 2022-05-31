
def printTable():
	code = 0
	for i in inst:
		if i != 'x':
			istr = '"%s"' % (i),
		else:
			istr = '"?.%02X"' % (code),
		print '%6s,' % istr,
		code += 1
		if code % 8 == 0:
			print

def printCode():
	code = 0
	for i in inst:
		if i != 'x':
			print '\t\tcase 0x%02X: do%s(iWord); break;' % (code, i)
		else:
			print '\t\tcase 0x%02X: do%02X(iWord); break;' % (code, code)
		code += 1
	code = 0
	print
	for i in inst:
		if i != 'x':
			print '\tpublic void do%s(int iWord) {' % i
		else:
			print '\tpublic void do%02X(int iWord) {' % code
		print '\t\tString dis = Disassembler.decode(iWord);'
		print '\t\tthrow new IllegalArgumentException("Unimplemented instruction: " + dis);'
		print '\t}'
		print
		code += 1

def printDisMap():
	code = 0
	for i in inst:
		if i != 'x':
			if i in immediate:
				print 'instruction[0x%02X] = new ImmediateInstruction(0x%02X, "%s", "");' % (code, code, i)
			elif i in branch:
				print 'instruction[0x%02X] = new BranchInstruction(0x%02X, "%s", "");' % (code, code, i)
			else:
				print 'instruction[0x%02X] = new Instruction(0x%02X, "%s", "");' % (code, code, i)
		else:
			print 'instruction[0x%02X] = new Instruction(0x%02X, "?.%02X", "");' % (code, code, code)
		code += 1

inst = [ "x", "x", "LCFI", "x", "CAL1", "CAL2", "CAL3", "CAL4", "PLW", "PSW", "PLM", "PSM", "x", "x", "LPSD", "XPSD", "AD", "CD", "LD", "MSP", "x", "STD", "x", "x", "SD", "CLM", "LCD", "LAD", "FSL", "FAL", "FDL", "FML", "AI", "CI", "LI", "MI", "SF", "S", "x", "x", "CVS", "CVA", "LM", "STM", "x", "x", "WAIT", "LRP", "AW", "CW", "LW", "MTW", "x", "STW", "DW", "MW", "SW", "CLR", "LCW", "LAW", "FSS", "FAS", "FDS", "FMS", "TTBS", "TBS", "x", "x", "ANLZ", "CS", "XW", "STS", "EOR", "OR", "LS", "AND", "SIO", "TIO", "TDV", "HIO", "AH", "CH", "LH", "MTH", "x", "STH", "DH", "MH", "SH", "x", "LCH", "LAH", "x", "x", "x", "x", "CBS", "MBS", "x", "EBS", "BDR", "BIR", "AWM", "EXU", "BCR", "BCS", "BAL", "INT", "RD", "WD", "AIO", "MMC", "LCF", "CB", "LB", "MTB", "STFC", "STB", "PACK", "UNPK", "DS", "DA", "DD", "DM", "DSA", "DC", "DL", "DST" ]
immediate = ['LCFI', 'AI', 'CI', 'LI', 'MI']
branch = ['BDR', 'BIR', 'BCR', 'BCS', 'BAL']
printDisMap()
