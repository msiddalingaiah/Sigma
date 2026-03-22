
package com.madhu.sigma;

/**
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class Util {
	public static String toHexString(int value, int nChars) {
		String hex = Integer.toHexString(value).toUpperCase();
		StringBuffer sb = new StringBuffer(nChars);
		int n = hex.length() + 1; // Don't forget the '.'
		for (int i=0; i<nChars-n; i++) {
			sb.append(' ');
		}
		sb.append('.');
		sb.append(hex);
		return sb.toString();
	}

	public static String toHexString(int value) {
		return Integer.toHexString(value).toUpperCase();
	}
}
