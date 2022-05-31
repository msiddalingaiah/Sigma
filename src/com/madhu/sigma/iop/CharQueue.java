
package com.madhu.sigma.iop;

/**
 * A simple character queue
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class CharQueue {
	protected char[] data;
	protected int readIndex;
	protected int writeIndex;
	protected int count;

	public CharQueue(int maxChars) {
		data = new char[maxChars];
		readIndex = 0;
		writeIndex = 0;
		count = 0;
	}

	public CharQueue() {
		this(256);
	}

	public synchronized void write(char c) {
		if (count < data.length) {
			data[writeIndex++] = c;
			writeIndex %= data.length;
			notifyAll();
		}
		// drop extra chars for now...
	}

	public synchronized char read() {
		while (count <= 0) {
			try {
				wait();
			} catch (InterruptedException e) {
			}
		}
		char c = data[readIndex++];
		readIndex %= data.length;
		return c;
	}
}
