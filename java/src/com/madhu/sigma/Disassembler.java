
package com.madhu.sigma;

import java.io.FileInputStream;

/**
 * A crude Sigma disassembler
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class Disassembler {
	private static String toASCII =
	  // 0123456789ABCDEF0123456789ABCDEF
		"................................" +
		"................................" +
		" ...........<(+|&.........!$*);." +
		"-/.........,%_>?..........:#@'=\"" +
		".abcdefghi.......jklmnopqr......" +
		"..stuvwxyz...............`......" +
		".ABCDEFGHI.......JKLMNOPQR......" +
		"..STUVWXYZ......0123456789......";

	public Disassembler() {
	}

	public void disassemble(MainMemory memory, int start, int end) {
		OpCode[] instArray = OpCode.getOpCodes();
		for (int addr=start; addr<end; addr++)  {
			int iWord = memory.readWord(addr);
			int code = (iWord >>> 24) & 0x7f;
			OpCode inst = instArray[code];
			System.out.print(toHexString(addr, 3, ' '));
			System.out.print("\t");
			System.out.print(toHexString(iWord, 8, '0'));
			System.out.print("\t");
			System.out.println(inst.decode(iWord));
		}
	}

	public static String decode(int iWord) {
		OpCode[] instArray = OpCode.getOpCodes();
		int code = (iWord >>> 24) & 0x7f;
		OpCode inst = instArray[code];
		return inst.decode(iWord);
	}

	public static String toHexString(int value, int nChars, char fillChar) {
		String hex = Integer.toHexString(value).toUpperCase();
		StringBuffer sb = new StringBuffer(nChars);
		sb.append('.');
		int n = hex.length();
		for (int i=0; i<nChars-n; i++) {
			sb.append(fillChar);
		}
		sb.append(hex);
		return sb.toString();
	}

	public static void main(String args[]) throws Exception {
		FileInputStream fis = new FileInputStream(args[0]);
		OpCode[] instArray = OpCode.getOpCodes();
		int record = 1;
		int addr = 0xA000;
		out: while (true) {
			// for (int i=0; i<8; i+=1) {
			// 	int b = fis.read();
			// }
			System.out.println();
			// System.out.println("Record " + record++);
			// System.out.println();
			for (int j=0; j<32; j+=1) {
				int iWord = 0;
				for (int i=0; i<4; i+=1) {
					int b = fis.read();
					if (b < 0) {
						break out;
					}
					iWord <<= 8;
					iWord |= b;
				}
				int code = (iWord >>> 24) & 0x7f;
				OpCode inst = instArray[code];

				StringBuffer sb = new StringBuffer(30);
				sb.append(Disassembler.toHexString(addr, 3, ' '));
				sb.append("  ");
				sb.append(Disassembler.toHexString(iWord, 8, '0'));
				sb.append("  ");
				sb.append(inst.decode(iWord));
				int n = sb.length();
				for (int k=0; k<40-n; k+=1) {
					sb.append(' ');
				}
				sb.append(toASCII.charAt((iWord >> 24) & 0xff));
				sb.append(toASCII.charAt((iWord >> 16) & 0xff));
				sb.append(toASCII.charAt((iWord >> 8) & 0xff));
				sb.append(toASCII.charAt((iWord) & 0xff));
				System.out.println(sb.toString());
				addr += 1;
			}
		}
		fis.close();
	}
}
