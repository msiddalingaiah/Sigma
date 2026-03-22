
f = open('sighcp2.txt', 'r')
for j in range(108):
	print '\nCard %d\n' % (j+1)
	for i in range(0x1e):
		line = f.readline()
		print line.rstrip()
	f.readline()
