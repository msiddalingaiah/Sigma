
package com.madhu.sigma.iop;

import java.io.*;

import com.madhu.sigma.*;

public class AssemblyReader extends IOProcessor {
	protected static final int STATE_READY = 0;
	protected static final int STATE_BUSY = 1;
	protected static final int STATE_CLOSED = 2;

	protected int state;
	protected BufferedReader br;
	protected int lineNumber;
	protected String fileName;
	protected boolean verbose;

	public AssemblyReader() {
	}

	protected void init(String[] params) throws Exception {
		this.fileName = params[0];
		if (params.length >= 2) {
			this.verbose = params[1].equals("true");
		}
		state = STATE_READY;
	}

	public void reset() {
		try {
			if (br != null) {
				br.close();
			}
			state = STATE_READY;
			lineNumber = 0;
		} catch (Exception e) {
			e.printStackTrace();
		}
	}

	public void run() {
		try {
			int orderType = getOrderType();
			if (orderType == ORDER_TYPE_READ) {
				br = new BufferedReader(new FileReader(fileName));
				String line = br.readLine();
				while (line != null) {
					lineNumber += 1;
					String addrStr = null;
					String instStr = null;
					int n = line.length();
					for (int i=0; i<n; i+=1) {
						if (Character.isWhitespace(line.charAt(i))) {
							addrStr = line.substring(0, i).trim();
							instStr = line.substring(i).trim();
							break;
						}
					}
					if (addrStr == null || addrStr.length() == 0 ||
						instStr == null || instStr.length() == 0) {
						System.out.println("line ignored: " + line);
					} else {
						int addr;
						if (addrStr.charAt(0) == '.') {
							addr = Integer.parseInt(addrStr.substring(1), 16);
						} else {
							addr = Integer.parseInt(addrStr);
						}
						int iWord = OpCode.encode(instStr);
						memory.writeWord(addr, iWord);
					}
					line = br.readLine();
				}
				br.close();
				br = null;
			} else {
				throw new IllegalArgumentException(getName() + " can only read!");
			}
		} catch (IOException e) {
			e.printStackTrace();
		} finally {
			if (br != null) {
				try {
					br.close();
				} catch (Exception e) {
				}
				br = null;
				lineNumber = 0;
			}
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
