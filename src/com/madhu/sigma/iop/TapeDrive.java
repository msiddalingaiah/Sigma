
package com.madhu.sigma.iop;

import java.io.IOException;
import java.io.RandomAccessFile;

/*
Tape order codes:

01 Write
02 Read forward
03 Set correction
04 Sense
0B Mode control
0C Read backward
13 Rewind and interrupt
1B Test
23 Rewind off-line
33 Rewind
43 Space record forward
4B Space record backward
53 Space file forward
5B Space file backward
63 Set erase
73 Write tape mark
*/

/**
 * Tape drive IO processor
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class TapeDrive extends IOProcessor {
	protected static final int STATE_READY = 0;
	protected static final int STATE_BUSY = 1;
	protected static final int STATE_CLOSED = 2;

	protected static final int ORDER_WRITE = 0x00;
	protected static final int ORDER_READ = 0x02;
	protected static final int ORDER_SET_CORRECTION = 0x03;
	protected static final int ORDER_SENSE = 0x04;
	protected static final int ORDER_MODE_CONTROL = 0x0B;
	protected static final int ORDER_READ_BACKWARD = 0x0C;
	protected static final int ORDER_REWING_AND_INTERRUPT = 0x13;
	protected static final int ORDER_TEST = 0x1B;
	protected static final int ORDER_REWIND_OFFLINE = 0x23;
	protected static final int ORDER_REWIND = 0x33;
	protected static final int ORDER_SPACE_RECORD_FORWARD = 0x43;
	protected static final int ORDER_SPACE_RECORD_BACKWARD = 0x4B;
	protected static final int ORDER_SPACE_FILE_FORWARD = 0x53;
	protected static final int ORDER_SPACE_FILE_BACKWARD = 0x5B;
	protected static final int ORDER_SET_ERASE = 0x63;
	protected static final int ORDER_WRITE_TAPE_MARK = 0x73;

	protected int state;
	protected RandomAccessFile raFile;
	protected int recordNumber;
	protected String fileName;
	protected int recordLength;
	protected byte[] header;
	protected boolean verbose;

	public TapeDrive() {
		header = new byte[4];
	}

	protected void init(String[] params) throws Exception {
		this.fileName = params[0];
		if (params.length >= 2) {
			this.verbose = params[1].equals("true");
		}
		raFile = new RandomAccessFile(fileName, "r");
		state = STATE_READY;
	}

	public void reset() {
		try {
			if (raFile != null) {
				raFile.close();
			}
			raFile = new RandomAccessFile(fileName, "r");
			state = STATE_READY;
			recordNumber = 0;
		} catch (Exception e) {
			e.printStackTrace();
		}
	}

	public void run() {
		try {
			while (true) {
				int order = getOrder();
				switch (order) {
					case ORDER_READ:
					int ba = getByteAddress();
					int count = getByteCount();
					recordNumber += 1;
					if (verbose) {
						System.out.println(getName() + " reading " + count +
							" bytes into WA(." + Integer.toHexString(ba >> 2) +
							") record " + recordNumber);
					}
					raFile.skipBytes(4);	// skip previous record info
					raFile.read(header);
					if (header[2] == -1 && header[3] == -1) {
						// EOF??? Note sure...
						System.out.print(getName() + " EOF? header = " +
							Integer.toHexString(header[0]) + " " +
							Integer.toHexString(header[1]) + " " +
							Integer.toHexString(header[2]) + " " +
							Integer.toHexString(header[3]));
						break;
					}
					recordLength = header[0];	// I think this is right...
					recordLength &= 0xff;
					for (int i=0; i<recordLength; i+=1) {
						int b = raFile.read();
						if (b == -1) {
							raFile.close();
							raFile = null;
							state = STATE_CLOSED;
							break;
						}
						if (i < count) {
							memory.writeByte(ba + i, b);
						}
					}
					break;

					case ORDER_REWIND:
					if (verbose) {
						System.out.println(getName() + " Rewind");
					}
					raFile.seek(0);
					recordNumber = 0;
					break;

					case ORDER_SPACE_RECORD_FORWARD:
					if (verbose) {
						System.out.println(getName() +
							" Space record forward");
					}
					raFile.skipBytes(4);
					raFile.read(header);
					if (header[2] == -1 && header[3] == -1) {
						System.out.print(getName() + " EOF? header = " +
							Integer.toHexString(header[0]) + " " +
							Integer.toHexString(header[1]) + " " +
							Integer.toHexString(header[2]) + " " +
							Integer.toHexString(header[3]));
						break;
					}
					recordLength = header[0];
					recordLength &= 0xff;
					raFile.skipBytes(recordLength);
					recordNumber += 1;
					break;

					case ORDER_SPACE_RECORD_BACKWARD:
					if (verbose) {
						System.out.println(getName() +
							" Space record backward");
					}
					long pos = raFile.getFilePointer();
					pos -= recordLength;
					pos -= 8;
					if (pos < 0) {
						if (verbose) {
							System.out.println(getName() +
								" BOT HIT!");
						}
						pos = 0;
					}
					raFile.seek(pos);
					recordNumber -= 1;
					break;

					case ORDER_SPACE_FILE_FORWARD:
					if (verbose) {
						System.out.println(getName() +
							" Space file forward");
					}
					while (true) {
						raFile.skipBytes(4);
						raFile.read(header);
						if (header[0] == -1) {
							throw new IllegalArgumentException(
								"EOF HIT!");
						}
						if (header[2] == -1 && header[3] == -1) {
							break;
						}
						recordLength = header[0];
						recordLength &= 0xff;
						raFile.skipBytes(recordLength);
					}
					recordNumber = 0;
					break;

					default:
					System.out.print(getName() + " order: ." +
						Integer.toHexString(order).toUpperCase());
					System.out.print(getName() + " CW0, CW1: .");
					System.out.print(Integer.toHexString(command0).toUpperCase());
					System.out.print(", .");
					System.out.println(Integer.toHexString(command1).toUpperCase());
					throw new IllegalArgumentException(
						"Order not supported: ." +
						Integer.toHexString(order).toUpperCase());
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
