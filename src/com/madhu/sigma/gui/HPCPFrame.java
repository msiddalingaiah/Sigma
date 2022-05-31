
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
import java.util.Properties;

import javax.swing.BorderFactory;
import javax.swing.JButton;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.Timer;
import javax.swing.border.Border;
import javax.swing.border.TitledBorder;

import com.madhu.sigma.SigmaComputer;
import com.madhu.sigma.cpu.SigmaCPU;
import com.madhu.sigma.sigma6.Sigma6Computer;

/**
 * Processor control panel JFrame
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class HPCPFrame extends JFrame implements
	ActionListener, WindowListener {

	protected SigmaComputer computer;
	protected SigmaCPU cpu;
	protected HRegisterPanel regPanel;
	protected HPSDPanel psdPanel;
	protected MemoryPanel codePanel;
	protected JButton resetBtn, loadBtn, stepBtn, runBtn;
	protected IntegerTextField unitTF;
	protected IntegerTextField breakPointTF;
	protected IntegerTextField breakCountTF;
	protected Timer updateTimer;

	public HPCPFrame(String title, SigmaComputer computer) {
		setTitle(title);
		this.computer = computer;
		cpu = computer.getCPU();
		Container cp = getContentPane();
		cp.setLayout(new BorderLayout());

		JPanel center = new JPanel();

		GridBagLayout gb = new GridBagLayout();
		GridBagConstraints gbc = new GridBagConstraints();

		center.setLayout(gb);

		gbc.fill = GridBagConstraints.BOTH;
		gbc.weightx = 1.0;
		gbc.weighty = 1.0;
		gbc.gridx = 0;
		gbc.gridy = 0;

		center.add(regPanel = new HRegisterPanel(computer));
		gb.setConstraints(regPanel, gbc);

		gbc.gridx = 0;
		gbc.gridy = 1;
		center.add(psdPanel = new HPSDPanel(computer));
		gb.setConstraints(psdPanel, gbc);
		computer.setPCP(psdPanel);

		gbc.gridx = 0;
		gbc.gridy = 2;
		center.add(codePanel = new MemoryPanel(computer));
		gbc.weightx = 1000.0;
		gbc.weighty = 1000.0;
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
		updateTimer = new Timer(100, this);

		cp.add(south, BorderLayout.SOUTH);

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
		} else if (source == loadBtn) {
			regPanel.store();
			psdPanel.store();
			codePanel.store();
			computer.load(unitTF.getInteger());
			regPanel.load();
			psdPanel.load();
			codePanel.load();
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
			updateTimer.start();
		} else if (source == runBtn) {
			if (cpu.isRunning()) {
				cpu.stop();
				regPanel.load();
				psdPanel.load();
				codePanel.load();
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
				updateTimer.start();
			}
		} else if (source == updateTimer) {
			if (!cpu.isRunning()) {
				updateTimer.stop();
				regPanel.load();
				psdPanel.load();
				codePanel.load();
				resetBtn.setEnabled(true);
				loadBtn.setEnabled(true);
				stepBtn.setEnabled(true);
				runBtn.setText("Run");
				Exception ex = cpu.getException();
				if (ex != null) {
					throw ex;
				}
			}
		} else if (source == cpu) {
			if (!cpu.isRunning()) {
				updateTimer.stop();
				regPanel.load();
				psdPanel.load();
				codePanel.load();
				resetBtn.setEnabled(true);
				loadBtn.setEnabled(true);
				stepBtn.setEnabled(true);
				runBtn.setText("Run");
				Exception ex = cpu.getException();
				if (ex != null) {
					throw ex;
				}
			}
		}
	}

	public void windowActivated(WindowEvent e) { }
	public void windowClosed(WindowEvent e) { }

	public void windowClosing(WindowEvent e) {
		System.exit(0);
	}

	public void windowDeactivated(WindowEvent e) { }
	public void windowDeiconified(WindowEvent e) { }
	public void windowIconified(WindowEvent e) { }
	public void windowOpened(WindowEvent e)  { }

	public static void main(String args[]) throws Exception {
		Properties props = new Properties();
		props.load(new FileInputStream(args[0]));
		Sigma6Computer sig6 = new Sigma6Computer(props);
		HPCPFrame pcpF = new HPCPFrame("Sigma6", sig6);
		pcpF.setVisible(true);
	}
}
