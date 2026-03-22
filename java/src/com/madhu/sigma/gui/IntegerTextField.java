
package com.madhu.sigma.gui;

import javax.swing.*;
import java.awt.*;

/**
 * A JTextField for decimal and hex integers
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class IntegerTextField extends JTextField {
	public static final int DISPLAY_HEX = 0;
	public static final int DISPLAY_DEC = 1;

	protected int displayMode;

	public IntegerTextField() {
		init();
	}

	public IntegerTextField(javax.swing.text.Document doc,
		String text, int columns) {
		super(doc, text, columns);
		init();
	}

	public IntegerTextField(int columns) {
		super(columns);
		init();
	}

	public IntegerTextField(String text) {
		super(text);
		init();
	}

	public IntegerTextField(String text, int columns) {
		super(text, columns);
		init();
	}

	protected void init() {
		Font monoFont = new Font("Monospaced", Font.PLAIN, 12);
		setFont(monoFont);
		displayMode = DISPLAY_HEX;
	}

	public void setDisplayMode(int mode) {
		displayMode = mode;
	}

	public int getDisplayMode() {
		return displayMode;
	}

	public int getInteger() {
		String s = getText();
		if (s == null || s.length() == 0) {
			return 0;
		}
		if (s.charAt(0) == '.') {
			s = s.substring(1);
			long lv = Long.parseLong(s, 16);
			return (int) (lv & 0x0FFFFFFFFL);
		}
		return Integer.parseInt(s);
	}

	public void setInteger(int value) {
		switch(displayMode) {
			case DISPLAY_HEX:
			String hex = Integer.toHexString(value).toUpperCase();
			setText('.' + hex);
			break;

			case DISPLAY_DEC:
			setText(Integer.toString(value));
			break;
		}
	}
}
