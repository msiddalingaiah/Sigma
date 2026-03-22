
package com.madhu.sigma.cpu;

import com.madhu.sigma.*;

/**
 * A trace of instruction addresses, useful for debugging
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class IATracer {
	protected IATrace[] data;
	protected int readIndex;
	protected int writeIndex;
	protected int count;
	protected int size;

	public IATracer(int size) {
		this.size = size;
		data = new IATrace[size];
		for (int i=0; i<size; i+=1) {
			data[i] = new IATrace();
		}
		readIndex = 0;
		writeIndex = 0;
		count = 0;
	}

	public IATracer() {
		this(32);
	}

	public void reset() {
		readIndex = 0;
		writeIndex = 0;
		count = 0;
	}

	public void addTrace(int from, int iWord, int to) {
		IATrace iat = data[writeIndex++];
		writeIndex %= data.length;
		iat.setData(from, iWord, to);
		count += 1;
		if (count >= data.length) {
			readIndex = writeIndex;
			count = data.length;
		}
	}

	public IATrace read() {
		IATrace iat = data[readIndex++];
		readIndex %= data.length;
		count -= 1;
		return iat;
	}

	public String toString() {
		int n = getCount();
		StringBuffer sb = new StringBuffer(n * 20);
		for (int i=0; i<n; i+=1) {
			IATrace iat = read();
			sb.append(iat.toString());
			sb.append('\n');
		}
		return sb.toString();
	}

	public int getSize() {
		return size;
	}

	public int getCount() {
		return count;
	}
}

class IATrace {
	protected int from;
	protected int to;
	protected int iWord;
	protected static OpCode[] instArray = OpCode.getOpCodes();

	protected void setData(int from, int iWord, int to) {
		this.from = from;
		this.iWord = iWord;
		this.to = to;
	}

	public String toString() {
		int code = (iWord >>> 24) & 0x7f;
		OpCode inst = instArray[code];
		StringBuffer sb = new StringBuffer(40);
		sb.append(Disassembler.toHexString(from, 3, ' '));
		sb.append("  ");
		sb.append(inst.decode(iWord));
		int n = sb.length();
		for (int j=0; j<25-n; j+=1) {
			sb.append(' ');
		}
		sb.append(Disassembler.toHexString(to, 3, ' '));
		return sb.toString();
	}
}
