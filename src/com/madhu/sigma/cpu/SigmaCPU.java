
package com.madhu.sigma.cpu;

import java.util.Observer;

import com.madhu.sigma.*;
import com.madhu.sigma.iop.*;

/**
 * Abstract base class for Sigma processors
 * Concrete subclasses can implement Sigma 6, 7, 9 etc.
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public abstract class SigmaCPU implements Runnable {
	// This numbering is CRITICAL! Do not monkey with it!!
	public static final int NONEXISTENT_INSTRUCTION = 8;
	public static final int NONEXISTENT_MEMORY = 4;
	public static final int PRIVELEGED_INSTRUCTION = 2;
	public static final int MEMORY_PROTECTION = 1;

	protected int[][] regs;		//  32 register blocks of 16 words each
	protected int cc;			//  condition code
	protected boolean fs;		//  float significance mode control
	protected boolean fz;		//  float zero mode control
	protected boolean fn;		//  float normalize mode control
	protected boolean ms;		//  master/slave (slave = true)
	protected boolean mm;		//  memory map control
	protected boolean dm;		//  decimal mask
	protected boolean am;		//  arithmetic mask
	protected int ia;			//  instruction address
	protected int wk;			//  write key
	protected boolean ci;		//  counter interrupt group inhibit
	protected boolean ii;		//  input/output interrupt group inhibit
	protected boolean ei;		//  external interrupt group inhibit
	protected boolean ma;		//  mode altered *** BIG 6 ***
	protected int rp;			//  register pointer

	protected int[] currentRegisters;
	protected boolean interruptArmed[];
	protected boolean interruptWaiting[];
	protected boolean interruptEnabled[];
	protected boolean interruptActive[];
	protected boolean interrupted;

	protected MainMemory memory;
	protected ProcessorControlPanel pcp;
	protected IOPManager iopMgr;

	protected Thread runningThread;
	protected int breakAddr;
	protected int breakCount;
	protected int executionCount;
	protected boolean running;
	protected Exception execException;
	protected boolean started;
	protected NonAllowedOperation naoExc;
	protected TrapException trapExc;

	protected IATracer iaTracer;
	protected CPUNotifier cpuNotifier;

	protected Instruction[] instructions;

	public SigmaCPU() {
		cpuNotifier = new CPUNotifier();
		iaTracer = new IATracer(32);
		breakAddr = -1;
		regs = new int[32][16];
		interruptArmed = new boolean[320];
		interruptWaiting = new boolean[320];
		interruptEnabled = new boolean[320];
		interruptActive = new boolean[320];
		executionCount = 0;
		execException = null;
		breakCount = 1;
		running = false;
		runningThread = null;
		naoExc = new NonAllowedOperation();
		trapExc = new TrapException();
		instructions = new Instruction[128];

		instructions[0x00] = new NonExistentInstruction(0x00, false);
		instructions[0x01] = new NonExistentInstruction(0x01, false);
		instructions[0x02] = new LCFI();
		instructions[0x03] = new NonExistentInstruction(0x03, false);
		instructions[0x04] = new CAL1();
		instructions[0x05] = new CAL2();
		instructions[0x06] = new CAL3();
		instructions[0x07] = new CAL4();
		instructions[0x08] = new PLW();
		instructions[0x09] = new PSW();
		instructions[0x0A] = new PLM();
		instructions[0x0B] = new PSM();
		instructions[0x0C] = new NonExistentInstruction(0x0C, true);
		instructions[0x0D] = new NonExistentInstruction(0x0D, true);
		instructions[0x0E] = new LPSD();
		instructions[0x0F] = new XPSD();
		instructions[0x10] = new AD();
		instructions[0x11] = new CD();
		instructions[0x12] = new LD();
		instructions[0x13] = new MSP();
		instructions[0x14] = new NonExistentInstruction(0x14, false);
		instructions[0x15] = new STD();
		instructions[0x16] = new NonExistentInstruction(0x16, false);
		instructions[0x17] = new NonExistentInstruction(0x17, false);
		instructions[0x18] = new SD();
		instructions[0x19] = new CLM();
		instructions[0x1A] = new LCD();
		instructions[0x1B] = new LAD();
		instructions[0x1C] = new UnimplementedInstruction("FSL", 0x1C);
		instructions[0x1D] = new UnimplementedInstruction("FAL", 0x1D);
		instructions[0x1E] = new UnimplementedInstruction("FDL", 0x1E);
		instructions[0x1F] = new UnimplementedInstruction("FML", 0x1F);
		instructions[0x20] = new AI();
		instructions[0x21] = new CI();
		instructions[0x22] = new LI();
		instructions[0x23] = new MI();
		instructions[0x24] = new SF();
		instructions[0x25] = new S();
		instructions[0x26] = new LAS();
		instructions[0x27] = new NonExistentInstruction(0x27, false);
		instructions[0x28] = new CVS();
		instructions[0x29] = new CVA();
		instructions[0x2A] = new LM();
		instructions[0x2B] = new STM();
		instructions[0x2C] = new NonExistentInstruction(0x2C, true);
		instructions[0x2D] = new LMS();
		instructions[0x2E] = new WAIT();
		instructions[0x2F] = new LRP();
		instructions[0x30] = new AW();
		instructions[0x31] = new CW();
		instructions[0x32] = new LW();
		instructions[0x33] = new MTW();
		instructions[0x34] = new NonExistentInstruction(0x34, false);
		instructions[0x35] = new STW();
		instructions[0x36] = new DW();
		instructions[0x37] = new MW();
		instructions[0x38] = new SW();
		instructions[0x39] = new CLR();
		instructions[0x3A] = new LCW();
		instructions[0x3B] = new LAW();
		instructions[0x3C] = new UnimplementedInstruction("FSS", 0x3C);
		instructions[0x3D] = new UnimplementedInstruction("FAS", 0x3D);
		instructions[0x3E] = new UnimplementedInstruction("FDS", 0x3E);
		instructions[0x3F] = new UnimplementedInstruction("FMS", 0x3F);
		instructions[0x40] = new TTBS();
		instructions[0x41] = new TBS();
		instructions[0x42] = new NonExistentInstruction(0x42, false);
		instructions[0x43] = new NonExistentInstruction(0x43, false);
		instructions[0x44] = new ANLZ();
		instructions[0x45] = new CS();
		instructions[0x46] = new XW();
		instructions[0x47] = new STS();
		instructions[0x48] = new EOR();
		instructions[0x49] = new OR();
		instructions[0x4A] = new LS();
		instructions[0x4B] = new AND();
		instructions[0x4C] = new SIO();
		instructions[0x4D] = new TIO();
		instructions[0x4E] = new TDV();
		instructions[0x4F] = new HIO();
		instructions[0x50] = new AH();
		instructions[0x51] = new CH();
		instructions[0x52] = new LH();
		instructions[0x53] = new MTH();
		instructions[0x54] = new NonExistentInstruction(0x54, false);
		instructions[0x55] = new STH();
		instructions[0x56] = new DH();
		instructions[0x57] = new MH();
		instructions[0x58] = new SH();
		instructions[0x59] = new NonExistentInstruction(0x59, false);
		instructions[0x5A] = new LCH();
		instructions[0x5B] = new LAH();
		instructions[0x5C] = new NonExistentInstruction(0x5C, false);
		instructions[0x5D] = new NonExistentInstruction(0x5D, false);
		instructions[0x5E] = new NonExistentInstruction(0x5E, false);
		instructions[0x5F] = new NonExistentInstruction(0x5F, false);
		instructions[0x60] = new CBS();
		instructions[0x61] = new MBS();
		instructions[0x62] = new NonExistentInstruction(0x62, false);
		instructions[0x63] = new EBS();
		instructions[0x64] = new BDR();
		instructions[0x65] = new BIR();
		instructions[0x66] = new AWM();
		instructions[0x67] = new EXU();
		instructions[0x68] = new BCR();
		instructions[0x69] = new BCS();
		instructions[0x6A] = new BAL();
		instructions[0x6B] = new INT();
		instructions[0x6C] = new RD();
		instructions[0x6D] = new WD();
		instructions[0x6E] = new AIO();
		instructions[0x6F] = new MMC();
		instructions[0x70] = new LCF();
		instructions[0x71] = new CB();
		instructions[0x72] = new LB();
		instructions[0x73] = new MTB();
		instructions[0x74] = new STFC();
		instructions[0x75] = new STB();
		instructions[0x76] = new UnimplementedInstruction("PACK", 0x76);
		instructions[0x77] = new UnimplementedInstruction("UNPK", 0x77);
		instructions[0x78] = new UnimplementedInstruction("DS", 0x78);
		instructions[0x79] = new UnimplementedInstruction("DA", 0x79);
		instructions[0x7A] = new UnimplementedInstruction("DD", 0x7A);
		instructions[0x7B] = new UnimplementedInstruction("DM", 0x7B);
		instructions[0x7C] = new UnimplementedInstruction("DSA", 0x7C);
		instructions[0x7D] = new UnimplementedInstruction("DC", 0x7D);
		instructions[0x7E] = new DL();
		instructions[0x7F] = new DST();
	}

	public void addStopObserver(Observer o) {
		cpuNotifier.addObserver(o);
	}

	public void setMemory(MainMemory memory) {
		this.memory = memory;
	}

	public void setPCP(ProcessorControlPanel pcp) {
		this.pcp = pcp;
	}

	public void setIOPManager(IOPManager iopMgr) {
		this.iopMgr = iopMgr;
	}

	public IATracer getIATracer() {
		return iaTracer;
	}

	public void setRP(int rp) {
		rp = rp & 0x1f;
		this.rp = rp;
		currentRegisters = regs[rp];
		memory.setRegisters(regs[rp]);
	}

	public void setCC(int cc) {
		this.cc = cc;
	}
	public int getCC() {
		return cc;
	}

	public boolean isMS() { return ms; }
	public boolean isMM() { return mm; }
	public boolean isDM() { return dm; }
	public boolean isAM() { return am; }
	public void setMS(boolean flag) {
		ms = flag;
		memory.setSlaveMode(flag);
	}
	public void setMM(boolean flag) {
		mm = flag;
		memory.setMapEnabled(flag);
	}
	public void setDM(boolean flag) { dm = flag; }
	public void setAM(boolean flag) { am = flag; }

	public void setIA(int ia) {
		int from = this.ia - 1;
		int iWord = memory.fetchInstruction(from);
		this.ia = ia & 0x1ffff;
		int to = this.ia;
		iaTracer.addTrace(from, iWord, to);
	}
	public int getIA() {
		return ia;
	}

	public void setWK(int wk) {
		this.wk = wk;
		memory.setWriteKey(wk);
	}
	public int getWK() {
		return wk;
	}

	public boolean isCI() { return ci; }
	public boolean isII() { return ii; }
	public boolean isEI() { return ei; }
	public void setCI(boolean flag) { ci = flag; }
	public void setII(boolean flag) { ii = flag; }
	public void setEI(boolean flag) { ei = flag; }

	public void reset() {
		iaTracer.reset();
		setRP(0);
		setIA(0x26);
		setCC(0);
		for (int i=0; i<regs.length; i+=1) {
			for (int j=0; j<regs[i].length; j+=1) {
				regs[i][j] = 0;
			}
		}
		fs = false;
		fz = false;
		fn = false;
		setMS(false);
		setMM(false);
		dm = false;
		am = false;
		setWK(0);
		ci = true;	// 1 == inhibit
		ii = true;
		ei = true;
		ma = false;
		for (int i=0; i<interruptArmed.length; i+=1) {
			interruptArmed[i] = false;
		}
		for (int i=0; i<interruptWaiting.length; i+=1) {
			interruptWaiting[i] = false;
		}
		for (int i=0; i<interruptEnabled.length; i+=1) {
			interruptEnabled[i] = false;
		}
		for (int i=0; i<interruptActive.length; i+=1) {
			interruptActive[i] = false;
		}
		interrupted = false;
	}

	public void trap40(int function) {
		memory.setMapEnabled(false);
		int iWord = memory.fetchInstruction(0x40);
		memory.setMapEnabled(mm);
		int code = (iWord >>> 24) & 0x7f;
		ia -= 1;
		try {
			XPSD xpsd = (XPSD) instructions[code];
			xpsd.setInTrap(true);
			xpsd.execute(iWord);
			xpsd.setInTrap(false);
			boolean lp = (iWord & 0x00800000) != 0;
			boolean ai = (iWord & 0x00400000) != 0;
			boolean mp = (iWord & 0x00200000) != 0;
			cc |= function;
			if (ai) {
				ia += function;
			}
		} catch (ClassCastException e) {
			throw new IllegalArgumentException(
				"Invalid trap instruction: " +
				Disassembler.decode(iWord) + " at .40");
		}
	}

	public void trap(int location) {
		memory.setMapEnabled(false);
		int iWord = memory.fetchInstruction(location);
		memory.setMapEnabled(mm);
		int code = (iWord >>> 24) & 0x7f;
		ia -= 1;
		try {
			XPSD xpsd = (XPSD) instructions[code];
			xpsd.setInTrap(true);
			xpsd.execute(iWord);
			xpsd.setInTrap(false);
		} catch (ClassCastException e) {
			throw new IllegalArgumentException(
				"Invalid trap instruction: " +
				Disassembler.decode(iWord) + " at ." +
				Integer.toHexString(location).toUpperCase());
		}
	}

	public synchronized void start() {
		executionCount = -1;
		execException = null;
		running = true;
		if (runningThread == null) {
			runningThread = new Thread(this);
			runningThread.setPriority(Thread.MIN_PRIORITY);
			runningThread.start();
		}
		notify();
	}

	public synchronized void step() {
		executionCount = 1;
		execException = null;
		running = true;
		if (runningThread == null) {
			runningThread = new Thread(this);
			runningThread.setPriority(Thread.MIN_PRIORITY);
			runningThread.start();
		}
		notify();
	}

	public synchronized void stop() {
		running = false;
		cpuNotifier.notifyObservers();
	}

	public boolean isRunning() {
		return running;
	}

	protected synchronized void checkWait() {
		if (!running) {
			try {
				wait();
			} catch (InterruptedException e) {
			}
		}
	}

	public Exception getException() {
		return execException;
	}

	public void setBreakPoint(int breakAddr) {
		this.breakAddr = breakAddr;
	}

	public void setBreakCount(int breakCount) {
		this.breakCount = breakCount;
	}

	public void run() {
		while (true) {
			try {
				checkWait();
				started = true;
				int yieldCount = 0;
				long start = System.currentTimeMillis();
				while (running) {
					if (!started && (breakAddr >= 0 && ia == breakAddr &&
						--breakCount <= 0) ||
						(executionCount == 0)) {
						stop();
						break;
					}
					executeOne(memory.fetchInstruction(ia++));
					if (executionCount > 0) {
						executionCount -= 1;
					}
					if (interrupted) {
						processInterrupt();
					}
					started = false;
					yieldCount += 1;
					if (yieldCount >= 100) {
						yieldCount = 0;
						long dt = System.currentTimeMillis() - start;
						if (dt >= 2) {
							start += 2;
							interrupt(0x54);
							interrupt(0x55);
							// Thread.yield();
						}
					}
				}
			} catch (NonAllowedOperation e) {
				trap40(e.getReason());
			} catch (TrapException e) {
				trap(e.getLocation());
			} catch (Exception e) {
				execException = e;
				stop();
				// System.out.println(iaTracer.toString());
			}
		}
	}

	public void runFast() {
		int yieldCount = 0;
		long start = System.currentTimeMillis();
		while (true) {
			try {
				if (interrupted) {
					processInterrupt();
				}
				int iWord = memory.fetchInstruction(ia++);
				int code = (iWord >>> 24) & 0x7f;
				instructions[code].execute(iWord);
				yieldCount += 1;
				if (yieldCount >= 100) {
					yieldCount = 0;
					long dt = System.currentTimeMillis() - start;
					if (dt >= 2) {
						start += 2;
						interrupt(0x54);
						interrupt(0x55);
						// Thread.yield();
					}
				}
			} catch (NonAllowedOperation e) {
				trap40(e.getReason());
			} catch (TrapException e) {
				trap(e.getLocation());
			} catch (Exception e) {
				System.out.println(e.getMessage());
				break;
			}
		}
	}

	public void interrupt(int loc) {
		if (interruptArmed[loc]) {
			interruptWaiting[loc] = true;
			interruptArmed[loc] = false;
			checkInterrupts();
		}
	}

	protected void clearInterrupt(int loc) {
		interruptActive[loc] = false;
		interruptArmed[loc] = true;
		checkInterrupts();
	}

	protected void checkInterrupts() {
		// Power on/off interrupts can't be disabled
		for (int i=0x50; i<=0x51; i+=1) {
			if (interruptActive[i]) {
				return;
			}
			if (interruptWaiting[i]) {
				interrupted = true;
				interruptWaiting[i] = false;
				interruptActive[i] = true;
				return;
			}
		}
		// Counters, memory parity don't have PSD inhibit
		for (int i=0x52; i<=0x57; i+=1) {
			if (interruptActive[i]) {
				return;
			}
			if (interruptEnabled[i] && interruptWaiting[i]) {
				interrupted = true;
				interruptWaiting[i] = false;
				interruptActive[i] = true;
				return;
			}
		}

		// Counters == 0
		for (int i=0x58; i<=0x5B; i+=1) {
			if (interruptActive[i]) {
				return;
			}
			if (!ci && interruptEnabled[i] && interruptWaiting[i]) {
				interrupted = true;
				interruptWaiting[i] = false;
				interruptActive[i] = true;
				return;
			}
		}
		// I/O, control panel
		for (int i=0x5C; i<=0x5D; i+=1) {
			if (interruptActive[i]) {
				return;
			}
			if (!ii && interruptEnabled[i] && interruptWaiting[i]) {
				interrupted = true;
				interruptWaiting[i] = false;
				interruptActive[i] = true;
				return;
			}
		}

		// 0x5E, 0x5F are reserved

		// External interrupts
		for (int i=0x60; i<=0x13F; i+=1) {
			if (interruptActive[i]) {
				return;
			}
			if (!ei && interruptEnabled[i] && interruptWaiting[i]) {
				interrupted = true;
				interruptWaiting[i] = false;
				interruptActive[i] = true;
				return;
			}
		}
	}

	protected int getActiveInterrupt() {
		// Power on/off interrupts can't be disabled
		for (int i=0x50; i<=0x51; i+=1) {
			if (interruptActive[i]) {
				return i;
			}
		}
		// Counters, memory parity don't have PSD inhibit
		for (int i=0x52; i<=0x57; i+=1) {
			if (interruptActive[i]) {
				return i;
			}
		}

		// Counters == 0
		for (int i=0x58; i<=0x5B; i+=1) {
			if (interruptActive[i]) {
				return i;
			}
		}
		// I/O, control panel
		for (int i=0x5C; i<=0x5D; i+=1) {
			if (interruptActive[i]) {
				return i;
			}
		}

		// 0x5E, 0x5F are reserved

		// External interrupts
		for (int i=0x60; i<=0x13F; i+=1) {
			if (interruptActive[i]) {
				return i;
			}
		}
		return -1;
	}

	protected void processInterrupt() {
		interrupted = false;
		int loc = getActiveInterrupt();
		if (loc < 0) {	// be safe
			return;
		}
		int iWord;
		memory.setMapEnabled(false);
		iWord = memory.fetchInstruction(loc);
		memory.setMapEnabled(mm);
		int code = (iWord >>> 24) & 0x7f;
		Instruction inst = (Instruction) instructions[code];
		try {
			InterruptInstruction sii = (InterruptInstruction) inst;
			sii.setLocation(loc);
			sii.setInTrap(true);
			memory.setWriteKey(0);
			if (loc == 0x55) {	// Sig6 ref, page 18, pp 2b.
				inst.execute(iWord);
			} else {
				memory.setMapEnabled(false);
				inst.execute(iWord);
				memory.setMapEnabled(mm);
			}
			memory.setWriteKey(wk);
			sii.setInTrap(false);
			sii.setLocation(0);
		} catch (ClassCastException e) {
			throw new IllegalArgumentException("Invalid int. loc. instruction at ." +
				Integer.toHexString(loc).toUpperCase() + ": " +
				Disassembler.decode(iWord));
		}
	}

	protected void executeOne(int iWord) {
		if (!started && iWord == breakAddr && --breakCount <= 0) {
			ia -= 1;
			stop();
			return;
		}
		int code = (iWord >>> 24) & 0x7f;
		instructions[code].execute(iWord);
	}

	public void printCC() {
		System.out.print("CC = ");
		int mask = 0x08;
		for (int i=0; i<4; i+=1) {
			if ((cc & mask) != 0) {
				System.out.print("1 ");
			} else {
				System.out.print("0 ");
			}
			mask >>>= 1;
		}
		System.out.println();
	}

	public void printRegisters() {
		for (int i=0; i<16; i++) {
			System.out.print("R");
			System.out.print(Integer.toString(i));
			System.out.print(" = .");
			System.out.println(Integer.toHexString(regs[rp][i]).toUpperCase());
		}
	}

	public void timeInstruction(int addr) {
		for (int i=0; i<128; i+=1) {
			Object o = instructions[i];
			if (o instanceof UnimplementedInstruction ||
				o instanceof PrivelegedWordIndexedInstruction ||
				o instanceof PrivelegedDoubleWordIndexedInstruction ||
				o instanceof NonExistentInstruction ||
				o instanceof CVS ||
				o instanceof CVA ||
				o instanceof MBS ||
				o instanceof TBS ||
				o instanceof TTBS ||
				o instanceof EBS ||
				o instanceof CBS) {
				continue;
			}
			int iWord = i << 24;
			iWord |= 0x00280040;
			if (!(o instanceof ImmediateInstruction)) {
				iWord |= 0x80000000;
			}
			memory.writeWord(addr, iWord);
			try {
				Instruction inst = (Instruction) o;
				System.out.print(inst.getName() + "\t");
				timeOne(addr);
			} catch (Exception e) {
				System.out.println(e.getMessage());
			}
		}
	}

	protected void timeOne(int addr) {
		int n = 5000000;
		long start = System.currentTimeMillis();
		int iWord = memory.fetchInstruction(addr);
		for (int i=0; i<n; i+=1) {
			iWord = memory.fetchInstruction(addr);
			int code = (iWord >>> 24) & 0x7f;
			instructions[code].execute(iWord);
		}
		long end = System.currentTimeMillis();
		double time = (end-start)/1000.0;
		time = 1e6 * time/n;
		System.out.println(1/time + "\tMIPs");
	}

/***********************************
 *
 * Begin instructions
 *
 ***********************************/

	// ?? operation .00
	// ?? operation .01

	// LCFI operation .02
	protected class LCFI extends ImmediateInstruction {
		public LCFI() { super("LCFI", 0x02); }
		protected void execute(int regR, int value) {
			if ((regR & 0x2) != 0) {
				cc = (value >>> 4) & 0x0f;
			}
			if ((regR & 0x1) != 0) {
				fs = (value & 0x4) != 0;
				fz = (value & 0x2) != 0;
				fn = (value & 0x1) != 0;
			}
		}
	}

	// ?? operation .03

	// CAL1 operation .04
	protected class CAL1 extends WordIndexedInstruction {
		protected CAL1() { super("CAL1", 0x04); }
		protected void execute(int regR, int addr) {
			memory.setMapEnabled(false);
			int iWord = memory.fetchInstruction(0x48);
			memory.setMapEnabled(mm);
			int code = (iWord >>> 24) & 0x7f;
			if (code != 0x0F) {
				throw new IllegalArgumentException(
					"Invalid trap instruction: " +
					Disassembler.decode(iWord) + " at .48");
			}
			ia -= 1;
			XPSD xpsd = (XPSD) instructions[code];
			xpsd.setInTrap(true);
			xpsd.execute(iWord);
			xpsd.setInTrap(false);
			cc |= regR;
			boolean ai = (iWord & 0x00400000) != 0;
			if (ai) {
				ia += regR;
			}
		}
	}

	// CAL2 operation .05
	protected class CAL2 extends WordIndexedInstruction {
		protected CAL2() { super("CAL2", 0x05); }
		protected void execute(int regR, int addr) {
			memory.setMapEnabled(false);
			int iWord = memory.fetchInstruction(0x49);
			memory.setMapEnabled(mm);
			int code = (iWord >>> 24) & 0x7f;
			if (code != 0x0F) {
				throw new IllegalArgumentException(
					"Invalid trap instruction: " +
					Disassembler.decode(iWord) + " at .48");
			}
			ia -= 1;
			XPSD xpsd = (XPSD) instructions[code];
			xpsd.setInTrap(true);
			xpsd.execute(iWord);
			xpsd.setInTrap(false);
			cc |= regR;
			boolean ai = (iWord & 0x00400000) != 0;
			if (ai) {
				ia += regR;
			}
		}
	}

	// CAL3 operation .06
	protected class CAL3 extends WordIndexedInstruction {
		protected CAL3() { super("CAL3", 0x06); }
		protected void execute(int regR, int addr) {
			memory.setMapEnabled(false);
			int iWord = memory.fetchInstruction(0x4A);
			memory.setMapEnabled(mm);
			int code = (iWord >>> 24) & 0x7f;
			if (code != 0x0F) {
				throw new IllegalArgumentException(
					"Invalid trap instruction: " +
					Disassembler.decode(iWord) + " at .48");
			}
			ia -= 1;
			XPSD xpsd = (XPSD) instructions[code];
			xpsd.setInTrap(true);
			xpsd.execute(iWord);
			xpsd.setInTrap(false);
			cc |= regR;
			boolean ai = (iWord & 0x00400000) != 0;
			if (ai) {
				ia += regR;
			}
		}
	}

	// CAL4 operation .07
	protected class CAL4 extends WordIndexedInstruction {
		protected CAL4() { super("CAL4", 0x07); }
		protected void execute(int regR, int addr) {
			memory.setMapEnabled(false);
			int iWord = memory.fetchInstruction(0x4B);
			memory.setMapEnabled(mm);
			int code = (iWord >>> 24) & 0x7f;
			if (code != 0x0F) {
				throw new IllegalArgumentException(
					"Invalid trap instruction: " +
					Disassembler.decode(iWord) + " at .48");
			}
			ia -= 1;
			XPSD xpsd = (XPSD) instructions[code];
			xpsd.setInTrap(true);
			xpsd.execute(iWord);
			xpsd.setInTrap(false);
			cc |= regR;
			boolean ai = (iWord & 0x00400000) != 0;
			if (ai) {
				ia += regR;
			}
		}
	}

	// PLW operation .08
	protected class PLW extends DoubleWordIndexedInstruction {
		protected PLW() { super("PLW", 0x08); }
		protected void execute(int regR, int addr) {         //PLW is 08 added 11/23/02 KGC
			int value0 = memory.readWord(addr) & 0x1ffff;
			int value1 = memory.readWord(addr+1);
			boolean TS = value1 < 0;
			boolean TW = ((value1 >> 15) & 0x1) == 1;
			int spacecnt = (value1 >> 16) & 0x7fff;
			int wordcnt = value1 & 0x7fff;
			spacecnt++;
			wordcnt --;
			int localcc = 0;
			if ((wordcnt  < 0) | (wordcnt  > 0x7fff)) {
				if (TW) {
					localcc |= 0x2;
				} else {
					trap(0x42);
					return;
				}
			}
			if ((spacecnt < 0) | (spacecnt > 0x7fff)) {
				if (TS) {
					localcc |= 0x8;
				} else {
					trap(0x42);
					return;
				}
			}
			if ((localcc & 0xa) != 0) {
				wordcnt = value1 & 0x7fff;
				spacecnt = (value1 >> 16) & 0x7fff;
			}
			cc = 0;
			if (wordcnt == 0) {
				cc |= 0x1;
			}
			if (localcc > 0 & wordcnt == 0 & TW) { cc |= 0x2; }
			if (localcc > 0 & spacecnt == 0 & TW) { cc |= 0x4; }
			if (localcc > 0 & spacecnt == 0x7fff & TS) { cc |=0x8; }
			if ((localcc & 0xa) != 0) {
				return;
			}
			value1 = (value1 & 0x80008000) | ((spacecnt << 16) | wordcnt);
			currentRegisters[regR] = memory.readWord(value0--);
			memory.writeWord(addr, value0);
			memory.writeWord(addr+1, value1);
		}
	}

	// PSW operation .09
	protected class PSW extends DoubleWordIndexedInstruction {
		protected PSW() { super("PSW", 0x09); }
		protected void execute(int regR, int addr) {         //PSW is 09 added 11/23/02 KGC
			int value =  currentRegisters[regR];
			int value0 = memory.readWord(addr) & 0x1ffff;
			int value1 = memory.readWord(addr+1);
			boolean TS = value1 < 0;
			boolean TW = ((value1 >> 15) & 0x1) == 1;
			int spacecnt = (value1 >> 16) & 0x7fff;
			int wordcnt = value1 & 0x7fff;
			value0 ++; spacecnt --; wordcnt ++;
			int localcc = 0;
			if ((wordcnt  < 0) | (wordcnt  > 0x7fff)) {
				 if (TW) {localcc |= 0x2;} else {trap(0x42); return;}}
			if ((spacecnt < 0) | (spacecnt > 0x7fff)) {
				 if (TS) {localcc |= 0x8;} else {trap(0x42); return;}}
			if ((localcc & 0xa) != 0) {wordcnt = value1 & 0x7fff;
									   spacecnt = (value1 >> 16) & 0x7fff;}
			cc = localcc; if (wordcnt == 0) {cc |= 0x1;}
						  if (wordcnt == 0x7fff & TW) {cc |= 0x2;}
						  if (spacecnt == 0) {cc |= 0x4;}
			if ((localcc & 0xa) != 0) return;
			value1 = (value1 & 0x80008000) | ((spacecnt << 16) | wordcnt);
			memory.writeWord(addr, value0);
			memory.writeWord(addr+1, value1);
			memory.writeWord(value0, value);
		}
	}

	// PLM operation .0A
	protected class PLM extends DoubleWordIndexedInstruction {
		protected PLM() { super("PLM", 0x0A); }
		protected void execute(int regR, int addr) {       //PLM is 0A added 11/24/02 KGC
			int value0 = memory.readWord(addr) & 0x1ffff;
			int value1 = memory.readWord(addr+1);
			boolean TS = value1 < 0;
			boolean TW = ((value1 >> 15) & 0x1) == 1;
			int spacecnt = (value1 >> 16) & 0x7fff;
			int wordcnt = value1 & 0x7fff;
			int count=cc; if (count == 0) count = 16;
			spacecnt += count; wordcnt -= count; int localcc = 0;
			if ((wordcnt  < 0) | (wordcnt  > 0x7fff)) {
				 if (TW) {localcc |= 0x2;} else {trap(0x42); return;}}
			if ((spacecnt < 0) | (spacecnt > 0x7fff)) {
				 if (TS) {localcc |= 0x8;} else {trap(0x42); return;}}
			if ((localcc & 0xa) != 0) {wordcnt = value1 & 0x7fff;
									   spacecnt = (value1 >> 16) & 0x7fff;}
			if ((localcc & 0xa) == 0) {
				for (int i=0; i<count; i++) {
					currentRegisters[(regR+count-1-i) & 0xf] = memory.readWord(value0--);
				}
				value1 = (value1 & 0x80008000) | ((spacecnt << 16) | wordcnt);
				memory.writeWord(addr, value0);
				memory.writeWord(addr+1, value1);
			}
			cc = 0;
			if (wordcnt == 0) { cc |= 0x1; }
			if (localcc > 0 & wordcnt < count) { cc |= 0x2; }
			if (localcc > 0 & spacecnt == 0) { cc |= 0x4; }
			if (localcc > 0 & spacecnt + count > 0x7fff) { cc |=0x8; }
		}
	}

	// PSM operation .0B
	protected class PSM extends DoubleWordIndexedInstruction {
		protected PSM() { super("PSM", 0x0B); }
		protected void execute(int regR, int addr) {       // PSM is 0B added 11/24/02 KGC
			int value0 = memory.readWord(addr) & 0x1ffff;
			int value1 = memory.readWord(addr+1);
			boolean TS = value1 < 0;
			boolean TW = ((value1 >> 15) & 0x1) == 1;
			int spacecnt = (value1 >> 16) & 0x7fff;
			int wordcnt = value1 & 0x7fff;
			int count=cc; if (count == 0) count = 16;
			spacecnt -= count; wordcnt += count; int localcc = 0;
			if ((wordcnt  < 0) | (wordcnt  > 0x7fff)) {
				 if (TW) {localcc |= 0x2;} else {trap(0x42); return;}}
			if ((spacecnt < 0) | (spacecnt > 0x7fff)) {
				 if (TS) {localcc |= 0x8;} else {trap(0x42); return;}}
			if ((localcc & 0xa) != 0) {wordcnt = value1 & 0x7fff;
									   spacecnt = (value1 >> 16) & 0x7fff;}
			if ((localcc & 0xa) == 0) {
				for (int i=0; i<=count; i++) {
					memory.writeWord(value0++, currentRegisters[(regR+i-1) & 0xf]);
				}
				value0--; // ???  seems i<=count should be i<count ???
				value1 = (value1 & 0x80008000) | ((spacecnt << 16) | wordcnt);
				memory.writeWord(addr, value0);
				memory.writeWord(addr+1, value1);
			}
			cc = 0; if (localcc > 0 & wordcnt == 0) {cc |= 0x1;}
					if (localcc > 0 & wordcnt + count > 0x7fff) {cc |= 0x2;}
					if (spacecnt == 0) {cc |= 0x4;}
					if (localcc > 0 & spacecnt < count) {cc |=0x8;}
		}
	}

	// ?? operation .0C
	// ?? operation .0D

	// LPSD operation .0E
	protected class LPSD extends PrivelegedDoubleWordIndexedInstruction {
		protected LPSD() { super("LPSD", 0x0E); }
		protected void execute(int regR, int addr) {
			int value0 = memory.readWord(addr);
			int value1 = memory.readWord(addr+1);

			cc = value0 >>> 28;
			setIA(value0 & 0x1ffff);

			fs = (value0 & 0x04000000) != 0;
			fz = (value0 & 0x02000000) != 0;
			fn = (value0 & 0x01000000) != 0;

			setMS((value0 & 0x00800000) != 0);
			setMM((value0 & 0x00400000) != 0);
			dm = (value0 & 0x00200000) != 0;
			am = (value0 & 0x00100000) != 0;

			setWK((value1 >>> 28) & 0x3);
			ci = (value1 & 0x04000000) != 0;
			ii = (value1 & 0x02000000) != 0;
			ei = (value1 & 0x01000000) != 0;

			if ((regR & 0x8) != 0) {
				setRP(value1 >>> 4);
			}
			if ((regR & 0x2) != 0) {
				int loc = getActiveInterrupt();
				if (loc >= 0) {
					// clearInterrupt(loc);
					interruptActive[loc] = false;
					interruptArmed[loc] = (regR & 0x1) != 0;
				}
			}
			if (!ci || !ii || !ei) {
				checkInterrupts();
			}
		}
	}

	// XPSD operation .0F
	protected class XPSD extends PrivelegedDoubleWordIndexedInstruction
		implements InterruptInstruction {

		protected boolean inTrap;

		protected XPSD() { super("XPSD", 0x0F); inTrap = false; }

		public void setLocation(int loc) { }	// Make the compiler happy
		public void setInTrap(boolean inTrap) {
			this.inTrap = inTrap;
			if (inTrap) {
				memory.setWriteKey(0);
			}
		}

		protected void execute(int iWord) {
			if (!inTrap && ms) {
				trap40(PRIVELEGED_INSTRUCTION);
				return;
			}
			if (inTrap) {
				memory.setWriteKey(0);
			}
			int regX = (iWord >>> 17) & 0x07;
			int addr = iWord & 0x1ffff;

			if (iWord < 0) {
				addr = memory.readWord(addr);
			}
			if (inTrap && (iWord & 0x00200000) == 0) {
				memory.setMapEnabled(false);
			}
			addr &= 0x1fffe;
			if (regX != 0) {
				addr += currentRegisters[regX] << 1;
			}
			int value0 = ia;
			value0 |= cc << 28;
			value0 |= fs ? 0x04000000 : 0;
			value0 |= fz ? 0x02000000 : 0;
			value0 |= fn ? 0x01000000 : 0;

			value0 |= ms ? 0x00800000 : 0;
			value0 |= mm ? 0x00400000 : 0;
			value0 |= dm ? 0x00200000 : 0;
			value0 |= am ? 0x00100000 : 0;

			int value1 = rp << 4;
			value1 |= wk << 28;

			value1 |= ci ? 0x04000000 : 0;
			value1 |= ii ? 0x02000000 : 0;
			value1 |= ei ? 0x01000000 : 0;

			memory.writeWord(addr, value0);
			memory.writeWord(addr+1, value1);

			addr += 2;

			value0 = memory.readWord(addr);
			value1 = memory.readWord(addr+1);

			cc = value0 >>> 28;
			setIA(value0 & 0x1ffff);
			fs = (value0 & 0x04000000) != 0;
			fz = (value0 & 0x02000000) != 0;
			fn = (value0 & 0x01000000) != 0;

			setMS((value0 & 0x00800000) != 0);
			setMM((value0 & 0x00400000) != 0);
			dm = (value0 & 0x00200000) != 0;
			am = (value0 & 0x00100000) != 0;

			setWK((value1 >>> 28) & 0x3);
			ci = ci || ((value1 & 0x04000000) != 0);
			ii = ii || ((value1 & 0x02000000) != 0);
			ei = ei || ((value1 & 0x01000000) != 0);

			if ((iWord & 0x00800000) != 0) {
				setRP(value1 >>> 4);
			}
			if (!ci || !ii || !ei) {
				checkInterrupts();
			}
		}

		protected void execute(int regR, int addr) {
		}
	}

	// AD operation .10
	protected class AD extends DoubleWordIndexedInstruction {
		protected AD() { super("AD", 0x10); }
		protected void execute(int regR, int addr) {
			int value0 = memory.readWord(addr);
			int value1 = memory.readWord(addr+1);
			long a = value0;
			a <<= 32;
			a |= value1 & 0xffffffffL;

			long b = currentRegisters[regR];
			b <<= 32;
			b |= currentRegisters[regR | 1] & 0xffffffffL;

			long result = a + b;
			currentRegisters[regR | 1] = (int) (result & 0xffffffffL);
			currentRegisters[regR] = (int) (result >>> 32);

			cc = 0;
			if (result < 0) {
				cc |= 0x1;
			} else if (result > 0) {
				cc |= 0x2;
			}
			long a0 = a & 0x8000000000000000L;
			long b0 = b & 0x8000000000000000L;
			long c0 = result & 0x8000000000000000L;
			if (((~(a0 ^ b0)) & (c0 ^ a0)) != 0) {
				cc |= 0x4;
			}
			if ((a0 != 0 || b0 != 0) && ((a0 != 0 && b0 != 0) ||
				((a & 0x7fffffffffffffffL) + (b & 0x7fffffffffffffffL) < 0))) {
				cc |= 0x8;
			}
			if (am && (cc & 0x4) != 0) {
				trap(0x43);
			}
		}
	}

	// CD operation .11
	protected class CD extends DoubleWordIndexedInstruction {
		protected CD() { super("CD", 0x11); }
		protected void execute(int regR, int addr) {
			long value = memory.readWord(addr);
			value <<= 32;
			value |= memory.readWord(addr+1) & 0xffffffffL;

			long r = currentRegisters[regR];
			r <<= 32;
			r |= currentRegisters[regR | 0x1] & 0xffffffffL;

			cc &= 0xc;
			if (r < value) {
				cc |= 0x1;
			} else if (r > value) {
				cc |= 0x2;
			}
		}
	}

	// LD operation .12
	protected class LD extends DoubleWordIndexedInstruction {
		protected LD() { super("LD", 0x12); }
		protected void execute(int regR, int addr) {
			int value0 = memory.readWord(addr);
			int value1 = memory.readWord(addr+1);
			cc &= 0xc;
			if (value0 < 0) {
				cc |= 0x1;
			} else if (value0 > 0 || value1 != 0) {
				cc |= 0x2;
			}
			currentRegisters[regR | 0x1] = value1;
			currentRegisters[regR] = value0;
		}
	}

	// MSP operation .13
	protected class MSP extends DoubleWordIndexedInstruction {
		protected MSP() { super("MSP", 0x13); }
		protected void execute(int regR, int addr) {               //MSP is 13 added 11/22/02 KGC
			int value =  currentRegisters[regR];
			value <<= 16; value >>= 16;             // sign extend modifier
			int value0 = memory.readWord(addr) & 0x1ffff;
			int value1 = memory.readWord(addr+1);
			boolean TS = value1 < 0;
			boolean TW = ((value1 >> 15) & 0x1) == 1;
			int spacecnt = (value1 >> 16) & 0x7fff;
			int wordcnt = value1 & 0x7fff;
			value0 += value; spacecnt -= value; wordcnt += value;
			value1 = (value1 & 0x80008000) | ((spacecnt << 16) | wordcnt);
			int localcc = 0;
			if ((wordcnt  < 0) | (wordcnt  > 0x7fff)) {
				 if (TW) {localcc |= 0x2;} else {trap(0x42); return;}}
			if ((spacecnt < 0) | (spacecnt > 0x7fff)) {
				 if (TS) {localcc |= 0x8;} else {trap(0x42); return;}}
			cc = localcc; if (wordcnt  == 0) {cc |= 0x1;}
						  if (spacecnt == 0) {cc |= 0x4;}
			if ((cc & 0xa) > 0) return;
			memory.writeWord(addr, value0);
			memory.writeWord(addr+1, value1);
		}
	}

	// ?? operation .14

	// STD operation .15
	protected class STD extends DoubleWordIndexedInstruction {
		protected STD() { super("STD", 0x15); }
		protected void execute(int regR, int addr) {
			memory.writeWord(addr+1, currentRegisters[regR | 0x1]);
			memory.writeWord(addr, currentRegisters[regR]);
		}
	}

	// ?? operation .16
	// ?? operation .17

	// SD operation .18
	protected class SD extends DoubleWordIndexedInstruction {
		protected SD() { super("SD", 0x18); }
		protected void execute(int regR, int addr) {
			int value0 = memory.readWord(addr);
			int value1 = memory.readWord(addr+1);
			long a = value0;
			a <<= 32;
			a |= value1 & 0xffffffffL;
			a = -a;

			long b = currentRegisters[regR];
			b <<= 32;
			b |= currentRegisters[regR | 1] & 0xffffffffL;

			long result = a + b;
			currentRegisters[regR | 1] = (int) (result & 0xffffffffL);
			currentRegisters[regR] = (int) (result >>> 32);

			cc = 0;
			if (result < 0) {
				cc |= 0x1;
			} else if (result > 0) {
				cc |= 0x2;
			}
			long a0 = a & 0x8000000000000000L;
			long b0 = b & 0x8000000000000000L;
			long c0 = result & 0x8000000000000000L;
			if ((a != -b) && ((~(a0 ^ b0)) & (c0 ^ a0)) != 0) {
				cc |= 0x4;
			}
			if ((a0 != 0 || b0 != 0) && ((a0 != 0 && b0 != 0) ||
				((a & 0x7fffffffffffffffL) + (b & 0x7fffffffffffffffL) < 0))) {
				cc |= 0x8;
			}
			if (am && (cc & 0x4) != 0) {
				trap(0x43);
			}
		}
	}

	// CLM operation .19
	protected class CLM extends DoubleWordIndexedInstruction {
		protected CLM() { super("CLM", 0x19); }
		protected void execute(int regR, int addr) {
			int value0 = memory.readWord(addr);
			int value1 = memory.readWord(addr + 1);
			int r = currentRegisters[regR];
			cc = 0;
			if (r < value0) {
				cc |= 0x1;
			} else if (r > value0) {
				cc |= 0x2;
			}
			if (r < value1) {
				cc |= 0x4;
			} else if (r > value1) {
				cc |= 0x8;
			}
		}
	}

	// LCD operation .1A
	protected class LCD extends DoubleWordIndexedInstruction {
		protected LCD() { super("LCD", 0x1A); }
		protected void execute(int regR, int addr) {
			int value0 = memory.readWord(addr);
			int value1 = memory.readWord(addr+1);
			long result = value0;
			result <<= 32;
			result |= value1 & 0xffffffffL;

			result = -result;
			value0 = (int) (result >>> 32);
			value1 = (int) result;
			currentRegisters[regR | 0x1] = value1;
			currentRegisters[regR] = value0;

			cc &= 0x8;
			if (result == 0x8000000000000000L) {
				cc |= 0x5;
				if (am) {
					trap(0x43);
				}
			} else if (result < 0) {
				cc |= 0x1;
			} else if (result > 0) {
				cc |= 0x2;
			}
		}
	}

	// LAD operation .1B
	protected class LAD extends DoubleWordIndexedInstruction {
		protected LAD() { super("LAD", 0x1B); }
		protected void execute(int regR, int addr) {
			int value0 = memory.readWord(addr);
			int value1 = memory.readWord(addr+1);
			long result = value0;
			result <<= 32;
			result |= value1 & 0xffffffffL;

			if (result < 0) {
				result = -result;
				value0 = (int) (result >>> 32);
				value1 = (int) result;
			}
			currentRegisters[regR | 0x1] = value1;
			currentRegisters[regR] = value0;

			cc &= 0x8;
			if (result == 0x8000000000000000L) {
				cc |= 0x5;
				if (am) {
					trap(0x43);
				}
			} else if (result != 0) {
				cc |= 0x2;
			}
		}
	}

	// FSL operation .1C
	// FAL operation .1D
	// FDL operation .1E
	// FML operation .1F

	// AI operation .20
	protected class AI extends ImmediateInstruction {
		protected AI() { super("AI", 0x20); }
		protected void execute(int regR, int a) {
			int b = currentRegisters[regR];
			int result = currentRegisters[regR] += a;

			cc = 0;
			if (result < 0) {
				cc |= 0x1;
			} else if (result > 0) {
				cc |= 0x2;
			}
			int a0 = a & 0x80000000;
			int b0 = b & 0x80000000;
			int c0 = result & 0x80000000;
			if (((~(a0 ^ b0)) & (c0 ^ a0)) != 0) {
				cc |= 0x4;
			}
			if ((a0 != 0 || b0 != 0) && ((a0 != 0 && b0 != 0) ||
				((a & 0x7fffffff) + (b & 0x7fffffff) < 0))) {
				cc |= 0x8;
			}
			if (am && (cc & 0x4) != 0) {
				trap(0x43);
			}
		}
	}

	// CI operation .21
	protected class CI extends ImmediateInstruction {
		protected CI() { super("CI", 0x21); }
		protected void execute(int regR, int value) {
			int r = currentRegisters[regR];
			cc &= 0x8;
			if (r < value) {
				cc |= 0x1;
			} else if (r > value) {
				cc |= 0x2;
			}
			if ((r & value) != 0) {
				cc |= 0x4;
			}
		}
	}

	// LI operation .22
	protected class LI extends ImmediateInstruction {
		protected LI() { super("LI", 0x22); }
		protected void execute(int regR, int value) {
			currentRegisters[regR] = value;
			cc &= 0x0c;
			if (value < 0) {
				cc |= 0x01;
			} else if (value > 0) {
				cc |= 0x02;
			}
		}
	}

	// MI operation .23
	protected class MI extends ImmediateInstruction {
		protected MI() { super("MI", 0x23); }
		protected void execute(int regR, int iVal) {
			long value = iVal;
			value *= currentRegisters[regR | 1];
			int hi = currentRegisters[regR] = (int) (value >>> 32);
			int lo = currentRegisters[regR | 1] = (int) value;
			cc &= 0x8;
			if (value < 0) {
				cc |= 0x1;
			} else if (value > 0) {
				cc |= 0x2;
			}
			if (hi > 0 || hi < -1 || (hi == -1 && lo > 0) || (hi == 0 && lo == 0x80000000)) {
				cc |= 0x4;
			}
		}
	}

	// SF operation .24
	protected class SF extends Instruction {
		protected SF() { super("SF", 0x24); }
		protected void execute(int iWord) {
			int regR = (iWord >>> 20) & 0x0f;
			int regX = (iWord >>> 17) & 0x07;
			int addr = iWord & 0x1ffff;

			if (iWord < 0) {
				addr = memory.readWord(addr) & 0x1ffff;
			}
			int type = (addr >>> 8) & 0x7;
			int count = addr & 0x7F;
			if (regX != 0) {
				count += currentRegisters[regX] & 0x7F;
			}
			count <<= 25;
			count >>= 25;
			cc &= 0x3;
			if ((addr & 0x100) == 0) {
				if (count >= 0) {
					doSFSinglePosCount(regR, count);
				} else {
					doSFSingleNegCount(regR, count);
				}
			} else {
				if (count >= 0) {
					doSFDoublePosCount(regR, count);
				} else {
					doSFDoubleNegCount(regR, count);
				}
			}
		}

		protected void doSFSinglePosCount(int regR, int count) {
			int r;
			r = currentRegisters[regR];
			boolean neg = r < 0;
			if (neg) {
				r = -r;
			}
			int c = (r >>> 24) & 0x7f;
			int f = r & 0x00ffffff;
			cc &= 0x3;
			boolean underflow = false;
			if (f == 0) {
				cc = 0x8;
				c = 0;
				neg = false;
			} else while (count > 0 && (f & 0x00f00000) == 0) {
				f <<= 4;
				c -= 1;
				count -= 1;
				if ((c & 0x7f) == 0x7f) {
					underflow = true;
					break;
				}
			}
			r = ((c & 0x7f) << 24) | f;
			if (neg) {
				r = -r;
				cc &= 0xc;
				cc |= 0x1;
			} else if (r > 0) {
				cc &= 0xc;
				cc |= 0x2;
			}
			currentRegisters[regR] = r;
			if (count == 0) {
				cc &= 0x3;
			}
			if (underflow) {
				cc |= 0x4;
			}
			if ((f & 0x00f00000) != 0) {
				cc |= 0x8;
			}
		}

		protected void doSFSingleNegCount(int regR, int count) {
			count = -count;
			int r;
			r = currentRegisters[regR];
			boolean neg = r < 0;
			if (neg) {
				r = -r;
			}
			int c = (r >>> 24) & 0x7f;
			int f = r & 0x00ffffff;
			cc &= 0x3;
			boolean underflow = false;
			if (f == 0) {
				cc = 0x8;
				c = 0;
				neg = false;
			} else while (count > 0 && f != 0) {
				f >>>= 4;
				c += 1;
				count -= 1;
				if ((c & 0x7f) == 0) {
					underflow = true;
					break;
				}
			}
			if (f == 0) {
				cc = 0x0;
				c = 0;
				neg = false;
				underflow = false;
			}
			r = ((c & 0x7f) << 24) | f;
			if (neg) {
				r = -r;
				cc &= 0xc;
				cc |= 0x1;
			} else if (r > 0) {
				cc &= 0xc;
				cc |= 0x2;
			}
			currentRegisters[regR] = r;
			if (count == 0) {
				cc &= 0x3;
			}
			if (underflow) {
				cc |= 0x4;
			}
			if ((f & 0x00f00000) != 0) {
				cc |= 0x8;
			}
		}

		protected void doSFDoublePosCount(int regR, int count) {
			long rd, rdu1;
			rd = currentRegisters[regR];
			rdu1 = currentRegisters[regR | 1];
			rd <<= 32;
			rd |= rdu1 & 0xffffffffL;

			boolean neg = rd < 0;
			if (neg) {
				rd = -rd;
			}
			long c = (rd >>> (24+32)) & 0x7fL;
			long f = rd & 0x00ffffffffffffffL;
			cc &= 0x3;
			boolean underflow = false;
			if (f == 0) {
				cc = 0x8;
				c = 0;
				neg = false;
			} else while (count > 0 && (f & 0x00f0000000000000L) == 0) {
				f <<= 4;
				c -= 1;
				count -= 1;
				if ((c & 0x7fL) == 0x7fL) {
					underflow = true;
					break;
				}
			}
			rd = ((c & 0x7fL) << (24+32)) | f;
			if (neg) {
				rd = -rd;
				cc &= 0xc;
				cc |= 0x1;
			} else if (rd > 0) {
				cc &= 0xc;
				cc |= 0x2;
			}
			currentRegisters[regR | 1] = (int) rd;
			currentRegisters[regR] = (int) (rd >>> 32);
			if (count == 0) {
				cc &= 0x3;
			}
			if (underflow) {
				cc |= 0x4;
			}
			if ((f & 0x00f0000000000000L) != 0) {
				cc |= 0x8;
			}
		}

		protected void doSFDoubleNegCount(int regR, int count) {
			count = -count;
			long rd, rdu1;
			rd = currentRegisters[regR];
			rdu1 = currentRegisters[regR | 1];
			rd <<= 32;
			rd |= rdu1 & 0xffffffffL;

			boolean neg = rd < 0;
			if (neg) {
				rd = -rd;
			}
			long c = (rd >>> (24+32)) & 0x7fL;
			long f = rd & 0x00ffffffffffffffL;
			cc &= 0x3;
			boolean underflow = false;
			if (f == 0) {
				cc = 0x8;
				c = 0;
				neg = false;
			} else while (count > 0 && f != 0) {
				f >>>= 4;
				c += 1;
				count -= 1;
				if ((c & 0x7fL) == 0) {
					underflow = true;
					break;
				}
			}
			if (f == 0) {
				cc = 0x0;
				c = 0;
				neg = false;
				underflow = false;
			}
			rd = ((c & 0x7f) << (24+32)) | f;
			if (neg) {
				rd = -rd;
				cc &= 0xc;
				cc |= 0x1;
			} else if (rd > 0) {
				cc &= 0xc;
				cc |= 0x2;
			}
			currentRegisters[regR | 1] = (int) rd;
			currentRegisters[regR] = (int) (rd >>> 32);
			if (count == 0) {
				cc &= 0x3;
			}
			if (underflow) {
				cc |= 0x4;
			}
			if ((f & 0x00f0000000000000L) != 0) {
				cc |= 0x8;
			}
		}
	}

	// S operation .25
	protected class S extends Instruction {
		protected S() { super("S", 0x25); }
		protected void execute(int iWord) {
			int regR = (iWord >>> 20) & 0x0f;
			int regX = (iWord >>> 17) & 0x07;
			int addr = iWord & 0x1ffff;

			if (iWord < 0) {
				addr = memory.readWord(addr) & 0x1ffff;
			}
			int type = (addr >>> 8) & 0x7;
			int count = addr & 0x7F;
			if (regX != 0) {
				count += currentRegisters[regX] & 0x7F;
			}
			count <<= 25;
			count >>= 25;
			cc &= 0x3;
			int r, ru1;
			long rd, rdu1;
			switch (type) {
				case 0:	// SLS
				if (count >= 0) {
					r = currentRegisters[regR];
					boolean sign = r >= 0;
					for (int i=0; i<count; i+=1) {
						if (r < 0) {
							cc ^= 0x8;
						}
						r <<= 1;
						if (sign != (r >= 0)) {
							cc |= 0x4;
						}
					}
					currentRegisters[regR] = r;
				} else {
					currentRegisters[regR] >>>= -count;
				}
				break;

				case 1:	// SLD
				rd = currentRegisters[regR];
				rdu1 = currentRegisters[regR | 1];
				rd <<= 32;
				rd |= rdu1 & 0x0ffffffffL;
				if (count >= 0) {
					boolean sign = rd >= 0;
					for (int i=0; i<count; i+=1) {
						if (rd < 0) {
							cc ^= 0x8;
						}
						rd <<= 1;
						if (sign != (rd >= 0)) {
							cc |= 0x4;
						}
					}
				} else {
					rd >>>= -count;
				}
				// Not sure of the order of register load...
				currentRegisters[regR | 1] = (int) (rd & 0x0ffffffff);
				currentRegisters[regR] = (int) (rd >> 32);
				break;

				case 2:	// SCS
				r = currentRegisters[regR];
				if (count >= 0) {
					boolean sign = r >= 0;
					for (int i=0; i<count; i+=1) {
						int lsb;
						if (r < 0) {
							cc ^= 0x8;
							lsb = 1;
						} else {
							lsb = 0;
						}
						r <<= 1;
						r |= lsb;
						if (sign != (r >= 0)) {
							cc |= 0x4;
						}
					}
				} else {
					count = -count;
					for (int i=0; i<count; i+=1) {
						int msb;
						if ((r & 1) != 0) {
							msb = 0x80000000;
						} else {
							msb = 0;
						}
						r >>>= 1;
						r |= msb;
					}
				}
				currentRegisters[regR] = r;
				break;

				case 3:	// SCD
				rd = currentRegisters[regR];
				rdu1 = currentRegisters[regR | 1];
				rd <<= 32;
				rd |= rdu1 & 0x0ffffffffL;
				if (count >= 0) {
					boolean sign = rd >= 0;
					for (int i=0; i<count; i+=1) {
						long lsb;
						if (rd < 0) {
							cc ^= 0x8;
							lsb = 1;
						} else {
							lsb = 0;
						}
						rd <<= 1;
						rd |= lsb;
						if (sign != (rd >= 0)) {
							cc |= 0x4;
						}
					}
				} else {
					count = -count;
					for (int i=0; i<count; i+=1) {
						long msb;
						if ((rd & 1L) != 0) {
							msb = 0x8000000000000000L;
						} else {
							msb = 0;
						}
						rd >>>= 1;
						rd |= msb;
					}
				}
				// Not sure of the order of register load...
				currentRegisters[regR | 1] = (int) (rd & 0x0ffffffff);
				currentRegisters[regR] = (int) (rd >> 32);
				break;

				case 4:	// SAS
				if (count >= 0) {
					r = currentRegisters[regR];
					boolean sign = r >= 0;
					for (int i=0; i<count; i+=1) {
						if (r < 0) {
							cc ^= 0x8;
						}
						r <<= 1;
						if (sign != (r >= 0)) {
							cc |= 0x4;
						}
					}
					currentRegisters[regR] = r;
				} else {
					currentRegisters[regR] >>= -count;
				}
				break;

				case 5:	// SAD
				rd = currentRegisters[regR];
				rdu1 = currentRegisters[regR | 1];
				rd <<= 32;
				rd |= rdu1 & 0x0ffffffffL;
				if (count >= 0) {
					boolean sign = rd >= 0;
					for (int i=0; i<count; i+=1) {
						if (rd < 0) {
							cc ^= 0x8;
						}
						rd <<= 1;
						if (sign != (rd >= 0)) {
							cc |= 0x4;
						}
					}
				} else {
					rd >>= -count;
				}
				// Not sure of the order of register load...
				currentRegisters[regR | 1] = (int) (rd & 0x0ffffffff);
				currentRegisters[regR] = (int) (rd >> 32);
				break;

				case 6:	// SSS as defined by Sig9, unknown for Sig6
				r = currentRegisters[regR];
				if (count >= 0) {
					boolean sign = r >= 0;
					while (count > 0 && r > 0) {
						r <<= 1;
						if (sign != (r >= 0)) {
							cc |= 0x4;
						}
						count -= 1;
					}
					if (r < 0) {
						cc |= 0x1;
					}
				} else {
					count = -count;
					boolean sign = r >= 0;
					int msb = 0;
					while (count > 0 && r > 0) {
						if ((r & 0x1) > 0) {
							msb = 0x80000000;
						}
						r >>= 1;
						r |= msb;
						if (sign != (r >= 0)) {
							cc |= 0x4;
						}
						count -= 1;
					}
					if (r < 0) {
						cc |= 0x1;
					}
					count = -count;
				}
				// Sig9 stores remaining count in R1
				// 7AUTO does not test it here, but in SSD
				// currentRegisters[1] = count & 0x7f;
				currentRegisters[regR] = r;
				break;

				case 7:	// SSD as defined by Sig9, unknown for Sig6
				rd = currentRegisters[regR];
				rdu1 = currentRegisters[regR | 1];
				rd <<= 32;
				rd |= rdu1 & 0x0ffffffffL;
				if (count >= 0) {
					boolean sign = rd >= 0;
					while (count > 0 && rd > 0) {
						rd <<= 1;
						if (sign != (rd >= 0)) {
							cc |= 0x4;
						}
						count -= 1;
					}
					if (rd < 0) {
						cc |= 0x1;
					}
				} else {
					count = -count;
					boolean sign = rd >= 0;
					long msb = 0;
					while (count > 0 && rd > 0) {
						if ((rd & 1L) != 0) {
							msb = 0x8000000000000000L;
						}
						rd >>>= 1;
						rd |= msb;
						if (sign != (rd >= 0)) {
							cc |= 0x4;
						}
						count -= 1;
					}
					if (rd < 0) {
						cc |= 0x1;
					}
					count = -count;
				}
				// Sig9 stores remaining count in R1
				// 7AUTO does not like that, maybe Sig7 is different?
				// currentRegisters[1] = count & 0x7f;
				// Not sure of the order of register load...
				currentRegisters[regR | 1] = (int) (rd & 0x0ffffffff);
				currentRegisters[regR] = (int) (rd >> 32);
				break;
			}
		}
	}

	// LAS operation .26
	protected class LAS extends WordIndexedInstruction {
		protected LAS() { super("LAS", 0x26); }
		protected void execute(int regR, int addr) {
			int value = memory.readWord(addr);
			currentRegisters[regR] = value;
			if (addr > 15) {
				value |= 0x80000000;
				memory.writeWord(addr, value);
			}
			cc &= 0x0c;
			if (value < 0) {
				cc |= 0x01;
			} else if (value > 0) {
				cc |= 0x02;
			}
		}
	}

	// ?? operation .27

	// CVS operation .28
	protected class CVS extends WordIndexedInstruction {
		protected CVS() { super("CVS", 0x28); }

		protected void execute(int regR, int addr) {		//CVS 28 added 11/24/02 KGC
			long value = currentRegisters[regR] & 0xffffffffL;
			int rvalue = 0;
			for (int i=0; i<32; i++) {
				if (((long) memory.readWord(addr + i) & 0xffffffffL) <= value) {
					value -= (long) memory.readWord(addr + i) & 0xffffffffL;
					rvalue |= 1;
				}
				if (i !=31) {
					rvalue = rvalue << 1;
				}
			}
			currentRegisters[regR] = (int) value;
			currentRegisters[regR | 0x1] = rvalue;
			cc &= 0xc;
			if (currentRegisters[regR | 0x1] < 0) {
				cc |=0x1;}
			if (currentRegisters[regR | 0x1] > 0) {
				cc |=0x2;
			}
		}
	}

	// CVA operation .29
	protected class CVA extends WordIndexedInstruction {
		protected CVA() { super("CVA", 0x29); }
		protected void execute(int regR, int addr) {         //CVA=29 added 11/24/02 KGC
			long value = 0;
			int rvalue = currentRegisters[regR | 0x1];
			for (int i=0; i<32; i++) {
				if ((rvalue & 0x80000000) != 0) {
					value += (long) memory.readWord(addr + i) & 0xffffffffL;
				}
				rvalue = rvalue << 1;
			}
			currentRegisters[regR] = (int) value & 0xffffffff;
			cc &= 0x4;
			if (currentRegisters[regR] < 0) {
				cc |=0x1;
			}
			if (currentRegisters[regR] > 0) {
				cc |=0x2;
			}
			if (value > 0xffffffffL) {
				cc |=0x8;
			}
		}
	}

	// LM operation .2A
	protected class LM extends WordIndexedInstruction {
		protected LM() { super("LM", 0x2A); }
		protected void execute(int regR, int addr) {
			int n = cc;
			if (n == 0) {
				n = 16;
			}
			for (int i=0; i<n; i+=1) {
				int value = memory.readWord(addr++);
				currentRegisters[regR++ & 0xf] = value;
			}
		}
	}

	// STM operation .2B
	protected class STM extends WordIndexedInstruction {
		protected STM() { super("STM", 0x2B); }
		protected void execute(int regR, int addr) {
			int n = cc;
			if (n == 0) {
				n = 16;
			}
			for (int i=0; i<n; i+=1) {
				int value = currentRegisters[regR++ & 0xf];
				memory.writeWord(addr++, value);
			}
		}
	}

	// ?? operation .2C
	// LMS operation .2D
	protected class LMS extends PrivelegedWordIndexedInstruction {
		protected LMS() { super("LMS", 0x2D); }
		protected void execute(int regR, int addr) {
			int value = memory.readWord(addr);
			currentRegisters[regR] = value;
			if (addr > 15) {
				value |= 0x80000000;
				memory.writeWord(addr, value);
			}
		}
	}

	// WAIT operation .2E
	protected class WAIT extends PrivelegedWordIndexedInstruction {
		protected WAIT() { super("WAIT", 0x2E); }
		protected void execute(int regR, int addr) {
			throw new IllegalArgumentException("WAIT!");
		}
	}

	// LRP operation .2F
	protected class LRP extends PrivelegedWordIndexedInstruction {
		protected LRP() { super("LRP", 0x2F); }
		protected void execute(int regR, int addr) {
			int a = memory.readWord(addr);
			setRP(a >>> 4);
		}
	}

	// AW operation .30
	protected class AW extends WordIndexedInstruction {
		protected AW() { super("AW", 0x30); }
		protected void execute(int regR, int addr) {
			int a = memory.readWord(addr);
			int b = currentRegisters[regR];

			int result = currentRegisters[regR] += a;
			cc = 0;
			if (result < 0) {
				cc |= 0x1;
			} else if (result > 0) {
				cc |= 0x2;
			}
			int a0 = a & 0x80000000;
			int b0 = b & 0x80000000;
			int c0 = result & 0x80000000;
			if (((~(a0 ^ b0)) & (c0 ^ a0)) != 0) {
				cc |= 0x4;
			}
			if ((a0 != 0 || b0 != 0) && ((a0 != 0 && b0 != 0) ||
				((a & 0x7fffffff) + (b & 0x7fffffff) < 0))) {
				cc |= 0x8;
			}
			if (am && (cc & 0x4) != 0) {
				trap(0x43);
			}
		}
	}

	// CW operation .31
	protected class CW extends WordIndexedInstruction {
		protected CW() { super("CW", 0x31); }
		protected void execute(int regR, int addr) {
			int value = memory.readWord(addr);
			int r = currentRegisters[regR];
			cc &= 0x8;
			if (r < value) {
				cc |= 0x1;
			} else if (r > value) {
				cc |= 0x2;
			}
			if ((r & value) != 0) {
				cc |= 0x4;
			}
		}
	}

	// LW operation .32
	protected class LW extends WordIndexedInstruction {
		protected LW() { super("LW", 0x32); }
		protected void execute(int regR, int addr) {
			int value = memory.readWord(addr);
			currentRegisters[regR] = value;
			cc &= 0x0c;
			if (value < 0) {
				cc |= 0x01;
			} else if (value > 0) {
				cc |= 0x02;
			}
		}
	}

	// MTW operation .33
	protected class MTW extends WordIndexedInstruction implements
		InterruptInstruction {

		protected int loc;
		protected boolean inTrap;

		protected MTW() { super("MTW", 0x33); loc = 0; }

		public void setLocation(int loc) { this.loc = loc; inTrap = false; }
		public void setInTrap(boolean inTrap) {
			this.inTrap = inTrap;
		}

		protected void execute(int regR, int addr) {
			int value = memory.readWord(addr);
			int localCC = 0;
			if (regR == 0) {
				if (value < 0) {
					localCC |= 0x1;
				} else  if (value > 0) {
					localCC |= 0x2;
				}
			} else {
				if ((regR & 0x8) != 0) {
					regR |= 0xfffffff0;
				}
				int a = value;
				int b = regR;
				int result = a + b;
				memory.writeWord(addr, result);
				if (result < 0) {
					localCC |= 0x1;
				} else if (result > 0) {
					localCC |= 0x2;
				}
				int a0 = a & 0x80000000;
				int b0 = b & 0x80000000;
				int c0 = result & 0x80000000;
				if (((~(a0 ^ b0)) & (c0 ^ a0)) != 0) {
					localCC |= 0x4;
				}
				if ((a0 != 0 || b0 != 0) && ((a0 != 0 && b0 != 0) ||
					((a & 0x7fffffff) + (b & 0x7fffffff) < 0))) {
					localCC |= 0x8;
				}
			}
			if (!inTrap) {
				cc = localCC;	// not in interrupt
				if (am && (cc & 0x4) != 0) {
					trap(0x43);
				}
			} else {
				clearInterrupt(loc);
				if ((localCC & 0x3) == 0) {
					interrupt(loc + 6);
				}
			}
		}
	}

	// ?? operation .34

	// STW operation .35
	protected class STW extends WordIndexedInstruction {
		protected STW() { super("STW", 0x35); }
		protected void execute(int regR, int addr) {
			memory.writeWord(addr, currentRegisters[regR]);
		}
	}

	// DW operation .36
	protected class DW extends WordIndexedInstruction {
		protected DW() { super("DW", 0x36); }
		protected void execute(int regR, int addr) {
			long den = memory.readWord(addr);
			cc &= 0xb;
			if (den == 0) {
				cc |= 0x4;
				if (am) {
					trap(0x43);
				}
				return;
			}
			long num;
			if ((regR & 1) == 0) {
				num = currentRegisters[regR];
				num <<= 32;
				long nu1 = currentRegisters[regR | 1];
				num |= nu1 & 0x0ffffffffL;
			} else {
				num = currentRegisters[regR];
			}
			long quotient = num / den;
			int hi = (int) (quotient >>> 32);
			int lo = (int) quotient;
			long remainder = num % den;
			if (hi > 0 || hi < -1 || (hi == -1 && lo > 0) || (hi == 0 && lo < 0) ||
				(lo == 0x80000000)) {
				cc |= 0x4;
				if (am) {
					trap(0x43);
				}
				return;
			}
			currentRegisters[regR] = (int) remainder;
			int value = currentRegisters[regR | 1] = (int) quotient;
			cc &= 0xc;
			if (value < 0) {
				cc |= 0x1;
			} else if (value > 0) {
				cc |= 0x2;
			}
		}
	}

	// MW operation .37
	protected class MW extends WordIndexedInstruction {
		protected MW() { super("MW", 0x37); }
		protected void execute(int regR, int addr) {
			long value = memory.readWord(addr);
			value *= currentRegisters[regR | 1];
			int hi = currentRegisters[regR] = (int) (value >>> 32);
			int lo = currentRegisters[regR | 1] = (int) value;
			cc &= 0x8;
			if (value < 0) {
				cc |= 0x1;
			} else if (value > 0) {
				cc |= 0x2;
			}
			if (hi > 0 || hi < -1 || (hi == -1 && lo > 0) || (hi == 0 && lo == 0x80000000)) {
				cc |= 0x4;
			}
		}
	}

	// SW operation .38
	protected class SW extends WordIndexedInstruction {
		protected SW() { super("SW", 0x38); }
		protected void execute(int regR, int addr) {
			int a = -memory.readWord(addr);
			int b = currentRegisters[regR];

			int result = currentRegisters[regR] += a;
			cc = 0;
			if (result < 0) {
				cc |= 0x1;
			} else if (result > 0) {
				cc |= 0x2;
			}
			int a0 = a & 0x80000000;
			int b0 = b & 0x80000000;
			int c0 = result & 0x80000000;
			if ((a != -b) && ((~(a0 ^ b0)) & (c0 ^ a0)) != 0) {
				cc |= 0x4;
			}
			if ((a0 != 0 || b0 != 0) && ((a0 != 0 && b0 != 0) ||
				((a & 0x7fffffff) + (b & 0x7fffffff) < 0)) ||
				a == 0) {
				cc |= 0x8;
			}
			if (am && (cc & 0x4) != 0) {
				trap(0x43);
			}
		}
	}

	// CLR operation .39
	protected class CLR extends WordIndexedInstruction {
		protected CLR() { super("CLR", 0x39); }
		protected void execute(int regR, int addr) {
			int value = memory.readWord(addr);
			int r = currentRegisters[regR];
			int ru1 = currentRegisters[regR | 1];
			cc = 0;
			if (r < value) {
				cc |= 0x1;
			} else if (r > value) {
				cc |= 0x2;
			}
			if (ru1 < value) {
				cc |= 0x4;
			} else if (ru1 > value) {
				cc |= 0x8;
			}
		}
	}

	// LCW operation .3A
	protected class LCW extends WordIndexedInstruction {
		protected LCW() { super("LCW", 0x3A); }
		protected void execute(int regR, int addr) {
			int value = memory.readWord(addr);
			int result = currentRegisters[regR] = -value;
			cc &= 0x8;
			if (result == 0x80000000) {
				cc |= 0x5;
				if (am) {
					trap(0x43);
				}
			} else if (result < 0) {
				cc |= 0x1;
			} else if (result > 0) {
				cc |= 0x2;
			}
		}
	}

	// LAW operation .3B
	protected class LAW extends WordIndexedInstruction {
		protected LAW() { super("LAW", 0x3B); }
		protected void execute(int regR, int addr) {
			int value = memory.readWord(addr);
			int result;
			if (value >= 0) {
				result = currentRegisters[regR] = value;
			} else {
				result = currentRegisters[regR] = -value;
			}
			cc &= 0x8;
			if (result == 0x80000000) {
				cc |= 0x5;
				if (am) {
					trap(0x43);
				}
			} else if (result != 0) {
				cc |= 0x2;
			}
		}
	}

	// FSS operation .3C
	// FAS operation .3D
	// FDS operation .3E
	// FMS operation .3F

	// TTBS operation .40
	protected class TTBS extends Instruction {
		protected TTBS() { super("TTBS", 0x40); }
		protected void execute(int iWord) {
			if (iWord < 0) {
				trap40(NONEXISTENT_INSTRUCTION);
			} else {
				int regR = (iWord >>> 20) & 0x0f;
				int disp = iWord & 0xfffff;
				disp <<= 12; disp >>= 12;    // sign extend
				int tmask=0; int i=0; cc &= 0xE;
				if (regR != 0) {
					int rVal = currentRegisters[regR];
					int r1Val = currentRegisters[regR | 1];
					int src = rVal & 0x7ffff;
					int mask = (rVal >> 24) & 0xff;
					int dst = r1Val & 0x7ffff;
					int count = (r1Val >> 24) & 0xff;
					for (i=0; (i<count) & (tmask==0); i+=1) {
						int bd = memory.readByte(dst++) & 0xff;
						int bt = memory.readByte(disp + src + bd);
						tmask = mask & bt;
					}
					if (tmask != 0) {
						dst--; src--; i--; cc |= 1;
					}
					currentRegisters[regR] &= 0x00ffffff;
					currentRegisters[regR] |= tmask << 24;
					currentRegisters[regR | 1] &= 0x00f80000;
					currentRegisters[regR | 1] |= (dst | (count-i << 24));
				} else {
					int mask = 0xff;
					int r1Val = currentRegisters[1];
					int dst = r1Val & 0x7ffff;
					int count = (r1Val >> 24) & 0xff;
					for (i=0; (i<count) & (tmask==0); i+=1) {
						int bd = memory.readByte(dst++) & 0xff;
						int bt = memory.readByte(disp + bd);
						tmask = mask & bt;
					}
					if (tmask !=0) {
						dst--; i--; cc |= 1;
					}
					currentRegisters[1] &= 0x00f80000;
					currentRegisters[1] |= (dst | (count-i << 24));
				}
			}
		}
	}

	// TBS operation .41
	protected class TBS extends Instruction {
		protected TBS() { super("TBS", 0x41); }
		protected void execute(int iWord) {
			if (iWord < 0) {trap40(NONEXISTENT_INSTRUCTION);} else {
				int regR = (iWord >>> 20) & 0x0f;
				int disp = iWord & 0xfffff;
				disp <<= 12; disp >>= 12;    // sign extend
				if (regR != 0) {
					int rVal = currentRegisters[regR];
					int r1Val = currentRegisters[regR | 1];
					int src = rVal & 0x7ffff;
					int dst = r1Val & 0x7ffff;
					int count = (r1Val >> 24) & 0xff;
					for (int i=0; i<count; i+=1) {
						int bd = memory.readByte(dst) & 0xff;
						int bt = memory.readByte(disp + src + bd);
						memory.writeByte(dst++, bt);
					}
					currentRegisters[regR | 1] &= 0x00f80000;
					currentRegisters[regR | 1] |= dst;
				} else {
					int r1Val = currentRegisters[1];
					int dst = r1Val & 0x7ffff;
					int count = (r1Val >> 24) & 0xff;
					for (int i=0; i<count; i+=1) {
						int bd = memory.readByte(dst) & 0xff;
						int bt = memory.readByte(disp + bd);
						memory.writeByte(dst++, bt);
					}
					currentRegisters[1] &= 0x00f8000;
					currentRegisters[1] |= dst;
				}
			}
		}
	}

	// ?? operation .42
	// ?? operation .43

	protected final static int ANLZ_BYTE = 0;
	protected final static int ANLZ_IMM_BYTE = 1;
	protected final static int ANLZ_HALFWORD = 4;
	protected final static int ANLZ_WORD = 8;
	protected final static int ANLZ_IMM_WORD = 9;
	protected final static int ANLZ_DOUBLEWORD = 12;

	protected static final byte[] ANLZ_TABLE = {
		9,  9,  9,  9,  8,  8,  8,  8,  12, 12, 12, 12, 12, 12, 12, 12,
		12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12,
		9,  9,  9,  9,  8,  8,  8,  8,  8,  8,  8,  8,  8,  8,  8,  8,
		8,  8,  8,  8,  8,  8,  8,  8,  8,  8,  8,  8,  8,  8,  8,  8,
		1,  1,  1,  1,  8,  8,  8,  8,  8,  8,  8,  8,  8,  8,  8,  8,
		4,  4,  4,  4,  4,  4,  4,  4,  4,  4,  4,  4,  4,  4,  4,  4,
		1,  1,  1,  1,  8,  8,  8,  8,  8,  8,  8,  8,  8,  8,  8,  8,
		0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0
	};

	// ANLZ operation .44
	protected class ANLZ extends WordIndexedInstruction {
		protected ANLZ() { super("ANLZ", 0x44); }
		protected void execute(int regR, int addr) {
			int iWord = memory.readWord(addr);
			int code = (iWord >>> 24) & 0x7f;
			int regX = (iWord >>> 17) & 0x07;
			addr = iWord & 0x1ffff;
			int type = ANLZ_TABLE[code];
			cc = type;
			switch (type) {
				case ANLZ_IMM_BYTE:
				case ANLZ_IMM_WORD:
				break;

				case ANLZ_BYTE:
				if (iWord < 0) {
					addr = memory.readWord(addr) & 0x1ffff;
					cc |= 0x2;
				}
				addr <<= 2;
				if (regX != 0) {
					addr += currentRegisters[regX];
				}
				currentRegisters[regR] = addr & 0x0007ffff;
				break;

				case ANLZ_HALFWORD:
				if (iWord < 0) {
					addr = memory.readWord(addr) & 0x1ffff;
					cc |= 0x2;
				}
				addr <<= 1;
				if (regX != 0) {
					addr += currentRegisters[regX];
				}
				currentRegisters[regR] = addr & 0x0003ffff;
				break;

				case ANLZ_WORD:
				if (iWord < 0) {
					addr = memory.readWord(addr) & 0x1ffff;
					cc |= 0x2;
				}
				if (regX != 0) {
					addr += currentRegisters[regX];
				}
				currentRegisters[regR] = addr & 0x0001ffff;
				break;

				case ANLZ_DOUBLEWORD:
				if (iWord < 0) {
					addr = memory.readWord(addr) & 0x1ffff;
					cc |= 0x2;
				}
				addr >>>= 1;
				if (regX != 0) {
					addr += currentRegisters[regX];
				}
				currentRegisters[regR] = addr & 0x0000ffff;
				break;

				default:
					throw new IllegalArgumentException("ANLZ table is bogus!");
			}
		}
	}

	// CS operation .45
	protected class CS extends WordIndexedInstruction {
		protected CS() { super("CS", 0x45); }
		protected void execute(int regR, int addr) {
			int value = memory.readWord(addr);
			int r = currentRegisters[regR];
			long lR, lEW;
			if ((regR & 1) == 0) {
				int ru1 = currentRegisters[regR | 1];
				lR = (r & ru1) & 0xffffffffL;
				lEW = (value & ru1) & 0xffffffffL;
			} else {
				lR = r & 0xffffffffL;
				lEW = (value & r) & 0xffffffffL;
			}
			cc &= 0xc;
			if (lR < lEW) {
				cc |= 0x1;
			} else if (lR > lEW) {
				cc |= 0x2;
			}
		}
	}

	// XW operation .46
	protected class XW extends WordIndexedInstruction {
		protected XW() { super("XW", 0x46); }
		protected void execute(int regR, int addr) {
			int value = memory.readWord(addr);
			int rvalue = currentRegisters[regR];
			currentRegisters[regR] = value;
			memory.writeWord(addr, rvalue);
			cc &= 0x0c;
			if (value < 0) {
				cc |= 0x01;
			} else if (value > 0) {
				cc |= 0x02;
			}
		}
	}

	// STS operation .47
	protected class STS extends WordIndexedInstruction {
		protected STS() { super("STS", 0x47); }
		protected void execute(int regR, int addr) {
			int value = memory.readWord(addr);
			int result;
			if ((regR & 1) == 0) {
				int r = currentRegisters[regR];
				int ru1 = currentRegisters[regR | 1];
				result = (r & ru1) | (value & ~ru1);
			} else {
				result = value | currentRegisters[regR];
			}
			memory.writeWord(addr, result);
		}
	}

	// EOR operation .48
	protected class EOR extends WordIndexedInstruction {
		protected EOR() { super("EOR", 0x48); }
		protected void execute(int regR, int addr) {
			int value = memory.readWord(addr);
			int result = currentRegisters[regR] ^= value;
			cc &= 0x0c;
			if (result < 0) {
				cc |= 0x01;
			} else if (result > 0) {
				cc |= 0x02;
			}
		}
	}

	// OR operation .49
	protected class OR extends WordIndexedInstruction {
		protected OR() { super("OR", 0x49); }
		protected void execute(int regR, int addr) {                //OR is 49 added 11/22/02 KGC
			int value = memory.readWord(addr);
			int result = currentRegisters[regR] |= value;
			cc &= 0x0c;
			if (result < 0) {
				cc |= 0x01;
			} else if (result > 0) {
				cc |= 0x02;
			}
		}
	}

	// LS operation .4A
	protected class LS extends WordIndexedInstruction {
		protected LS() { super("LS", 0x4A); }
		protected void execute(int regR, int addr) {
			int value = memory.readWord(addr);
			int result;
			if ((regR & 1) == 0) {
				int r = currentRegisters[regR];
				int ru1 = currentRegisters[regR | 1];
				result = (value & ru1) | (r & ~ru1);
			} else {
				result = value & currentRegisters[regR];
			}
			currentRegisters[regR] = result;
			cc &= 0xc;
			if (result < 0) {
				cc |= 0x1;
			} else if (result > 0) {
				cc |= 0x2;
			}
		}
	}

	// AND operation .4B
	protected class AND extends WordIndexedInstruction {
		protected AND() { super("AND", 0x4B); }
		protected void execute(int regR, int addr) {
			int value = memory.readWord(addr);
			int result = currentRegisters[regR] &= value;
			cc &= 0x0c;
			if (result < 0) {
				cc |= 0x01;
			} else if (result > 0) {
				cc |= 0x02;
			}
		}
	}

	// SIO operation .4C
	protected class SIO extends PrivelegedWordIndexedInstruction {
		protected SIO() { super("SIO", 0x4C); }
		protected void execute(int regR, int addr) {
			int ioAddr = addr & 0x7ff;
			cc &= 0x03;
			IOProcessor iop = iopMgr.getIOP(ioAddr);
			if (iop != null) {
				iop.startIO(currentRegisters[0]);
				if ((cc & 0xc) == 4 && regR != 0) {
					currentRegisters[regR] = iop.getCommandDWordAddr();
					currentRegisters[regR | 0x1] = iop.getStatus();
				}
			} else {
				cc |= 0xc;
				// throw new IllegalArgumentException(
				//	"Nonexistent IOP addr: " + ioAddr);
			}
		}
	}

	// TIO operation .4D
	protected class TIO extends PrivelegedWordIndexedInstruction {
		protected TIO() { super("TIO", 0x4D); }
		protected void execute(int regR, int addr) {
			int ioAddr = addr & 0x7ff;
			cc &= 0x3;
			IOProcessor iop = iopMgr.getIOP(ioAddr);
			if (iop != null) {
				iop.testIO();
				if ((cc & 0x8) == 0 && regR != 0) {
					currentRegisters[regR] = iop.getCommandDWordAddr();
					currentRegisters[regR | 0x1] = iop.getStatus();
				}
			} else {
				cc |= 0xc;
				// throw new IllegalArgumentException(
				//	"Nonexistent IOP addr: " + ioAddr);
			}
		}
	}

	// TDV operation .4E
	protected class TDV extends PrivelegedWordIndexedInstruction {
		protected TDV() { super("TDV", 0x4E); }
		protected void execute(int regR, int addr) {
			int ioAddr = addr & 0x7ff;
			cc &= 0x3;
			IOProcessor iop = iopMgr.getIOP(ioAddr);
			if (iop != null) {
				int tStat = iop.testDevice();
				if ((cc & 0x8) == 0 && regR != 0) {
					currentRegisters[regR] = iop.getCommandDWordAddr();
					currentRegisters[regR | 0x1] = tStat;
				}
			} else {
				cc |= 0xc;
				// throw new IllegalArgumentException(
				//	"Nonexistent IOP addr: " + ioAddr);
			}
		}
	}

	// HIO operation .4F
	protected class HIO extends PrivelegedWordIndexedInstruction {
		protected HIO() { super("HIO", 0x4F); }
		protected void execute(int regR, int addr) {
			int ioAddr = addr & 0x7ff;
			cc &= 0x3;
			IOProcessor iop = iopMgr.getIOP(ioAddr);
			if (iop != null) {
				iop.haltIO();
				if (regR != 0) {
					currentRegisters[regR] = iop.getCommandDWordAddr();
					currentRegisters[regR | 0x1] = iop.getStatus();
				}
			} else {
				cc |= 0xc;
				// throw new IllegalArgumentException(
				//	"Nonexistent IOP addr: " + ioAddr);
			}
		}
	}

	// AH operation .50
	protected class AH extends HalfWordIndexedInstruction {
		protected AH() { super("AH", 0x50); }
		protected void execute(int regR, int addr) {
			int a = memory.readHalfWord(addr);
			int b = currentRegisters[regR];

			int result = currentRegisters[regR] += a;
			cc = 0;
			if (result < 0) {
				cc |= 0x1;
			} else if (result > 0) {
				cc |= 0x2;
			}
			int a0 = a & 0x80000000;
			int b0 = b & 0x80000000;
			int c0 = result & 0x80000000;
			if (((~(a0 ^ b0)) & (c0 ^ a0)) != 0) {
				cc |= 0x4;
			}
			if ((a0 != 0 || b0 != 0) && ((a0 != 0 && b0 != 0) ||
				((a & 0x7fffffff) + (b & 0x7fffffff) < 0))) {
				cc |= 0x8;
			}
			if (am && (cc & 0x4) != 0) {
				trap(0x43);
			}
		}
	}

	// CH operation .51
	protected class CH extends HalfWordIndexedInstruction {
		protected CH() { super("CH", 0x51); }
		protected void execute(int regR, int addr) {
			int value = memory.readHalfWord(addr);
			int r = currentRegisters[regR];
			cc &= 0x8;
			if (r < value) {
				cc |= 0x1;
			} else if (r > value) {
				cc |= 0x2;
			}
			if ((r & value) != 0) {
				cc |= 0x4;
			}
		}
	}

	// LH operation .52
	protected class LH extends HalfWordIndexedInstruction {
		protected LH() { super("LH", 0x52); }
		protected void execute(int regR, int addr) {
			int value = memory.readHalfWord(addr);
			currentRegisters[regR] = value;
			cc &= 0xc;
			if (value < 0) {
				cc |= 0x01;
			} else if (value > 0) {
				cc |= 0x02;
			}
		}
	}

	// MTH operation .53
	protected class MTH extends HalfWordIndexedInstruction implements
		InterruptInstruction {	//MTH=53 added 11/22/02 KGC

		protected int loc;
		protected boolean inTrap;

		protected MTH() { super("MTH", 0x53); loc = 0; }
		public void setLocation(int loc) { this.loc = loc; inTrap = false; }

		public void setInTrap(boolean inTrap) {
			this.inTrap = inTrap;
		}

		protected void execute(int regR, int addr) {
			int value = memory.readHalfWord(addr);
			int localCC = 0;
			if (regR == 0) {
				if (value < 0) {
					localCC |= 0x1;
				} else if (value > 0) {
					localCC |= 0x2;
				}
			} else {
				if ((regR & 0x8) != 0) {
					regR |= 0xfff0;
				}
				int a = value & 0xffff;
				int b = regR;
				int result = a + b;
				memory.writeHalfWord(addr, result);
				if ((result & 0x8000) != 0) {
					localCC |= 0x1;
				} else if ((result & 0x7fff) != 0) {
					localCC |= 0x2;
				}
				int a0 = a & 0x8000;
				int b0 = b & 0x8000;
				int c0 = result & 0x8000;
				if (((~(a0 ^ b0)) & (c0 ^ a0)) != 0) {
					localCC |= 0x4;
				}
				if ((result & 0xf0000) != 0) {
					localCC |= 0x8;
				}
			}
			if (!inTrap) {
				cc = localCC;	// not in interrupt
				if (am && (cc & 0x4) != 0) {
					trap(0x43);
				}
			} else {
				clearInterrupt(loc);
				if ((localCC & 0x3) == 0) {
					interrupt(loc + 6);
				}
			}
		}
	}

	// ?? operation .54

	// STH operation .55
	protected class STH extends HalfWordIndexedInstruction {
		protected STH() { super("STH", 0x55); }
		protected void execute(int regR, int addr) {
			int value = currentRegisters[regR];
			memory.writeHalfWord(addr, value);
			cc &= 0xb;
			value >>= 15;
			if (value != 0 && value != -1) {
				cc |= 4;
			}
		}
	}

	// DH operation .56
	protected class DH extends HalfWordIndexedInstruction {
		protected DH() { super("DH", 0x56); }
		protected void execute(int regR, int addr) {
			int den = memory.readHalfWord(addr);
			cc &= 0xb;
			if (den == 0) {
				cc |= 0x4;
				if (am) {
					trap(0x43);
				}
				return;
			}
			long num = currentRegisters[regR];
			long quotient = num / den;
			int hi = (int) (quotient >>> 32);
			int lo = (int) quotient;
			if (hi > 0 || hi < -1 || (hi == -1 && lo > 0) || (hi == 0 && lo < 0) ||
				(lo == 0x80000000)) {
				cc |= 0x4;
				if (am) {
					trap(0x43);
				}
				return;
			}
			int value = currentRegisters[regR] = (int) quotient;
			cc &= 0xc;
			if (value < 0) {
				cc |= 0x1;
			} else if (value > 0) {
				cc |= 0x2;
			}
		}
	}

	// MH operation .57
	protected class MH extends HalfWordIndexedInstruction {
		protected MH() { super("MH", 0x57); }
		protected void execute(int regR, int addr) {
			int a = memory.readHalfWord(addr);
			int b = currentRegisters[regR] & 0xffff;
			b <<= 16; b >>= 16;
			int result = currentRegisters[regR | 1] = a * b;
			cc &= 0xc;
			if (result < 0) {
				cc |= 0x01;
			} else if (result > 0) {
				cc |= 0x02;
			}
		}
	}

	// SH operation .58
	protected class SH extends HalfWordIndexedInstruction {
		protected SH() { super("SH", 0x58); }
		protected void execute(int regR, int addr) {
			int a = -memory.readHalfWord(addr);
			int b = currentRegisters[regR];

			int result = currentRegisters[regR] += a;
			cc = 0;
			if (result < 0) {
				cc |= 0x1;
			} else if (result > 0) {
				cc |= 0x2;
			}
			int a0 = a & 0x80000000;
			int b0 = b & 0x80000000;
			int c0 = result & 0x80000000;
			if ((a != -b) && ((~(a0 ^ b0)) & (c0 ^ a0)) != 0) {
				cc |= 0x4;
			}
			if ((a0 != 0 || b0 != 0) && ((a0 != 0 && b0 != 0) ||
				((a & 0x7fffffff) + (b & 0x7fffffff) < 0)) ||
				a == 0) {
				cc |= 0x8;
			}
			if (am && (cc & 0x4) != 0) {
				trap(0x43);
			}
		}
	}

	// ?? operation .59

	// LCH operation .5A
	protected class LCH extends HalfWordIndexedInstruction {
		protected LCH() { super("LCH", 0x5A); }
		protected void execute(int regR, int addr) {
			int value = memory.readHalfWord(addr);
			int result = currentRegisters[regR] = -value;
			cc &= 0xc;
			if (result < 0) {
				cc |= 0x1;
			} else if (result > 0) {
				cc |= 0x2;
			}
		}
	}

	// LAH operation .5B
	protected class LAH extends HalfWordIndexedInstruction {
		protected LAH() { super("LAH", 0x5B); }
		protected void execute(int regR, int addr) {
			int value = memory.readHalfWord(addr);
			int result;
			if (value >= 0) {
				result = currentRegisters[regR] = value;
			} else {
				result = currentRegisters[regR] = -value;
			}
			cc &= 0xc;
			if (result != 0) {
				cc |= 0x2;
			}
		}
	}

	// ?? operation .5C
	// ?? operation .5D
	// ?? operation .5E
	// ?? operation .5F

	// CBS operation .60
	protected class CBS extends Instruction {
		protected CBS() { super("CBS", 0x60); }
		protected void execute(int iWord) {
			if (iWord < 0) {trap40(NONEXISTENT_INSTRUCTION);} else {
				int regR = (iWord >>> 20) & 0x0f;
				int disp = iWord & 0xfffff;
				disp <<= 12; disp >>= 12;    // sign extend
				int bs=-1; int bd=-1; int i=0;
				if (regR != 0) {
					int rVal = currentRegisters[regR];
					int r1Val = currentRegisters[regR | 1];
					int src = rVal & 0x7ffff;
					int dst = r1Val & 0x7ffff;
					int count = (r1Val >> 24) & 0xff;
					for (i=0; (i<count & (bs == bd)); i+=1) {
						bs = memory.readByte(disp + src++) & 0xff;
						bd = memory.readByte(dst++) & 0xff;
					}
					if (bs != bd) {
						dst--; src--; i--;
					}
					currentRegisters[regR] &= 0xfff80000;
					currentRegisters[regR] |= src;
					currentRegisters[regR | 1] &= 0x00f80000;
					currentRegisters[regR | 1] |= (dst | ((count-i) << 24));
				} else {
					int r1Val = currentRegisters[1];
					int dst = r1Val & 0x7ffff;
					int count = (r1Val >> 24) & 0xff;
					bs = memory.readByte(disp) & 0xff; bd=bs;
					for (i=0; (i<count &  (bs == bd)); i+=1) {
						bd = memory.readByte(dst++) & 0xff;
					}
					if (bs != bd) {
						dst--; i--;
					}
					currentRegisters[1] &= 0x00f80000;
					currentRegisters[1] |= (dst | ((count-i) << 24));
				}
				cc &= 0xc;
				if (bs < bd) cc |= 0x1;
				if (bs > bd) cc |= 0x2;
			}
		}
	}

	// MBS operation .61
	protected class MBS extends Instruction {
		protected MBS() { super("MBS", 0x61); }
		protected void execute(int iWord) {
			if (iWord < 0) {
				trap40(NONEXISTENT_INSTRUCTION);
			} else {
				int regR = (iWord >>> 20) & 0x0f;
				int disp = iWord & 0xfffff;
				disp <<= 12;
				disp >>= 12;	// sign extend

				if (regR != 0) {
					int rVal = currentRegisters[regR];
					int r1Val = currentRegisters[regR | 1];
					int src = rVal & 0x7ffff;
					int dst = r1Val & 0x7ffff;
					int count = (r1Val >> 24) & 0xff;
					for (int i=0; i<count; i+=1) {
						int b = memory.readByte(disp + src++);
						memory.writeByte(dst++, b);
					}
					currentRegisters[regR] &= 0xfff80000;
					currentRegisters[regR] |= src;
					currentRegisters[regR | 1] &= 0x00f80000;
					currentRegisters[regR | 1] |= dst;
				} else {
					int r1Val = currentRegisters[1];
					int dst = r1Val & 0x7ffff;
					int count = (r1Val >> 24) & 0xff;
					int b = memory.readByte(disp);
					for (int i=0; i<count; i+=1) {
						memory.writeByte(dst++, b);
					}
					currentRegisters[1] &= 0x00f80000;
					currentRegisters[1] |= dst;
				}
			}
		}
	}

	// ?? operation .62

	// EBS operation .63
	protected class EBS extends Instruction {
		protected EBS() { super("EBS", 0x63); }
		protected void execute(int iWord) {
			trap(0x41);
		}
	}

	// BDR operation .64
	protected class BDR extends WordIndexedInstruction {
		protected BDR() { super("BDR", 0x64); }
		protected void execute(int regR, int addr) {
			int value = currentRegisters[regR];
			value -= 1;
			currentRegisters[regR] = value;
			if (value > 0) {
				if (addr == ia-1) {
					// System.out.println("BDR loop, value = " + value);
				}
				setIA(addr);
			}
		}
	}

	// BIR operation .65
	protected class BIR extends WordIndexedInstruction {
		protected BIR() { super("BIR", 0x65); }
		protected void execute(int regR, int addr) {
			int value = currentRegisters[regR];
			value += 1;
			currentRegisters[regR] = value;
			if (value < 0) {
				setIA(addr);
			}
		}
	}

	// AWM operation .66
	protected class AWM extends WordIndexedInstruction {
		protected AWM() { super("AWM", 0x66); }
		protected void execute(int regR, int addr) {
			int a = memory.readWord(addr);
			int b = currentRegisters[regR];

			int result = a + b;
			memory.writeWord(addr, result);
			cc = 0;
			if (result < 0) {
				cc |= 0x1;
			} else if (result > 0) {
				cc |= 0x2;
			}
			int a0 = a & 0x80000000;
			int b0 = b & 0x80000000;
			int c0 = result & 0x80000000;
			if (((~(a0 ^ b0)) & (c0 ^ a0)) != 0) {
				cc |= 0x4;
			}
			if ((a0 != 0 || b0 != 0) && ((a0 != 0 && b0 != 0) ||
				((a & 0x7fffffff) + (b & 0x7fffffff) < 0))) {
				cc |= 0x8;
			}
			if (am && (cc & 0x4) != 0) {
				trap(0x43);
			}
		}
	}

	// EXU operation .67
	protected class EXU extends WordIndexedInstruction {
		protected EXU() { super("EXU", 0x67); }
		protected void execute(int regR, int addr) {
			// This assumes no pathological cases!
			executeOne(memory.fetchInstruction(addr));
		}
	}

	// BCR operation .68
	protected class BCR extends WordIndexedInstruction {
		protected BCR() { super("BCR", 0x68); }
		protected void execute(int regR, int addr) {
			if ((regR & cc) == 0) {
				setIA(addr);
			}
		}
	}

	// BCS operation .69
	protected class BCS extends WordIndexedInstruction {
		protected BCS() { super("BCS", 0x69); }
		protected void execute(int regR, int addr) {
			if ((regR & cc) != 0) {
				setIA(addr);
			}
		}
	}

	// BAL operation .6A
	protected class BAL extends WordIndexedInstruction {
		protected BAL() { super("BAL", 0x6A); }
		protected void execute(int regR, int addr) {
			currentRegisters[regR] = ia;
			setIA(addr);
		}
	}

	// INT operation .6B
	protected class INT extends WordIndexedInstruction {
		protected INT() { super("INT", 0x6B); }
		protected void execute(int regR, int addr) {
			int value = memory.readWord(addr);
			cc = value >>> 28;
			currentRegisters[regR] = (value >>> 16) & 0x0fff;
			currentRegisters[regR | 1] = value & 0x0ffff;
		}
	}

	// RD operation .6C
	protected class RD extends PrivelegedWordIndexedInstruction {
		protected RD() { super("RD", 0x6C); }
		protected void execute(int regR, int addr) {
			addr &= 0xffff;
			if (addr == 0) {	// read sense switches
				cc = pcp.getSenseSwitches();
			} else if (addr == 0x0010) {
				if (regR != 0) {	// read/reset mem fault
					currentRegisters[regR] = 0;
				}
				cc = pcp.getSenseSwitches();
			} else {
				throw new IllegalArgumentException("RD undefined mode/function: ." +
					Integer.toHexString(addr).toUpperCase());
			}
		}
	}

	// WD operation .6D
	protected class WD extends PrivelegedWordIndexedInstruction {
		protected WD() { super("WD", 0x6D); }
		protected void execute(int regR, int addr) {
			addr &= 0xffff;
			if ((addr & 0xf8f0) == 0x1000) {
				int code = (addr >>> 8) & 0x7;
				int group = addr & 0xf;
				int value = currentRegisters[regR];
				switch (code) {
					case 0:	// Undefined
					throw new IllegalArgumentException("WD undefined code");
					// break;

					case 1:	// disarm selected levels
					if (group == 0) {
						int iMask = 0x8000;
						int baseLoc = 0x52;
						for (int i=0; i<12; i+=1) {
							if ((value & iMask) != 0) {
								interruptArmed[baseLoc + i] = false;
								interruptWaiting[baseLoc + i] = false;
								interruptActive[baseLoc + i] = false;
							}
							iMask >>>= 1;
						}
					} else if (group >= 2) {
						int iMask = 0x8000;
						int baseLoc = ((group-2) << 4) + 0x60;
						for (int i=0; i<16; i+=1) {
							if ((value & iMask) != 0) {
								interruptArmed[baseLoc + i] = false;
								interruptWaiting[baseLoc + i] = false;
								interruptActive[baseLoc + i] = false;
							}
							iMask >>>= 1;
						}
					}
					checkInterrupts();
					break;

					case 2:	// arm & enable selected levels
					if (group == 0) {
						int iMask = 0x8000;
						int baseLoc = 0x52;
						for (int i=0; i<12; i+=1) {
							if ((value & iMask) != 0) {
								interruptArmed[baseLoc + i] = true;
								interruptEnabled[baseLoc + i] = true;
								interruptWaiting[baseLoc + i] = false;
								interruptActive[baseLoc + i] = false;
							}
							iMask >>>= 1;
						}
					} else if (group >= 2) {
						int iMask = 0x8000;
						int baseLoc = ((group-2) << 4) + 0x60;
						for (int i=0; i<16; i+=1) {
							if ((value & iMask) != 0) {
								interruptArmed[baseLoc + i] = true;
								interruptEnabled[baseLoc + i] = true;
								interruptWaiting[baseLoc + i] = false;
								interruptActive[baseLoc + i] = false;
							}
							iMask >>>= 1;
						}
					}
					checkInterrupts();
					break;

					case 3:	// arm & disable selected levels
					if (group == 0) {
						int iMask = 0x8000;
						int baseLoc = 0x52;
						for (int i=0; i<12; i+=1) {
							if ((value & iMask) != 0) {
								interruptArmed[baseLoc + i] = true;
								interruptEnabled[baseLoc + i] = false;
								interruptWaiting[baseLoc + i] = false;
								interruptActive[baseLoc + i] = false;
							}
							iMask >>>= 1;
						}
					} else if (group >= 2) {
						int iMask = 0x8000;
						int baseLoc = ((group-2) << 4) + 0x60;
						for (int i=0; i<16; i+=1) {
							if ((value & iMask) != 0) {
								interruptArmed[baseLoc + i] = true;
								interruptEnabled[baseLoc + i] = false;
								interruptWaiting[baseLoc + i] = false;
								interruptActive[baseLoc + i] = false;
							}
							iMask >>>= 1;
						}
					}
					checkInterrupts();
					break;

					case 4:	// enable selected levels
					if (group == 0) {
						int iMask = 0x8000;
						int baseLoc = 0x52;
						for (int i=0; i<12; i+=1) {
							if ((value & iMask) != 0) {
								interruptEnabled[baseLoc + i] = true;
							}
							iMask >>>= 1;
						}
					} else if (group >= 2) {
						int iMask = 0x8000;
						int baseLoc = ((group-2) << 4) + 0x60;
						for (int i=0; i<16; i+=1) {
							if ((value & iMask) != 0) {
								interruptEnabled[baseLoc + i] = true;
							}
							iMask >>>= 1;
						}
					}
					checkInterrupts();
					break;

					case 5:	// disable selected levels
					if (group == 0) {
						int iMask = 0x8000;
						int baseLoc = 0x52;
						for (int i=0; i<12; i+=1) {
							if ((value & iMask) != 0) {
								interruptEnabled[baseLoc + i] = false;
							}
							iMask >>>= 1;
						}
					} else if (group >= 2) {
						int iMask = 0x8000;
						int baseLoc = ((group-2) << 4) + 0x60;
						for (int i=0; i<16; i+=1) {
							if ((value & iMask) != 0) {
								interruptEnabled[baseLoc + i] = false;
							}
							iMask >>>= 1;
						}
					}
					checkInterrupts();
					break;

					case 6:	// enable all 1's, disable all 0's
					if (group == 0) {
						int iMask = 0x8000;
						int baseLoc = 0x52;
						for (int i=0; i<12; i+=1) {
							interruptEnabled[baseLoc + i] = (value & iMask) != 0;
							iMask >>>= 1;
						}
					} else if (group >= 2) {
						int iMask = 0x8000;
						int baseLoc = ((group-2) << 4) + 0x60;
						for (int i=0; i<16; i+=1) {
							interruptEnabled[baseLoc + i] = (value & iMask) != 0;
							iMask >>>= 1;
						}
					}
					checkInterrupts();
					break;

					case 7:	// Trigger selected interrupts
					if (group == 0) {
						int iMask = 0x8000;
						int baseLoc = 0x52;
						for (int i=0; i<12; i+=1) {
							if ((value & iMask) != 0) {
								interrupt(baseLoc + i);
							}
							iMask >>>= 1;
						}
					} else if (group >= 2) {
						int iMask = 0x8000;
						int baseLoc = ((group-2) << 4) + 0x60;
						for (int i=0; i<16; i+=1) {
							if ((value & iMask) != 0) {
								interrupt(baseLoc + i);
							}
							iMask >>>= 1;
						}
					}
					break;
				}
			} else if ((addr & 0xfff8) == 0x0030) {	// Set int. inhibits
				ci = ci || ((addr & 0x4) != 0);
				ii = ii || ((addr & 0x2) != 0);
				ei = ii || ((addr & 0x1) != 0);
			} else if ((addr & 0xfff8) == 0x0020) {	// Reset int. inhibits
				ci = ((addr & 0x4) != 0) ? false : ci;
				ii = ((addr & 0x2) != 0) ? false : ii;
				ei = ((addr & 0x1) != 0) ? false : ei;
			} else if (addr  == 0x0040) {			// Reset alarm indicator
			} else if (addr  == 0x0041) {			// Set alarm indicator
				java.awt.Toolkit.getDefaultToolkit().beep();
			} else if (addr  == 0x0042) {			// Toggle PCF flip-flop
			} else if (addr  == 0x0045) {			// Clock margins
			} else {
				throw new IllegalArgumentException(
					"WD: addr = ." + Integer.toHexString(addr));
			}
		}
	}

	// AIO operation .6E
	protected class AIO extends PrivelegedWordIndexedInstruction {
		protected AIO() { super("AIO", 0x6E); }
		protected void execute(int regR, int addr) {
			int ioAddr = addr & 0x0700;
			if (ioAddr != 0) {
				throw new IllegalArgumentException("AIO: ioAddr not zero!");
			}
			cc &= 0x3;
			IOProcessor iop = iopMgr.getInterruptReqIOP();
			if (iop != null) {
				int status = iop.acknowledgeIO();
				if (regR != 0) {
					currentRegisters[regR] = status;
				}
			} else {
				cc |= 0xc;
			}
		}
	}

	// MMC operation .6F
	protected class MMC extends PrivelegedWordIndexedInstruction {
		protected MMC() { super("MMC", 0x6F); }
		protected void execute(int iWord) {
			if (ms) {
				trap40(PRIVELEGED_INSTRUCTION);
				return;
			}
			int regR = (iWord >>> 20) & 0x0f;
			int r = currentRegisters[regR];
			int ru1 = currentRegisters[regR | 1];
			int addr = r & 0x1ffff;
			int count = (ru1 >> 24) & 0xff;
			if (count == 0) {
				count = 256;
			}
			if ((iWord & 0x00080000) != 0) { // load map
				int page = (ru1 >> 9) & 0xff;
				memory.loadMemoryMap(addr, count, page);
				addr += count;
				page += count << 2;
				r &= 0xfffe0000;
				r |= addr & 0x1ffff;
				ru1 &= 0x00fe01ff;
				ru1 |= (page & 0xff) << 9;
				currentRegisters[regR] = r;
				currentRegisters[regR | 1] = ru1;
			} else if ((iWord & 0x00040000) != 0) { // load access protection
				int page = (ru1 >> 9) & 0xfc;
				memory.loadAccessProtection(addr, count, page);
				addr += count;
				page += count << 4;
				r &= 0xfffe0000;
				r |= addr & 0x1ffff;
				ru1 &= 0x00fe07ff;
				ru1 |= (page & 0xfc) << 9;
				currentRegisters[regR] = r;
				currentRegisters[regR | 1] = ru1;
			} else if ((iWord & 0x00020000) != 0) { // load write locks
				int page = (ru1 >> 9) & 0xfc;
				memory.loadWriteLocks(addr, count, page);
				addr += count;
				page += count << 4;
				r &= 0xfffe0000;
				r |= addr & 0x1ffff;
				ru1 &= 0x00fe07ff;
				ru1 |= (page & 0xfc) << 9;
				currentRegisters[regR] = r;
				currentRegisters[regR | 1] = ru1;
			}
		}

		protected void execute(int regR, int addr) {
		}
	}

	// LCF operation .70
	protected class LCF extends ByteIndexedInstruction {
		protected LCF() { super("LCF", 0x70); }
		protected void execute(int regR, int addr) {
			int value0 = memory.readByte(addr) & 0xff;
			if ((regR & 0x2) != 0) {
				cc = value0 >>> 4;
			}
			if ((regR & 0x1) != 0) {
				fs = (value0 & 0x04) != 0;
				fz = (value0 & 0x02) != 0;
				fn = (value0 & 0x01) != 0;
			}
		}
	}

	// CB operation .71
	protected class CB extends ByteIndexedInstruction {
		protected CB() { super("CB", 0x71); }
		protected void execute(int regR, int addr) {
			int value = memory.readByte(addr) & 0xff;
			int r = currentRegisters[regR] & 0xff;
			cc &= 0x8;
			if (r < value) {
				cc |= 0x1;
			} else if (r > value) {
				cc |= 0x2;
			}
			if ((r & value) != 0) {
				cc |= 0x4;
			}
		}
	}

	// LB operation .72
	protected class LB extends ByteIndexedInstruction {
		protected LB() { super("LB", 0x72); }
		protected void execute(int regR, int addr) {
			int value = memory.readByte(addr);
			currentRegisters[regR] = value & 0xff;
			cc &= 0xc;
			if (value != 0) {
				cc |= 0x2;
			}
		}
	}

	// MTB operation .73
	protected class MTB extends ByteIndexedInstruction implements
		InterruptInstruction {

		protected int loc;
		protected boolean inTrap;

		protected MTB() { super("MTB", 0x73); loc = 0; inTrap = false; }
		public void setLocation(int loc) { this.loc = loc; }

		public void setInTrap(boolean inTrap) {
			this.inTrap = inTrap;
		}

		protected void execute(int regR, int addr) {
			int value = memory.readByte(addr);
			int localCC = 0;
			if (regR == 0) {
				if (value != 0) {
					localCC |= 0x2;
				}
			} else {
				if ((regR & 0x8) != 0) {
					regR |= 0xf0;
				}
				int a = value & 0xff;
				int b = regR;
				int result = a + b;
				memory.writeByte(addr, result);
				if ((result & 0xff) != 0) {
					localCC |= 0x2;
				}
				if ((result & 0xf00) != 0) {
					localCC |= 0x8;
				}
			}
			if (!inTrap) {
				cc = localCC;	// not in interrupt
			} else {
				clearInterrupt(loc);
				if ((localCC & 0x3) == 0) {
					interrupt(loc + 6);
				}
			}
		}
	}

	// STFC operation .74
	protected class STFC extends ByteIndexedInstruction {
		protected STFC() { super("STFC", 0x74); }
		protected void execute(int regR, int addr) {
			int value = cc << 4;
			value |= fs ? 4 : 0;
			value |= fz ? 2 : 0;
			value |= fn ? 1 : 0;
			memory.writeByte(addr, value);
		}
	}

	// STB operation .75
	protected class STB extends ByteIndexedInstruction {
		protected STB() { super("STB", 0x75); }
		protected void execute(int regR, int addr) {
			memory.writeByte(addr, currentRegisters[regR]);
		}
	}

	// PACK operation .76
	// UNPK operation .77
	// DS operation .78
	// DA operation .79
	// DD operation .7A
	// DM operation .7B
	// DSA operation .7C
	// DC operation .7D
	// DL operation .7E
	protected class DL extends ByteIndexedInstruction {
		protected int[] dp;
		protected DL() { super("DL", 0x7E); dp = new int[16]; }
		protected void execute(int regR, int addr) {
			int n = dp.length;
			for (int i=0; i<n; i+=1) {
				dp[i] = 0;
			}
			int r = ((regR - 1) & 0x0f) + 1;  // map 0 to 16
			cc &= 0x3; int s=2;
			for (int i=r; i>=1; i--) {
				dp[15+i-r] = memory.readByte(addr+i-1) & 0xff;
			}
			for (int i=0; i<15; i++) {
				if (((dp[i]>>4) > 9) | ((dp[i]&0xf) > 9)) {
					cc |= 0x8;
				}
			}
			if (((dp[15]>>4) > 9) | ((dp[15] & 0xf) < 0xa)) {
				cc |= 0x8;
			}
			if ((cc & 0x8) != 0) {
				if (dm) trap(0x45);
				return;
			}
			for (int i=12; i<16; i++) {
				currentRegisters[i] = 0;
			}
			for (int i=0; i<16; i+=1) {
				currentRegisters[12+(i>>2)] |= (dp[i] << (3-(i&0x3))*8);
			}
			if (((dp[15] & 0xf) == 0xb) | ((dp[15] & 0xf) == 0xd)) {
				s = 1;
			}
			if ((currentRegisters[12] == 0) & (currentRegisters[13] == 0) &
				(currentRegisters[14] == 0) &
				((currentRegisters[15] & 0xfffffff0) == 0)) {
				s = 0;
			}
			currentRegisters[15] = (currentRegisters[15] & 0xfffffff0) | 0xc;
			if (s == 1) {
				currentRegisters[15] |= 1;
			}
			cc|=s;
		}
	}

	// DST operation .7F
	protected class DST extends ByteIndexedInstruction {
		protected int[] dp;
		protected DST() { super("DST", 0x7F); dp = new int[16]; }
		protected void execute(int regR, int addr) {
			int n = dp.length;
			for (int i=0; i<n; i+=1) {
				dp[i] = 0;
			}
			int r = ((regR - 1) & 0x0f) + 1;  // map 0 to 16
			cc &= 0x3; int s=2;
			for (int i=0; i<16; i++) {
				dp[i] = (currentRegisters[12+(i>>2)] >>> (3-(i&0x3))*8) & 0xff;
			}
			for (int i=0; i<15; i++) {
				if (((dp[i]>>4) > 9) | ((dp[i]&0xf) > 9)) {
					cc |= 0x8;
				}
			}
			if (((dp[15]>>4) > 9) | ((dp[15] & 0xf) < 0xa)) {
				cc |= 0x8;
			}
			if ((cc & 0x8) != 0) {
				if (dm) trap(0x45);
				return;
			}
			if ((currentRegisters[12] == 0) & (currentRegisters[13] == 0) &
				(currentRegisters[14] == 0) &
				((currentRegisters[15] & 0xfffffff0) == 0)) {
				s = 0;
			}
			if (s != 0) {
				if (((dp[15] & 0xf) == 0xb) | ((dp[15] & 0xf) == 0xd)) {
					s = 1;
				}
			}
			if (s != 0) {
				dp[15] = (dp[15] & 0xfffffff0) | 0xc;
			}
			if (s==1) {
				dp[15] |= 1;
			}
			for (int i=r; i>=1; i--) {
				memory.writeByte(addr+i-1, dp[15+i-r] );
			}
			for (int i=0; 16-i>r; i++) {
				if (dp[i] != 0) cc|=4;
			}
		}
	}

	protected abstract class Instruction {
		protected String name;
		protected int code;

		protected Instruction(String name, int code) {
			this.name = name;
			this.code = code;
		}

		protected String getName() {
			return name;
		}

		protected int getCode() {
			return code;
		}

		protected abstract void execute(int iWord);
	}

	protected class NonExistentInstruction extends Instruction {
		protected boolean priveleged;

		protected NonExistentInstruction(String name, int code,
			boolean priveleged) {
			super(name, code);
			this.priveleged = priveleged;
		}

		protected NonExistentInstruction(String name, int code) {
			this(name, code, false);
		}

		protected NonExistentInstruction(int code, boolean priveleged) {
			this("?." + Integer.toHexString(code).toUpperCase(), code, priveleged);
		}

		protected boolean isPriveleged() {
			return priveleged;
		}

		protected void execute(int iWord) {
			if (priveleged && ms) {
				trap40(NONEXISTENT_INSTRUCTION | PRIVELEGED_INSTRUCTION);
			} else {
				trap40(NONEXISTENT_INSTRUCTION);
			}
		}
	}

	protected class UnimplementedInstruction extends Instruction {
		protected UnimplementedInstruction(String name, int code) {
			super(name, code);
		}

		protected void execute(int iWord) {
			trap(0x41);
		}
	}

	protected abstract class ImmediateInstruction extends Instruction {
		protected ImmediateInstruction(String name, int code) {
			super(name, code);
		}

		protected void execute(int iWord) {
			if (iWord < 0) {
				trap40(NONEXISTENT_INSTRUCTION);
				return;
			}
			int regR = (iWord >>> 20) & 0x0f;
			int value = iWord & 0xfffff;
			value <<= 12;
			value >>= 12;	// sign extend
			execute(regR, value);
		}

		protected abstract void execute(int regR, int value);
	}

	protected abstract class ByteIndexedInstruction extends Instruction {
		protected ByteIndexedInstruction(String name, int code) {
			super(name, code);
		}

		protected void execute(int iWord) {
			int regR = (iWord >>> 20) & 0x0f;
			int regX = (iWord >>> 17) & 0x07;
			int addr = iWord & 0x1ffff;

			if (iWord < 0) {
				addr = memory.readWord(addr) & 0x1ffff;
			}
			addr <<= 2;
			if (regX != 0) {
				addr += currentRegisters[regX];
			}
			execute(regR, addr);
		}

		protected abstract void execute(int regR, int addr);
	}

	protected abstract class HalfWordIndexedInstruction extends Instruction {
		protected HalfWordIndexedInstruction(String name, int code) {
			super(name, code);
		}

		protected void execute(int iWord) {
			int regR = (iWord >>> 20) & 0x0f;
			int regX = (iWord >>> 17) & 0x07;
			int addr = iWord & 0x1ffff;

			if (iWord < 0) {
				addr = memory.readWord(addr) & 0x1ffff;
			}
			addr <<= 1;
			if (regX != 0) {
				addr += currentRegisters[regX];
			}
			execute(regR, addr);
		}

		protected abstract void execute(int regR, int addr);
	}

	protected abstract class WordIndexedInstruction extends Instruction {
		protected WordIndexedInstruction(String name, int code) {
			super(name, code);
		}

		protected void execute(int iWord) {
			int regR = (iWord >>> 20) & 0x0f;
			int regX = (iWord >>> 17) & 0x07;
			int addr = iWord & 0x1ffff;

			if (iWord < 0) {
				addr = memory.readWord(addr) & 0x1ffff;
			}
			if (regX != 0) {
				addr += currentRegisters[regX];
			}
			execute(regR, addr);
		}

		protected abstract void execute(int regR, int addr);
	}

	protected abstract class PrivelegedWordIndexedInstruction extends WordIndexedInstruction {
		protected PrivelegedWordIndexedInstruction(String name, int code) {
			super(name, code);
		}

		protected void execute(int iWord) {
			if (ms) {
				trap40(PRIVELEGED_INSTRUCTION);
			} else {
				super.execute(iWord);
			}
		}

		protected abstract void execute(int regR, int addr);
	}

	protected abstract class DoubleWordIndexedInstruction extends Instruction {
		protected DoubleWordIndexedInstruction(String name, int code) {
			super(name, code);
		}

		protected void execute(int iWord) {
			int regR = (iWord >>> 20) & 0x0f;
			int regX = (iWord >>> 17) & 0x07;
			int addr = iWord & 0x1ffff;

			if (iWord < 0) {
				addr = memory.readWord(addr) & 0x1ffff;
			}
			addr &= 0xfffffffe;
			if (regX != 0) {
				addr += currentRegisters[regX] << 1;
			}
			execute(regR, addr);
		}

		protected abstract void execute(int regR, int addr);
	}

	protected abstract class PrivelegedDoubleWordIndexedInstruction extends DoubleWordIndexedInstruction {
		protected PrivelegedDoubleWordIndexedInstruction(String name, int code) {
			super(name, code);
		}

		protected void execute(int iWord) {
			if (ms) {
				trap40(PRIVELEGED_INSTRUCTION);
			} else {
				super.execute(iWord);
			}
		}

		protected abstract void execute(int regR, int addr);
	}

	interface InterruptInstruction {
		void setLocation(int loc);
		void setInTrap(boolean inTrap);
	}
}
