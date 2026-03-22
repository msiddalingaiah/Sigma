
package com.madhu.sigma;

/**
 * An exception for non-allowed operations
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class NonAllowedOperation extends TrapException {
	// This numbering is CRITICAL! Do not monkey with it!!
	public static final int NONEXISTENT_INSTRUCTION = 8;
	public static final int NONEXISTENT_MEMORY = 4;
	public static final int PRIVELEGED = 2;
	public static final int MEMORY_PROTECTION = 1;

	protected int reason;

	public NonAllowedOperation(int reason, String message) {
		super(0x40, message);
		this.reason = reason;
	}

	public NonAllowedOperation(int reason) {
		this(reason, "NonAllowedOperation");
	}

	public NonAllowedOperation() {
		this(0);
	}

	public void setReason(int reason) {
		this.reason = reason;
	}

	public int getReason() {
		return reason;
	}
}
