
ebcdic = \
	"             \r                  " + \
	"     \n                          " + \
	"           .<(+|&         !$*); " + \
	"-/         ,%_>?          :#@'=\"" + \
	" abcdefghi       jklmnopqr      " + \
	"  stuvwxyz               `      " + \
	" ABCDEFGHI       JKLMNOPQR      " + \
	"  STUVWXYZ      0123456789      "
for i in range(128):
	c = chr(i)
	if c in ebcdic:
		print '0x%02X, ' % ebcdic.index(c),
	else:
		print '0x40, ',
	if (i+1) % 4 == 0:
		print
