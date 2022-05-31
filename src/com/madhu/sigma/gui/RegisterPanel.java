
package com.madhu.sigma.gui;

import java.awt.GridBagConstraints;
import java.awt.GridBagLayout;
import java.awt.Insets;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;

import javax.swing.BorderFactory;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.border.Border;
import javax.swing.border.TitledBorder;

import com.madhu.sigma.MainMemory;
import com.madhu.sigma.SigmaComputer;

/**
 * General purpose register JPanel
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class RegisterPanel extends JPanel implements
	ActionListener {

	protected SigmaComputer computer;
	protected IntegerTextField[] regTFs;

	public RegisterPanel(SigmaComputer computer) {
		this.computer = computer;
		Border etched = BorderFactory.createEtchedBorder();
		TitledBorder tb = BorderFactory.createTitledBorder(
				       etched, "Registers");
		setBorder(tb);
		GridBagLayout gb = new GridBagLayout();
		GridBagConstraints gbc = new GridBagConstraints();
		setLayout(gb);
		gbc.fill = GridBagConstraints.NONE;
		gbc.weightx = 1.0;
		gbc.weighty = 1.0;
		gbc.anchor = GridBagConstraints.WEST;
		Insets inset1 = new Insets(0, 5, 0, 0);
		Insets inset2 = new Insets(0, 5, 0, 5);
		regTFs = new IntegerTextField[16];
		for (int i=0; i<16; i+=1) {
			String rls = "R" + i;
			JLabel rl = new JLabel(rls);
			add(rl);
			gbc.gridx = 0;
			gbc.gridy = i;
			gbc.insets = inset1;
			gb.setConstraints(rl, gbc);
			add(regTFs[i] = new IntegerTextField(".0", 10));
			gbc.gridx = 1;
			gbc.insets = inset2;
			gb.setConstraints(regTFs[i], gbc);
		}
		JLabel rl = new JLabel("");
		add(rl);
		gbc.gridx = 0;
		gbc.gridy = 16;
		gbc.weighty = 1000.0;
		gbc.gridwidth = GridBagConstraints.REMAINDER;
		gb.setConstraints(rl, gbc);
	}

	public void setComputer(SigmaComputer computer) {
		this.computer = computer;
	}

	public void load() {
		MainMemory mem = computer.getMemory();
		for (int i=0; i<16; i+=1) {
			int v = mem.readWord(i);
			regTFs[i].setInteger(v);
		}
	}

	public void store() {
		MainMemory mem = computer.getMemory();
		for (int i=0; i<16; i+=1) {
			try {
				int v = regTFs[i].getInteger();
				mem.writeWord(i, v);
			} catch (IllegalArgumentException e) {
				throw new IllegalArgumentException(
					"Register " + i + " value is invalid");
			}
		}
	}

	public void actionPerformed(ActionEvent e) {
	}
}
