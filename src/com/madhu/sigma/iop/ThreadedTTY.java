
package com.madhu.sigma.iop;

import java.io.*;

/**
 * A multithreaded teletype IOP
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class ThreadedTTY extends IOProcessor {
	public static String toASCII =
	  // 0123456789ABCD EF012345 6789ABCDEF
		"             \r       \n          " +
		"     \n                          " +
		"           .<(+|&         !$*); " +
		"-/         ,%_>?          :#@'=\"" +
		" abcdefghi       jklmnopqr      " +
		"  stuvwxyz               `      " +
		" ABCDEFGHI       JKLMNOPQR      " +
		"  STUVWXYZ      0123456789      ";

	public static int[] toEBCDIC = {
		0x40,  0x40,  0x40,  0x40, 0x40,  0x40,  0x40,  0x40,
		0x40,  0x40,  0x25,  0x40, 0x40,  0x0D,  0x40,  0x40,
		0x40,  0x40,  0x40,  0x40, 0x40,  0x40,  0x40,  0x40,
		0x40,  0x40,  0x40,  0x40, 0x40,  0x40,  0x40,  0x40,
		0x40,  0x5A,  0x7F,  0x7B, 0x5B,  0x6C,  0x50,  0x7D,
		0x4D,  0x5D,  0x5C,  0x4E, 0x6B,  0x60,  0x4B,  0x61,
		0xF0,  0xF1,  0xF2,  0xF3, 0xF4,  0xF5,  0xF6,  0xF7,
		0xF8,  0xF9,  0x7A,  0x5E, 0x4C,  0x7E,  0x6E,  0x6F,
		0x7C,  0xC1,  0xC2,  0xC3, 0xC4,  0xC5,  0xC6,  0xC7,
		0xC8,  0xC9,  0xD1,  0xD2, 0xD3,  0xD4,  0xD5,  0xD6,
		0xD7,  0xD8,  0xD9,  0xE2, 0xE3,  0xE4,  0xE5,  0xE6,
		0xE7,  0xE8,  0xE9,  0x40, 0x40,  0x40,  0x40,  0x6D,
		0xB9,  0x81,  0x82,  0x83, 0x84,  0x85,  0x86,  0x87,
		0x88,  0x89,  0x91,  0x92, 0x93,  0x94,  0x95,  0x96,
		0x97,  0x98,  0x99,  0xA2, 0xA3,  0xA4,  0xA5,  0xA6,
		0xA7,  0xA8,  0xA9,  0x40, 0x4F,  0x40,  0x40,  0x40
	};

	protected static final int STATE_READY = 0;
	protected static final int STATE_BUSY = 1;

	protected int state;
	protected boolean commandAvailable;
	protected BufferedReader stdin;

	public ThreadedTTY() {
	}

	protected void init(String[] params) throws Exception {
		state = STATE_BUSY;
		commandAvailable = false;
		// stdin = new BufferedReader(
		//	new InputStreamReader(System.in));
		Thread t = new Thread(this);
		t.start();
	}

	public void reset() {
		setAvailable(false);
		try {
			while (System.in.available() > 0) {
				System.in.read();
			}
		} catch (IOException e) {
			e.printStackTrace();
		}
	}

	protected synchronized void waitForCommand() {
		while (!commandAvailable) {
			try {
				wait();
			} catch (InterruptedException e) {
			}
		}
	}

	protected String readLine() throws IOException {
		StringBuffer sb = new StringBuffer(80);
		while (true) {
			if (System.in.available() > 0) {
				int b = System.in.read();
				if (b == '\n') {
					return sb.toString();
				}
				sb.append((char) b);
			} else {
				Thread.yield();
			}
			if (state == STATE_READY) {
				return "";
			}
		}
	}

	protected synchronized void setAvailable(boolean avail) {
		commandAvailable = avail;
		if (avail) {
			state = STATE_BUSY;
		} else {
			state = STATE_READY;
		}
		notify();
	}

	public void run() {
		try {
			while (true) {
				waitForCommand();
				int orderType = getOrderType();
				if (orderType == ORDER_TYPE_READ) {
					int ba = getByteAddress();
					int bc = getByteCount();
					System.out.print("> ");
					// String line = stdin.readLine();
					String line = readLine();
					int n = bc < line.length() ? bc :
						line.length();
					for (int i=0; i<n; i++) {
						int b = (byte) line.charAt(i);
						memory.writeByte(ba + i, toEBCDIC[b]);
					}
				} else if (orderType == ORDER_TYPE_WRITE) {
					int ba = getByteAddress();
					int bc = getByteCount();
					StringBuffer sb = new StringBuffer(bc);
					for (int i=0; i<bc; i+=1) {
						int b = memory.readByte(ba + i) & 0xff;
						sb.append(toASCII.charAt(b));
					}
					System.out.print(sb.toString());
				}
				int flags = getFlags();
				if ((flags & FLAG_CC_MASK) != 0) {
					nextCommand();
				} else {
					setAvailable(false);
				}
			}
		} catch (IOException e) {
			e.printStackTrace();
		}
	}

	public void startIO(int dwCommandAddr) {
		int cc = cpu.getCC();
		cc &= 3;
		if (state == STATE_READY) {
			init(dwCommandAddr);
			setAvailable(true);
		} else {
			cc |= 8;
		}
		cpu.setCC(cc);
	}

	public void testIO() {
		int cc = cpu.getCC();
		cc &= 3;
		if (state != STATE_READY) {
			cc |= 8;
		}
		cpu.setCC(cc);
		Thread.yield();
	}

	public void haltIO() {
	}

	protected int getAckStatus() {
		int aStat = getUnit();
		return aStat;
	}

	public int testDevice() {
		return 0;
	}

	public int getStatus() {
		return 0;
	}
}
