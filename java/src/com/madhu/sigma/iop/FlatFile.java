
package com.madhu.sigma.iop;

import java.io.FileInputStream;
import java.io.IOException;

/**
 * A simple IOP that can read flat machine code files
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class FlatFile extends IOProcessor {
	protected static final int STATE_READY = 0;
	protected static final int STATE_BUSY = 1;
	protected static final int STATE_CLOSED = 2;

	protected int state;
	protected FileInputStream fis;
	protected int recordNumber;
	protected String fileName;
	protected boolean verbose;

	public FlatFile() {
	}

	protected void init(String[] params) throws Exception {
		this.fileName = params[0];
		fis = new FileInputStream(fileName);
		if (params.length > 1) {
			verbose = params[1].equals("true");
		} else {
			verbose = false;
		}
		state = STATE_READY;
	}

	public void reset() {
		try {
			if (fis != null) {
				fis.close();
			}
			fis = new FileInputStream(fileName);
			state = STATE_READY;
			recordNumber = 0;
		} catch (Exception e) {
			e.printStackTrace();
		}
	}

	public void run() {
		try {
			while (true) {
				int orderType = getOrderType();
				if (orderType == ORDER_TYPE_READ) {
					int ba = getByteAddress();
					int n = getByteCount();
					recordNumber += 1;
					if (verbose) {
						System.out.println(getName() + " reading " + n +
							" bytes into WA(." + Integer.toHexString(ba >> 2) +
							") record " + recordNumber);
					}
					for (int i=0; i<n; i+=1) {
						int b = fis.read();
						if (b == -1) {
							fis.close();
							state = STATE_CLOSED;
							break;
						}
						memory.writeByte(ba + i, b);
					}
				} else {
					System.out.print(getName() + " CW0, CW1: .");
					System.out.print(Integer.toHexString(command0).toUpperCase());
					System.out.print(", .");
					System.out.println(Integer.toHexString(command1).toUpperCase());
				}
				int flags = getFlags();
				if ((flags & FLAG_CC_MASK) != 0) {
					nextCommand();
				} else {
					break;
				}
			}
		} catch (IOException e) {
			e.printStackTrace();
		}
		state = STATE_READY;
	}

	public void startIO(int dwCommandAddr) {
		int cc = cpu.getCC();
		cc &= 3;
		if (state == STATE_READY) {
			state = STATE_BUSY;
			init(dwCommandAddr);
			run();	// should really start a thread here
		} else {
			cc |= 8;	// No status to return
		}
		cpu.setCC(cc);
	}

	public void testIO() {
		int cc = cpu.getCC();
		cc &= 3;
		if (state != STATE_READY) {
			cc |= 8;	// No status to return
		}
		cpu.setCC(cc);
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
