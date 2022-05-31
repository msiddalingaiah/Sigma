
package com.madhu.sigma.iop;

import com.madhu.sigma.MainMemory;
import com.madhu.sigma.cpu.SigmaCPU;

/**
 * Abstract base class for all IO processors (IOPs)
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public abstract class IOProcessor implements Runnable {
	public static final int ORDER_TYPE_WRITE = 1;
	public static final int ORDER_TYPE_READ = 2;
	public static final int ORDER_TYPE_CONTROL = 3;
	public static final int ORDER_TYPE_SENSE = 4;
	public static final int ORDER_TYPE_READ_BACKWARD = 6;

	public static final int FLAG_DC_MASK = 0x80;
	public static final int FLAG_IZC_MASK = 0x40;
	public static final int FLAG_CC_MASK = 0x20;
	public static final int FLAG_ICE_MASK = 0x10;
	public static final int FLAG_HTE_MASK = 0x08;
	public static final int FLAG_IUE_MASK = 0x04;
	public static final int FLAG_SIL_MASK = 0x02;
	public static final int FLAG_S_MASK = 0x01;

	protected String name;
	protected int unit;
	protected MainMemory memory;
	protected SigmaCPU cpu;
	protected int commandWordAddr;
	protected int command0, command1;
	protected boolean interruptPending;

	public IOProcessor() {
	}

	public void setName(String name) {
		this.name = name;
	}

	public void setUnit(int unit) {
		this.unit = unit;
	}

	public int getUnit() {
		return unit;
	}

	public void setCPU(SigmaCPU cpu) {
		this.cpu = cpu;
	}

	public void setMemory(MainMemory memory) {
		this.memory = memory;
	}

	protected void init(int dwCommandAddr) {
		commandWordAddr = dwCommandAddr << 1;
		nextCommand();
	}

	protected void nextCommand() {
		command0 = memory.readWord(commandWordAddr++);
		command1 = memory.readWord(commandWordAddr++);
	}

	protected int getOrder() {
		return command0 >>> 24;
	}

	protected int getOrderType() {
		int order = getOrder();
		if ((order & 0x03) != 0) {
			return order & 0x03;
		} else {
			return order & 0x0f;
		}
	}

	protected int getByteAddress() {
		return command0 & 0x0007ffff;
	}

	protected int getFlags() {
		return command1 >>> 24;
	}

	protected int getByteCount() {
		return command1 & 0xffff;
	}

	public int getCommandDWordAddr() {
		return commandWordAddr >> 1;
	}

	public String getName() {
		return name;
	}

	public boolean isInterruptPending() {
		return interruptPending;
	}

	protected void requestInterrupt() {
		interruptPending = true;
		cpu.interrupt(0x5C);
	}

	protected void resetInterruptReq() {
		interruptPending = false;
	}

	public int acknowledgeIO() {
		if (isInterruptPending()) {
			resetInterruptReq();
			return getAckStatus();
		} else {
			return 0;
		}
	}

	protected abstract void init(String[] params) throws Exception;
	public abstract void startIO(int dwCommandAddr);
	public abstract void testIO();
	public abstract void haltIO();
	protected abstract int getAckStatus();
	public abstract int testDevice();
	public abstract int getStatus();
	public abstract void reset();
}
