
package com.madhu.sigma;

/**
 * Sigma main memory
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class MainMemory {
	private static int[] BYTE_MASK = {
		0x00ffffff, 0xff00ffff, 0xffff00ff, 0xffffff00
	};
	private static int[] HALFWORD_MASK = {
		0x0000ffff, 0xffff0000
	};

	protected int[] map;				//  memory map
	protected byte[] writeLocks;		//  physical core page write locks
	protected boolean[] readAccess;		//  virtual mem access protection bits
	protected boolean[] writeAccess;	//  virtual mem access protection bits
	protected boolean[] execAccess;		//  virtual mem access protection bits
	protected int[] memory;				//  physical memory
	protected int[] registers;
	protected boolean slaveMode;
	protected boolean mapEnabled;
	protected byte writeKey;
	protected NonAllowedOperation naoAC;
	protected NonAllowedOperation naoWL;

	public MainMemory(int sizeInBytes) {
		memory = new int[sizeInBytes >>> 2];
		map = new int[(sizeInBytes >> (2 + 9)) + 1];
		writeLocks = new byte[(sizeInBytes >> (2 + 9)) + 1];
		readAccess = new boolean[(sizeInBytes >> (2 + 9)) + 1];
		writeAccess = new boolean[(sizeInBytes >> (2 + 9)) + 1];
		execAccess = new boolean[(sizeInBytes >> (2 + 9)) + 1];
		naoAC = new NonAllowedOperation(
			NonAllowedOperation.MEMORY_PROTECTION,
			"Memory protection fault");
		naoWL = new NonAllowedOperation(
			NonAllowedOperation.MEMORY_PROTECTION,
			"Memory write lock fault");
	}

	public void setRegisters(int[] registers) {
		this.registers = registers;
	}

	public void setMapEnabled(boolean mapEnabled) {
		this.mapEnabled = mapEnabled;
	}

	public boolean isMapEnabled() {
		return mapEnabled;
	}

	public void setSlaveMode(boolean slaveMode) {
		this.slaveMode = slaveMode;
	}

	public void setWriteKey(int writeKey) {
		this.writeKey = (byte) writeKey;
	}

	public void reset() {
		int n = memory.length;
		for (int i=0; i<n; i++) {
			memory[i] = 0;
		}
		setMapEnabled(false);
		setSlaveMode(false);
	}

	// Sign is extended
	public byte readByte(int byteAddress) {
		int[] mem;
		byteAddress &= 0x7ffff;
		int wordAddress = byteAddress >>> 2;
		if (wordAddress < 16) {
			mem = registers;
		} else {
			mem = memory;
			if (mapEnabled) {
				int page = wordAddress >>> 9;
				if (slaveMode && !readAccess[page]) {
					naoAC.fillInStackTrace();
					throw naoAC;
				}
				int mapped = map[page];
				wordAddress &= 0x001ff;
				wordAddress |= mapped;
			}
		}
		int word = mem[wordAddress];
		int off = byteAddress & 0x03;
		return (byte) (word >>> (24 - (off << 3)));
	}

	public void writeByte(int byteAddress, int value) {
		int[] mem;
		byteAddress &= 0x7ffff;
		int wordAddress = byteAddress >>> 2;
		if (wordAddress < 16) {
			mem = registers;
		} else {
			mem = memory;
			if (mapEnabled) {
				int page = wordAddress >>> 9;
				if (slaveMode && !writeAccess[page]) {
					naoAC.fillInStackTrace();
					throw naoAC;
				}
				int mapped = map[page];
				wordAddress &= 0x001ff;
				wordAddress |= mapped;
			}
			byte wl = writeLocks[wordAddress >>> 9];
			if (wl != 0 && writeKey != 0 && wl != writeKey) {
				naoWL.fillInStackTrace();
				throw naoWL;
			}
		}
		int off = byteAddress & 0x03;
		int word = mem[wordAddress];
		word &= BYTE_MASK[off];
		word |= (value & 0xff) << (24 - (off << 3));
		mem[wordAddress] = word;
	}

	// Sign is extended
	public short readHalfWord(int halfWordAddress) {
		int[] mem;
		halfWordAddress &= 0x3ffff;
		int wordAddress = halfWordAddress >>> 1;
		if (wordAddress < 16) {
			mem = registers;
		} else {
			mem = memory;
			if (mapEnabled) {
				int page = wordAddress >>> 9;
				if (slaveMode && !readAccess[page]) {
					naoAC.fillInStackTrace();
					throw naoAC;
				}
				int mapped = map[page];
				wordAddress &= 0x001ff;
				wordAddress |= mapped;
			}
		}
		int word = mem[wordAddress];
		int off = halfWordAddress & 0x01;
		return (short) (word >>> (16 - (off << 4)));
	}

	public void writeHalfWord(int halfWordAddress, int value) {
		int[] mem;
		halfWordAddress &= 0x3ffff;
		int wordAddress = halfWordAddress >>> 1;
		if (wordAddress < 16) {
			mem = registers;
		} else {
			mem = memory;
			if (mapEnabled) {
				int page = wordAddress >>> 9;
				if (slaveMode && !writeAccess[page]) {
					naoAC.fillInStackTrace();
					throw naoAC;
				}
				int mapped = map[page];
				wordAddress &= 0x001ff;
				wordAddress |= mapped;
			}
			byte wl = writeLocks[wordAddress >>> 9];
			if (wl != 0 && writeKey != 0 && wl != writeKey) {
				naoWL.fillInStackTrace();
				throw naoWL;
			}
		}
		byte wl = writeLocks[wordAddress >>> 9];
		int off = halfWordAddress & 0x01;
		int word = mem[wordAddress];
		word &= HALFWORD_MASK[off];
		word |= (value & 0xffff) << (16 - (off << 4));
		mem[wordAddress] = word;
	}

	public int readWord(int wordAddress) {
		int[] mem;
		wordAddress &= 0x1ffff;
		if (wordAddress < 16) {
			mem = registers;
		} else {
			mem = memory;
			if (mapEnabled) {
				int page = wordAddress >>> 9;
				if (slaveMode && !readAccess[page]) {
					naoAC.fillInStackTrace();
					throw naoAC;
				}
				int mapped = map[page];
				wordAddress &= 0x001ff;
				wordAddress |= mapped;
			}
		}
		return mem[wordAddress];
	}

	// for execute memory access checks
	public int fetchInstruction(int wordAddress) {
		int[] mem;
		wordAddress &= 0x1ffff;
		if (wordAddress < 16) {
			mem = registers;
		} else {
			mem = memory;
			if (mapEnabled) {
				int page = wordAddress >>> 9;
				if (slaveMode && !execAccess[page]) {
					naoAC.fillInStackTrace();
					throw naoAC;
				}
				int mapped = map[page];
				wordAddress &= 0x001ff;
				wordAddress |= mapped;
			}
		}
		return mem[wordAddress];
	}

	public void writeWord(int wordAddress, int value) {
		int[] mem;
		wordAddress &= 0x1ffff;
		if (wordAddress < 16) {
			mem = registers;
		} else {
			mem = memory;
			if (mapEnabled) {
				int page = wordAddress >>> 9;
				if (slaveMode && !writeAccess[page]) {
					naoAC.fillInStackTrace();
					throw naoAC;
				}
				int mapped = map[page];
				wordAddress &= 0x001ff;
				wordAddress |= mapped;
			}
			byte wl = writeLocks[wordAddress >>> 9];
			if (wl != 0 && writeKey != 0 && wl != writeKey) {
				naoWL.fillInStackTrace();
				throw naoWL;
			}
		}
		mem[wordAddress] = value;
	}

	public void loadMemoryMap(int addr, int count, int page) {
		int ba = addr << 2;
		int n = count << 2;
		for (int i=0; i<n; i+=1) {
			int value = readByte(ba++);
			value &= 0xff;
			value <<= 9;
			map[page++ & 0xff] = value;
		}
	}

	public void loadAccessProtection(int addr, int count, int page) {
		int ba = addr << 2;
		int n = count << 2;
		for (int i=0; i<n; i+=1) {
			byte bits = readByte(ba++);
			setAccess(page++ & 0xff, (bits >> 6) & 0x3);
			setAccess(page++ & 0xff, (bits >> 4) & 0x3);
			setAccess(page++ & 0xff, (bits >> 2) & 0x3);
			setAccess(page++ & 0xff, (bits     ) & 0x3);
		}
	}

	// 00 - r, w, x
	// 01 - r, x
	// 10 - r
	// 11 - (no access)
	protected void setAccess(int page, int ac) {
		readAccess[page] = ac != 3;
		execAccess[page] = ac == 0 || ac == 1;
		writeAccess[page] = ac == 0;
	}

	public void loadWriteLocks(int addr, int count, int page) {
		// System.out.println("Loading write locks, page = " +
		//	Integer.toHexString(page));
		int ba = addr << 2;
		int n = count << 2;
		for (int i=0; i<n; i+=1) {
			byte bits = readByte(ba++);
			writeLocks[page++ & 0xff] = (byte) ((bits >> 6) & 0x3);
			writeLocks[page++ & 0xff] = (byte) ((bits >> 4) & 0x3);
			writeLocks[page++ & 0xff] = (byte) ((bits >> 2) & 0x3);
			writeLocks[page++ & 0xff] = (byte) ((bits     ) & 0x3);
		}
	}

	public void dumpMap() {
		int n = map.length;
		System.out.println("Memory map:");
		for (int i=0; i<n; i+=1) {
			if (i % 8 == 0) {
				System.out.println();
			}
			System.out.print(Util.toHexString(map[i], 8));
		}
	}

	public void testRWByte() {
		int ba = 0x20 << 2;
		for (int i=0; i<40; i+=1) {
			writeByte(ba + i, i | 0x80);
		}
		for (int i=0; i<40; i+=1) {
			System.out.print("BA(.");
			System.out.print(Integer.toHexString(ba + i));
			System.out.print(") = .");
			int b = readByte(ba + i);
			System.out.println(Integer.toHexString(b));
		}
	}

	public void testRWHalfWord() {
		int ha = 0x20 << 1;
		System.out.println();
		for (int i=0; i<20; i+=1) {
			writeHalfWord(ha + i, i| 0x8000);
		}
		for (int i=0; i<20; i+=1) {
			System.out.print("HA(.");
			System.out.print(Integer.toHexString(ha + i));
			System.out.print(") = .");
			int hw = readHalfWord(ha + i);
			System.out.println(Integer.toHexString(hw));
		}
	}

	public void timeMemory() {
		int n = 100000000;
		long start = System.currentTimeMillis();
		for (int i=0; i<n; i+=1) {
			// int b = readByte(i & 0xffff);
			int h = readHalfWord(i & 0xffff);
			// int w = readWord(i & 0xffff);
		}
		long end = System.currentTimeMillis();
		double time = (end-start)/1000.0;
		System.out.println("Time is " + time/n + " seconds per operation");
	}
}
