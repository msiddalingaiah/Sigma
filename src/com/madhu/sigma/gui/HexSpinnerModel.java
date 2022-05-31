
package com.madhu.sigma.gui;

import javax.swing.AbstractSpinnerModel;

/**
 * Spinner for hex digits
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class HexSpinnerModel extends AbstractSpinnerModel {
	public static final int DISPLAY_HEX = 0;
	public static final int DISPLAY_DEC = 1;

	protected int displayMode;
	protected int min;
	protected int max;
	protected int value;

	public HexSpinnerModel(int displayMode, int min, int max, int value) {
		this.displayMode = displayMode;
		this.min = min;
		this.max = max;
		this.value = value;
		init();
	}

	public HexSpinnerModel(int displayMode, int value) {
		this(displayMode, 0, 0x7fffffff, value);
	}

	public HexSpinnerModel() {
		this(DISPLAY_HEX, 0);
	}

	protected void init() {
	}

	public void setDisplayMode(int mode) {
		displayMode = mode;
	}

	public int getDisplayMode() {
		return displayMode;
	}

	public int getInteger() {
		return value;
	}

	public void setInteger(int value) {
		if (this.value != value) {
			this.value = value;
			fireStateChanged();
		}
	}

	public Object getNextValue() {
		int value = this.value;
		value += 1;
		if (value > max) {
			return null;
		}
		return getValue(value);
	}

	public Object getPreviousValue() {
		int value = this.value;
		value -= 1;
		if (value < min) {
			return null;
		}
		return getValue(value);
	}

	public Object getValue() {
		return getValue(value);
	}

	public Object getValue(int value) {
		switch(displayMode) {
			case DISPLAY_HEX:
			default:
			return '.' + Integer.toHexString(value).toUpperCase();

			case DISPLAY_DEC:
			return Integer.toString(value);
		}
	}

	public void setValue(Object value) {
		String s = (String) value;
		int iv;
		if (s.charAt(0) == '.') {
			iv = Integer.parseInt(s.substring(1), 16);
		} else {
			iv = Integer.parseInt(s);
		}
		if (iv != this.value) {
			this.value = iv;
			fireStateChanged();
		}
	}
}
