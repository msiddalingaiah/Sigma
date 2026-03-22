
package com.madhu.sigma;

/**
 * A trap exception containing the trap location
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class TrapException extends SigmaException {
	protected int location;

	public TrapException(int location, String message) {
		super(message);
		this.location = location;
	}

	public TrapException(int location) {
		this(location, "TrapException");
	}

	public TrapException() {
		this(0);
	}

	public void setLocation(int location) {
		this.location = location;
	}

	public int getLocation() {
		return location;
	}
}
