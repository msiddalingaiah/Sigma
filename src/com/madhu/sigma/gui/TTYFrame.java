
package com.madhu.sigma.gui;

import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Container;
import java.awt.Font;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.awt.event.KeyEvent;
import java.awt.event.KeyListener;
import java.awt.event.WindowEvent;
import java.awt.event.WindowListener;

import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JTextArea;

/**
 * A simple graphical teletype
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class TTYFrame extends JFrame implements
	ActionListener, WindowListener, KeyListener {

	protected JTextArea ttyTA;
	protected JLabel readLB;
	protected char[] lineChars;
	protected int lineIndex;
	protected boolean lineAvailable;

	public TTYFrame(String title) {
		setTitle(title);
		lineChars = new char[256];
		lineIndex = 0;
		lineAvailable = false;
		Container cp = getContentPane();
		cp.setLayout(new BorderLayout());
		JPanel north = new JPanel();
		readLB = new JLabel(" ");
		north.add(readLB);
		cp.add(north, BorderLayout.NORTH);
		ttyTA = new JTextArea(24, 80);
		JScrollPane jsp = new JScrollPane(ttyTA,
			JScrollPane.VERTICAL_SCROLLBAR_ALWAYS,
			JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);
		cp.add(jsp, BorderLayout.CENTER);
		Font monoFont = new Font("Monospaced", Font.BOLD, 12);
		ttyTA.setFont(monoFont);
		ttyTA.setForeground(Color.GREEN);
		ttyTA.setBackground(Color.BLACK);
		ttyTA.addKeyListener(this);
		pack();
	}

	public synchronized String readLine() {
		if (!lineAvailable) {
			try {
				// readLB.setText("READ");
				wait();
			} catch (InterruptedException e) {
			}
		}
		setAvailable(false);
		lineIndex = 0;
		String line = new String(lineChars);
		readLB.setText(" ");
		return line;
	}

	public void writeString(String s) {
		ttyTA.append(s);
	}

	public synchronized void reset() {
		setAvailable(false);
		lineIndex = 0;
	}

	protected synchronized void setAvailable(boolean avail) {
		lineAvailable = avail;
		notifyAll();
	}

	protected void addChar(char c) {
		if (c == '\n') {
			setAvailable(true);
		} else {
			if (lineIndex < lineChars.length) {
				lineChars[lineIndex++] = c;
			}
		}
	}

	public void keyPressed(KeyEvent e) { }
	public void keyReleased(KeyEvent e) { }

	public void keyTyped(KeyEvent e) {
		addChar(e.getKeyChar());
	}

	public void actionPerformed(ActionEvent e) {
	}

	public void windowActivated(WindowEvent e) { }
	public void windowClosed(WindowEvent e) { }
	public void windowClosing(WindowEvent e) { }
	public void windowDeactivated(WindowEvent e) { }
	public void windowDeiconified(WindowEvent e) { }
	public void windowIconified(WindowEvent e) { }
	public void windowOpened(WindowEvent e)  { }
}
