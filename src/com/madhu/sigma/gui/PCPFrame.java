
package com.madhu.sigma.gui;

import java.awt.BorderLayout;
import java.awt.Container;
import java.awt.GridBagConstraints;
import java.awt.GridBagLayout;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.awt.event.WindowEvent;
import java.awt.event.WindowListener;
import java.io.FileInputStream;
import java.util.Observable;
import java.util.Observer;
import java.util.Properties;

import javax.swing.BorderFactory;
import javax.swing.JButton;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JMenu;
import javax.swing.JMenuBar;
import javax.swing.JMenuItem;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.SwingUtilities;
import javax.swing.border.Border;
import javax.swing.border.TitledBorder;

import com.madhu.sigma.SigmaComputer;
import com.madhu.sigma.cpu.SigmaCPU;
import com.madhu.sigma.sigma6.Sigma6Computer;

/**
 * Processor Control Panel (PCP) JFrame
 * This is the main class for the Sigma computer with graphical control panel
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class PCPFrame extends JFrame implements
	ActionListener, WindowListener, Observer, Runnable {

	protected SigmaComputer computer;
	protected SigmaCPU cpu;
	protected RegisterPanel regPanel;
	protected PSDPanel psdPanel;
	protected MemoryPanel codePanel;
	protected JButton resetBtn, loadBtn, stepBtn, runBtn;
	protected IntegerTextField unitTF;
	protected IntegerTextField breakPointTF;
	protected IntegerTextField breakCountTF;
	protected JMenuItem exitItem;
	protected JMenuItem iaItem;
	protected IATraceFrame iaFrame;

	public PCPFrame(String title, SigmaComputer computer) {
		setTitle(title);
		this.computer = computer;
		cpu = computer.getCPU();
		cpu.addStopObserver(this);
		Container cp = getContentPane();
		cp.setLayout(new BorderLayout());

		JPanel center = new JPanel();

		GridBagLayout gb = new GridBagLayout();
		GridBagConstraints gbc = new GridBagConstraints();

		center.setLayout(gb);

		gbc.fill = GridBagConstraints.BOTH;
		gbc.weightx = 1.0;
		gbc.weighty = 1.0;

		center.add(regPanel = new RegisterPanel(computer));
		gb.setConstraints(regPanel, gbc);

		center.add(psdPanel = new PSDPanel(computer));
		gb.setConstraints(psdPanel, gbc);
		computer.setPCP(psdPanel);

		center.add(codePanel = new MemoryPanel(computer));
		gbc.weightx = 1000.0;
		gb.setConstraints(codePanel, gbc);
		psdPanel.setMemoryPanel(codePanel);

		cp.add(center, BorderLayout.CENTER);

		JPanel south = new JPanel();
		Border etched = BorderFactory.createEtchedBorder();
		TitledBorder tb = BorderFactory.createTitledBorder(
				       etched, "Execute");
		south.setBorder(tb);

		south.add(resetBtn = new JButton("Reset"));
		south.add(new JLabel("Unit"));
		south.add(unitTF = new IntegerTextField(6));
		unitTF.setInteger(computer.getDefaultBootUnit());
		south.add(loadBtn = new JButton("Load"));
		south.add(stepBtn = new JButton("Step"));
		south.add(runBtn = new JButton("Run"));
		south.add(new JLabel("Break addr/inst"));
		south.add(breakPointTF = new IntegerTextField(10));
		south.add(new JLabel("Break count"));
		south.add(breakCountTF = new IntegerTextField(5));

		resetBtn.addActionListener(this);
		loadBtn.addActionListener(this);
		stepBtn.addActionListener(this);
		runBtn.addActionListener(this);

		cp.add(south, BorderLayout.SOUTH);

		JMenuBar mb = new JMenuBar();
		JMenu fm = new JMenu("File");
		JMenuItem tmi;
		fm.add(tmi = new JMenuItem("New"));
		tmi.setEnabled(false);
		fm.add(tmi = new JMenuItem("Open..."));
		tmi.setEnabled(false);
		fm.add(tmi = new JMenuItem("Close"));
		tmi.setEnabled(false);
		fm.add(tmi = new JMenuItem("Close All"));
		tmi.setEnabled(false);
		fm.addSeparator();
		fm.add(tmi = new JMenuItem("Save"));
		tmi.setEnabled(false);
		fm.add(tmi = new JMenuItem("Save As..."));
		tmi.setEnabled(false);
		fm.addSeparator();
		fm.add(exitItem = new JMenuItem("Exit"));
		exitItem.addActionListener(this);
		mb.add(fm);

		JMenu em = new JMenu("Edit");
		em.add(tmi = new JMenuItem("Undo"));
		tmi.setEnabled(false);
		em.add(tmi = new JMenuItem("Cut"));
		tmi.setEnabled(false);
		em.add(tmi = new JMenuItem("Copy"));
		tmi.setEnabled(false);
		em.add(tmi = new JMenuItem("Paste"));
		tmi.setEnabled(false);
		mb.add(em);

		JMenu wm = new JMenu("Window");
		wm.add(iaItem = new JMenuItem("IA Trace"));
		iaItem.addActionListener(this);
		wm.add(tmi = new JMenuItem("Interrupts"));
		tmi.setEnabled(false);
		wm.add(tmi = new JMenuItem("Memory Map"));
		tmi.setEnabled(false);
		wm.add(tmi = new JMenuItem("Memory Protection"));
		tmi.setEnabled(false);
		wm.add(tmi = new JMenuItem("Write Locks"));
		tmi.setEnabled(false);
		mb.add(wm);

		setJMenuBar(mb);

		iaFrame = new IATraceFrame("IA Trace", cpu);
		addWindowListener(this);
		pack();
	}

	public void setComputer(SigmaComputer computer) {
		this.computer = computer;
	}

	public void actionPerformed(ActionEvent e) {
		try {
			doAction(e);
		} catch (Exception ex) {
			String message = ex.getMessage();
			if (message == null ||
				message.trim().length() == 0) {
				ex.printStackTrace();
				JOptionPane.showMessageDialog(this,
					ex.getClass().getName(), "Exception",
					JOptionPane.ERROR_MESSAGE);
			} else {
				JOptionPane.showMessageDialog(this,
					message, "Exception",
					JOptionPane.ERROR_MESSAGE);
			}
		}
	}

	protected void doAction(ActionEvent e) throws Exception {
		Object source = e.getSource();
		if (source == resetBtn) {
			computer.reset();
			regPanel.load();
			psdPanel.load();
			codePanel.load();
			iaFrame.load();
		} else if (source == loadBtn) {
			regPanel.store();
			psdPanel.store();
			codePanel.store();
			computer.load(unitTF.getInteger());
			regPanel.load();
			psdPanel.load();
			codePanel.load();
			iaFrame.load();
		} else if (source == stepBtn) {
			regPanel.store();
			psdPanel.store();
			codePanel.store();
			resetBtn.setEnabled(false);
			loadBtn.setEnabled(false);
			stepBtn.setEnabled(false);
			runBtn.setText("Stop");
			cpu.setBreakPoint(-1);
			computer.step();
		} else if (source == runBtn) {
			if (cpu.isRunning()) {
				cpu.stop();
				regPanel.load();
				psdPanel.load();
				codePanel.load();
				iaFrame.load();
				resetBtn.setEnabled(true);
				loadBtn.setEnabled(true);
				stepBtn.setEnabled(true);
				runBtn.setText("Run");
			} else {
				regPanel.store();
				psdPanel.store();
				codePanel.store();
				String bps = breakPointTF.getText();
				if (bps != null && bps.length() > 0) {
					try {
						cpu.setBreakPoint(breakPointTF.getInteger());
					} catch (IllegalArgumentException ex) {
						throw new IllegalArgumentException(
							"Break point value is invalid");
					}
				} else {
					cpu.setBreakPoint(-1);
				}
				bps = breakCountTF.getText();
				int count = 1;
				if (bps != null && bps.length() > 0) {
					try {
						count = breakCountTF.getInteger();
					} catch (IllegalArgumentException ex) {
						throw new IllegalArgumentException(
							"Break count value is invalid");
					}
				}
				cpu.setBreakCount(count);
				resetBtn.setEnabled(false);
				loadBtn.setEnabled(false);
				stepBtn.setEnabled(false);
				runBtn.setText("Stop");
				cpu.start();
			}
		} else if (source == exitItem) {
			exit(0);
		} else if (source == iaItem) {
			iaFrame.setVisible(true);
		}
	}

	protected void exit(int status) {
		System.exit(status);
	}

	public void windowActivated(WindowEvent e) { }
	public void windowClosed(WindowEvent e) { }

	public void windowClosing(WindowEvent e) {
		exit(0);
	}

	public void windowDeactivated(WindowEvent e) { }
	public void windowDeiconified(WindowEvent e) { }
	public void windowIconified(WindowEvent e) { }
	public void windowOpened(WindowEvent e)  { }

	public void update(Observable o, Object arg) {
		SwingUtilities.invokeLater(this);
	}

	public void run() {
		if (!cpu.isRunning()) {
			regPanel.load();
			psdPanel.load();
			codePanel.load();
			iaFrame.load();
			resetBtn.setEnabled(true);
			loadBtn.setEnabled(true);
			stepBtn.setEnabled(true);
			runBtn.setText("Run");
			Exception ex = cpu.getException();
			if (ex != null) {
				String message = ex.getMessage();
				if (message == null ||
					message.trim().length() == 0) {
					ex.printStackTrace();
					JOptionPane.showMessageDialog(this,
						ex.getClass().getName(), "Exception",
						JOptionPane.ERROR_MESSAGE);
				} else {
					JOptionPane.showMessageDialog(this,
						message, "Exception",
						JOptionPane.ERROR_MESSAGE);
				}
			}
		}
	}

	public static void main(String args[]) throws Exception {
		if (args.length < 1) {
			System.err.println(
				"usage: java <prog> <props-file> [<boot-unit>]");
			System.exit(1);
		}
		Properties props = new Properties();
		props.load(new FileInputStream(args[0]));
		Sigma6Computer sig6 = new Sigma6Computer(props);
		PCPFrame pcpF = new PCPFrame("Sigma6", sig6);
		pcpF.setVisible(true);
	}
}
