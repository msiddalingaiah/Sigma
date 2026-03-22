
package com.madhu.sigma;

/**
 * A generic Sigma exception
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class SigmaException extends RuntimeException {
	public SigmaException() {
		this("SigmaException");
	}

	public SigmaException(String message) {
		super(message);
	}
}
