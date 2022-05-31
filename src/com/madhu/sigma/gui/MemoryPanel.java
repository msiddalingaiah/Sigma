
package com.madhu.sigma.gui;

import java.awt.BorderLayout;
import java.awt.Font;
import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.awt.event.ItemEvent;
import java.awt.event.ItemListener;

import javax.swing.BorderFactory;
import javax.swing.JCheckBox;
import javax.swing.JLabel;
import javax.swing.JList;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.border.Border;
import javax.swing.border.TitledBorder;

import com.madhu.sigma.Disassembler;
import com.madhu.sigma.MainMemory;
import com.madhu.sigma.OpCode;
import com.madhu.sigma.SigmaComputer;
import com.madhu.sigma.cpu.SigmaCPU;

/**
 * Memory display panel with hex and EBCDIC conversion
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class MemoryPanel extends JPanel implements
	ActionListener, ItemListener {

	private static String toASCII =
	  // 0123456789ABCDEF0123456789ABCDEF
		"................................" +
		"................................" +
		" ...........<(+|&.........!$*);." +
		"-/.........,%_>?..........:#@'=\"" +
		".abcdefghi.......jklmnopqr......" +
		"..stuvwxyz...............`......" +
		".ABCDEFGHI.......JKLMNOPQR......" +
		"..STUVWXYZ......0123456789......";

	protected SigmaComputer computer;
	protected IntegerTextField startAddrTF;
	protected JCheckBox followIACB;
	protected JList codeList;
	protected OpCode[] instArray;
	protected int visibleLines = 32;
	protected String[] lines;
	protected IntegerTextField editAddrTF;
	protected IntegerTextField editDataTF;

	public MemoryPanel(SigmaComputer computer) {
		this.computer = computer;
		instArray = OpCode.getOpCodes();
		lines = new String[visibleLines];
		Border etched = BorderFactory.createEtchedBorder();
		TitledBorder tb = BorderFactory.createTitledBorder(
				       etched, "Memory");
		setBorder(tb);
		setLayout(new BorderLayout());

		Font monoFont = new Font("Monospaced", Font.PLAIN, 12);

		JPanel north = new JPanel();
		north.add(new JLabel("Address"));
		startAddrTF = new IntegerTextField(".20", 7);
		startAddrTF.setFont(monoFont);
		north.add(startAddrTF);
		followIACB = new JCheckBox("Follow IA", true);
		north.add(followIACB);
		add(north, BorderLayout.NORTH);

		codeList = new JList();
		codeList.setFont(monoFont);
		codeList.setVisibleRowCount(16);
		codeList.setPrototypeCellValue(" . 26  .00000000  ?.00,0   .0            ....");

		JScrollPane jsp = new JScrollPane(codeList,
			JScrollPane.VERTICAL_SCROLLBAR_ALWAYS,
			JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);
		add(jsp, BorderLayout.CENTER);

		JPanel south = new JPanel();
		Border etched1 = BorderFactory.createEtchedBorder();
		TitledBorder tb1 = BorderFactory.createTitledBorder(
				       etched1, "Edit Memory");
		south.setBorder(tb1);
		south.add(new JLabel("Address"));
		editAddrTF = new IntegerTextField(".26", 7);
		editAddrTF.setFont(monoFont);
		south.add(editAddrTF);
		south.add(new JLabel("Data/Assy"));
		editDataTF = new IntegerTextField(16);
		editDataTF.setFont(monoFont);
		south.add(editDataTF);
		add(south, BorderLayout.SOUTH);
		editAddrTF.addActionListener(this);
		editDataTF.addActionListener(this);

		startAddrTF.addActionListener(this);
		followIACB.addItemListener(this);
	}

	public void setComputer(SigmaComputer computer) {
		this.computer = computer;
	}

	public void load() {
		MainMemory memory = computer.getMemory();
		SigmaCPU cpu = computer.getCPU();
		int start = startAddrTF.getInteger() & 0x1ffff;
		int ia = cpu.getIA() & 0x1ffff;
		if (followIACB.isSelected() &&
			(ia < start || ia >= start+16)) {
			start = ia-1;
			if (start < 0) {
				start = 0;
			}
			startAddrTF.setInteger(start);
		}
		int addr = start;
		for (int i=0; i<visibleLines; i+=1) {
			int iWord = memory.readWord(addr);
			int code = (iWord >>> 24) & 0x7f;
			OpCode inst = instArray[code];
			StringBuffer sb = new StringBuffer(30);
			sb.append(Disassembler.toHexString(addr, 3, ' '));
			sb.append("  ");
			sb.append(Disassembler.toHexString(iWord, 8, '0'));
			sb.append("  ");
			sb.append(inst.decode(iWord));
			int n = sb.length();
			for (int j=0; j<40-n; j+=1) {
				sb.append(' ');
			}
			sb.append(toASCII.charAt((iWord >> 24) & 0xff));
			sb.append(toASCII.charAt((iWord >> 16) & 0xff));
			sb.append(toASCII.charAt((iWord >> 8) & 0xff));
			sb.append(toASCII.charAt((iWord) & 0xff));
			lines[i] = sb.toString();
			addr += 1;
		}
		codeList.setListData(lines);
		if (ia < start+visibleLines && ia >= start) {
			codeList.setSelectedIndex(ia-start);
		}
	}

	protected void loadEditPanel() {
		try {
			MainMemory memory = computer.getMemory();
			int addr = editAddrTF.getInteger();
			int iWord = memory.readWord(addr);
			editDataTF.setInteger(iWord);
		} catch (IllegalArgumentException e) {
			JOptionPane.showMessageDialog(this,
				e.getMessage() + " is not a valid HEX value",
				"Data Entry Error",
				JOptionPane.ERROR_MESSAGE);
		}
	}

	public void store() {
	}

	public void actionPerformed(ActionEvent e) {
		Object source = e.getSource();
		if (source == startAddrTF) {
			try {
				followIACB.setSelected(false);
				load();
			} catch (IllegalArgumentException ex) {
				JOptionPane.showMessageDialog(this,
					ex.getMessage() + " is not a valid HEX value",
					"Data Entry Error",
					JOptionPane.ERROR_MESSAGE);
			}
		} else if (source == editAddrTF) {
		} else if (source == editDataTF) {
			MainMemory memory = computer.getMemory();
			try {
				int addr = editAddrTF.getInteger();
				int iWord = OpCode.encode(editDataTF.getText());
				memory.writeWord(addr, iWord);
				editAddrTF.setInteger(addr+1);
				load();
			} catch (IllegalArgumentException ex) {
				JOptionPane.showMessageDialog(this,
					ex.getMessage() + " is not a valid instruction",
					"Data Entry Error",
					JOptionPane.ERROR_MESSAGE);
			}
		}
	}

	public void itemStateChanged(ItemEvent e) {
		Object source = e.getItemSelectable();

		if (source == followIACB) {
			if (e.getStateChange() == ItemEvent.SELECTED) {
				load();
			}
		}
	}
}
