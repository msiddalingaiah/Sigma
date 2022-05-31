
import java.io.*;

public class EBCDIC {
	public static String ebcdic =
		"             \r                  " +
		"     \n                          " +
		"           .<(+|&         !$*); " +
		"-/         ,%_>?          :#@'=\"" +
		" abcdefghi       jklmnopqr      " +
		"  stuvwxyz               `      " +
		" ABCDEFGHI       JKLMNOPQR      " +
		"  STUVWXYZ      0123456789      ";

	public static void main(String args[]) throws Exception {
		/*
		for (int i=0; i<ebcdic.length(); i+=1) {
			char c = ebcdic.charAt(i);
			if (c == '\r') {
				c = '\n';
			}
		 	System.out.println(i + " ." + Integer.toHexString(i) + " :" + c);
		}
		*/
		boolean keyed = false;
		String file = args[0];
		if (args.length == 2 && args[0].equals("-k")) {
			keyed = true;
			file = args[1];
		}
		FileInputStream fis = new FileInputStream(file);
		int b = fis.read();
		while (b != -1) {
			if (keyed) {
				int key = 0;
				for (int i=0; i<3; i++) {
					b = fis.read();
					key <<= 8;
					key |= b;
				}
				String skey = Integer.toString(key);
				int sn = skey.length();
				for (int i=0; i<8-sn; i++) {
					System.out.print(' ');
				}
				System.out.print(
					skey.substring(0, sn-3) + "." +
					skey.substring(sn-3) + " ");
				int n = 0;
				for (int i=0; i<4; i++) {
					b = fis.read();
					n <<= 8;
					n |= b;
				}
				for (int i=0; i<n; i++) {
					b = fis.read();
					char c = ebcdic.charAt(b);
					if (c == '\r') {
						c = '\n';
					}
					System.out.print(c);
				}
				System.out.println();
			} else {
				char c = ebcdic.charAt(b);
				if (c == '\r') {
					c = '\n';
				}
				System.out.print(c);
			}
			b = fis.read();
		}
		fis.close();
	}
}
