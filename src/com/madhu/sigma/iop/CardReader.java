
package com.madhu.sigma.iop;

import java.io.FileInputStream;
import java.io.IOException;

/**
 * Card reader IOP
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class CardReader extends IOProcessor {
	protected static final int STATE_READY = 0;
	protected static final int STATE_BUSY = 1;
	protected static final int STATE_CLOSED = 2;

	protected int state;
	protected FileInputStream fis;
	protected int cardNumber;
	protected String fileName;
	protected boolean verbose;

	public CardReader() {
	}

	protected void init(String[] params) throws Exception {
		this.fileName = params[0];
		if (params.length >= 2) {
			this.verbose = params[1].equals("true");
		}
		fis = new FileInputStream(fileName);
		state = STATE_READY;
	}

	public void reset() {
		try {
			if (fis != null) {
				fis.close();
			}
			fis = new FileInputStream(fileName);
			state = STATE_READY;
			cardNumber = 0;
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
					cardNumber += 1;
					if (verbose) {
						System.out.println(getName() + " reading " + n +
							" bytes into WA(." + Integer.toHexString(ba >> 2) +
							") CARD " + cardNumber);
					}
					for (int i=0; i<120; i+=1) {
						int b = fis.read();
						if (b == -1) {
							fis.close();
							state = STATE_CLOSED;
							throw new IllegalArgumentException("End of deck!");
						}
						if (i < n) {
							memory.writeByte(ba + i, b);
						}
					}
				} else {
					throw new IllegalArgumentException(getName() + " can only read!");
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
