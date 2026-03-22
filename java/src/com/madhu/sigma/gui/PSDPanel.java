
package com.madhu.sigma.gui;

import java.awt.Font;
import java.awt.GridBagConstraints;
import java.awt.GridBagLayout;
import java.awt.Insets;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;

import javax.swing.BorderFactory;
import javax.swing.JCheckBox;
import javax.swing.JFormattedTextField;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.JSpinner;
import javax.swing.border.Border;
import javax.swing.border.TitledBorder;
import javax.swing.event.ChangeEvent;
import javax.swing.event.ChangeListener;

import com.madhu.sigma.ProcessorControlPanel;
import com.madhu.sigma.SigmaComputer;
import com.madhu.sigma.cpu.SigmaCPU;

/**
 * Processor Status Doubleword (PSD) JPanel
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class PSDPanel extends JPanel implements
	ActionListener, ProcessorControlPanel, ChangeListener {

	protected SigmaComputer computer;
	protected JCheckBox cc1CB, cc2CB, cc3CB, cc4CB;
	protected JCheckBox msCB, mmCB, dmCB, amCB;
	protected JCheckBox ciCB, iiCB, eiCB;
	protected IntegerTextField iaTF;
	protected JCheckBox ss1CB, ss2CB, ss3CB, ss4CB;
	protected JSpinner iaSpinner;
	protected HexSpinnerModel iaModel;
	protected MemoryPanel memoryPanel;

	public PSDPanel(SigmaComputer computer) {
		this.computer = computer;
		Border etched = BorderFactory.createEtchedBorder();
		TitledBorder tb = BorderFactory.createTitledBorder(
				       etched, "Processor Status");
		setBorder(tb);
		GridBagLayout gb = new GridBagLayout();
		GridBagConstraints gbc = new GridBagConstraints();
		setLayout(gb);
		gbc.fill = GridBagConstraints.NONE;
		gbc.weightx = 1.0;
		gbc.weighty = 1.0;

		JLabel iaLB = new JLabel("Instruction Addr");
		add(iaLB);
		gbc.gridx = 0;
		gbc.gridy = 0;
		gbc.insets = new Insets(5, 0, 5, 5);
		gbc.anchor = GridBagConstraints.EAST;
		gb.setConstraints(iaLB, gbc);

		iaModel = new HexSpinnerModel();
		iaSpinner = new JSpinner(iaModel);
		add(iaSpinner);
		gbc.gridx = 1;
		gbc.gridy = 0;
		gbc.insets = new Insets(5, 0, 5, 0);
		gbc.anchor = GridBagConstraints.WEST;
		gb.setConstraints(iaSpinner, gbc);
		JFormattedTextField tf =
			((JSpinner.DefaultEditor)iaSpinner.getEditor()).getTextField();
		tf.setColumns(10);
		tf.setEditable(true);
		Font monoFont = new Font("Monospaced", Font.PLAIN, 12);
		tf.setFont(monoFont);
		iaSpinner.addChangeListener(this);

/*
		add(iaTF = new IntegerTextField(10));
		gbc.gridx = 1;
		gbc.gridy = 0;
		gbc.insets = new Insets(5, 0, 5, 0);
		gbc.anchor = gbc.WEST;
		gb.setConstraints(iaTF, gbc);
*/
		JPanel ccPanel = new JPanel();
		TitledBorder tbCC = BorderFactory.createTitledBorder(
				       etched, "Condition Codes");
		ccPanel.setBorder(tbCC);
		ccPanel.add(cc1CB = new JCheckBox("1"));
		ccPanel.add(cc2CB = new JCheckBox("2"));
		ccPanel.add(cc3CB = new JCheckBox("3"));
		ccPanel.add(cc4CB = new JCheckBox("4"));
		add(ccPanel);
		gbc.gridx = 0;
		gbc.gridy = 1;
		gbc.gridwidth = GridBagConstraints.REMAINDER;
		gbc.anchor = GridBagConstraints.CENTER;
		gb.setConstraints(ccPanel, gbc);

		JPanel cpPanel = new JPanel();
		TitledBorder tbCP = BorderFactory.createTitledBorder(
				       etched, "Control Bits");
		cpPanel.setBorder(tbCP);
		cpPanel.add(msCB = new JCheckBox("MS"));
		cpPanel.add(mmCB = new JCheckBox("MM"));
		cpPanel.add(dmCB = new JCheckBox("DM"));
		cpPanel.add(amCB = new JCheckBox("AM"));
		add(cpPanel);
		gbc.gridx = 0;
		gbc.gridy = 2;
		gbc.gridwidth = GridBagConstraints.REMAINDER;
		gbc.anchor = GridBagConstraints.CENTER;
		gb.setConstraints(cpPanel, gbc);
		mmCB.addChangeListener(this);

		JPanel intPanel = new JPanel();
		TitledBorder tbInt = BorderFactory.createTitledBorder(
				       etched, "Interrupt");
		intPanel.setBorder(tbInt);
		intPanel.add(ciCB = new JCheckBox("CI"));
		intPanel.add(iiCB = new JCheckBox("II"));
		intPanel.add(eiCB = new JCheckBox("EI"));
		add(intPanel);
		gbc.gridx = 0;
		gbc.gridy = 3;
		gbc.gridwidth = GridBagConstraints.REMAINDER;
		gbc.anchor = GridBagConstraints.CENTER;
		gb.setConstraints(intPanel, gbc);

		JPanel ssPanel = new JPanel();
		TitledBorder tbSS = BorderFactory.createTitledBorder(
				       etched, "Sense Switches");
		ssPanel.setBorder(tbSS);
		ssPanel.add(ss1CB = new JCheckBox("1"));
		ssPanel.add(ss2CB = new JCheckBox("2"));
		ssPanel.add(ss3CB = new JCheckBox("3"));
		ssPanel.add(ss4CB = new JCheckBox("4"));
		add(ssPanel);
		gbc.gridx = 0;
		gbc.gridy = 4;
		gbc.gridwidth = GridBagConstraints.REMAINDER;
		gbc.anchor = GridBagConstraints.CENTER;
		gb.setConstraints(ssPanel, gbc);

		JLabel rl = new JLabel("");
		add(rl);
		gbc.gridx = 0;
		gbc.gridy = 5;
		gbc.weighty = 1000.0;
		gbc.gridwidth = GridBagConstraints.REMAINDER;
		gb.setConstraints(rl, gbc);
	}

	public void setComputer(SigmaComputer computer) {
		this.computer = computer;
	}

	public void setMemoryPanel(MemoryPanel mp) {
		this.memoryPanel = mp;
	}

	public void load() {
		SigmaCPU cpu = computer.getCPU();
		int ia = cpu.getIA();
		iaModel.setInteger(ia);
		int cc = cpu.getCC();

		cc1CB.setSelected((cc & 0x8) != 0);
		cc2CB.setSelected((cc & 0x4) != 0);
		cc3CB.setSelected((cc & 0x2) != 0);
		cc4CB.setSelected((cc & 0x1) != 0);

		msCB.setSelected(cpu.isMS());
		mmCB.setSelected(cpu.isMM());
		dmCB.setSelected(cpu.isDM());
		amCB.setSelected(cpu.isAM());

		ciCB.setSelected(cpu.isCI());
		iiCB.setSelected(cpu.isII());
		eiCB.setSelected(cpu.isEI());
	}

	public void store() {
		SigmaCPU cpu = computer.getCPU();
		try {
			cpu.setIA(iaModel.getInteger());
		} catch (IllegalArgumentException e) {
			throw new IllegalArgumentException("IA value is invalid");
		}
		int cc = 0;
		cc |= cc1CB.isSelected() ? 0x8 : 0;
		cc |= cc2CB.isSelected() ? 0x4 : 0;
		cc |= cc3CB.isSelected() ? 0x2 : 0;
		cc |= cc4CB.isSelected() ? 0x1 : 0;
		cpu.setCC(cc);

		cpu.setMS(msCB.isSelected());
		cpu.setMM(mmCB.isSelected());
		cpu.setDM(dmCB.isSelected());
		cpu.setAM(amCB.isSelected());

		cpu.setCI(ciCB.isSelected());
		cpu.setII(iiCB.isSelected());
		cpu.setEI(eiCB.isSelected());
	}

	public void actionPerformed(ActionEvent e) {
	}

	public void stateChanged(ChangeEvent e) {
		Object source = e.getSource();
		if (source == iaSpinner) {
			SigmaCPU cpu = computer.getCPU();
			cpu.setIA(iaModel.getInteger());
			memoryPanel.load();
		} else if (source == mmCB) {
			SigmaCPU cpu = computer.getCPU();
			cpu.setMM(mmCB.isSelected());
			memoryPanel.load();
		}
	}

	public void setSenseSwitches(int senseSwitches) {
		int ss = senseSwitches;
		ss1CB.setSelected((ss & 0x8) != 0);
		ss2CB.setSelected((ss & 0x4) != 0);
		ss3CB.setSelected((ss & 0x2) != 0);
		ss4CB.setSelected((ss & 0x1) != 0);
	}

	public int getSenseSwitches() {
		int ss = 0;
		ss |= ss1CB.isSelected() ? 0x8 : 0;
		ss |= ss2CB.isSelected() ? 0x4 : 0;
		ss |= ss3CB.isSelected() ? 0x2 : 0;
		ss |= ss4CB.isSelected() ? 0x1 : 0;
		return ss;
	}
}
