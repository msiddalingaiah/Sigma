
import re

fileName = 'SigmaCPU.java'
f = open(fileName, 'r')
data = f.read()
f.close()
pat = 'protected void do([0-9A-Z]+)\(int iWord\) {' + \
	'\n\t\tString dis = Disassembler.decode'
p = re.compile(pat)
list = p.findall(data)
n = len(list)
print '%d instructions not implemented' % n
for i in range(n):
	if i % 8 == 0:
		print
	print '%-4s ' % list[i],
print
floatDec = ['FSL', 'FAL', 'FDL', 'FML', 'FSS', 'FAS', \
	'FDS', 'FMS', 'PACK', 'UNPK', 'DS', 'DA', 'DD', \
	'DM', 'DSA', 'DC', 'DL', 'DST']
print
print 'Not including floating and decimal instructions:'
m = 0
for i in range(n):
	if m % 8 == 0:
		print
	if list[i] not in floatDec:
		print '%-4s ' % list[i],
		m += 1
print
print
print '%d instructions remaining' % m
