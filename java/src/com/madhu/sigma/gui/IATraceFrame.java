
package com.madhu.sigma.gui;

import java.awt.BorderLayout;
import java.awt.Container;
import java.awt.Font;
import java.awt.event.WindowEvent;
import java.awt.event.WindowListener;

import javax.swing.JFrame;
import javax.swing.JList;
import javax.swing.JScrollPane;

import com.madhu.sigma.cpu.IATracer;
import com.madhu.sigma.cpu.SigmaCPU;

/**
 * A JFrame for the Instruction Address (IA) trace
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class IATraceFrame extends JFrame implements
	WindowListener {

	protected SigmaCPU cpu;
	protected JList codeList;
	protected IATracer iaTracer;
	protected String[] lines;

	public IATraceFrame(String title, SigmaCPU cpu) {
		setTitle(title);
		this.cpu = cpu;
		this.iaTracer = cpu.getIATracer();
		lines = new String[iaTracer.getSize()];
		Container cp = getContentPane();
		cp.setLayout(new BorderLayout());

		Font monoFont = new Font("Monospaced", Font.PLAIN, 12);
		codeList = new JList();
		codeList.setFont(monoFont);
		codeList.setVisibleRowCount(16);
		codeList.setPrototypeCellValue(" . 26  ?.00,0   .0    ");

		JScrollPane jsp = new JScrollPane(codeList,
			JScrollPane.VERTICAL_SCROLLBAR_ALWAYS,
			JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);
		cp.add(jsp, BorderLayout.CENTER);

		addWindowListener(this);
		pack();
	}

	public void load() {
		int n = iaTracer.getCount();
		for (int i=0; i<n; i+=1) {
			Object trace = iaTracer.read();
			lines[i] = trace.toString();
		}
		for (int i=n; i<lines.length; i+=1) {
			lines[i] = "";
		}
		codeList.setListData(lines);
	}

	public void windowActivated(WindowEvent e) { }
	public void windowClosed(WindowEvent e) { }

	public void windowClosing(WindowEvent e) {
		setVisible(false);
	}

	public void windowDeactivated(WindowEvent e) { }
	public void windowDeiconified(WindowEvent e) { }
	public void windowIconified(WindowEvent e) { }
	public void windowOpened(WindowEvent e)  { }
}
