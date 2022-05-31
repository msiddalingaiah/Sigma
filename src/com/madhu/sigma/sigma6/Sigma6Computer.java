
package com.madhu.sigma.sigma6;

import java.io.FileInputStream;
import java.util.Properties;

import com.madhu.sigma.Disassembler;
import com.madhu.sigma.MainMemory;
import com.madhu.sigma.ProcessorControlPanel;
import com.madhu.sigma.SigmaComputer;
import com.madhu.sigma.iop.IOPManager;

/**
 * A complete Sigma 6 computer without a graphical user interface (headless)
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class Sigma6Computer extends SigmaComputer {
	int defaultBootUnit;

	public Sigma6Computer(Properties props) throws Exception {
		memory = new MainMemory(512 * 1024);
		cpu = new Sigma6CPU();
		cpu.setMemory(memory);
		iopMgr = new IOPManager(props, cpu, memory);
		cpu.setIOPManager(iopMgr);
		String boots = props.getProperty("bootUnit");
		if (boots.charAt(0) == '.') {
			defaultBootUnit = Integer.parseInt(boots.substring(1), 16);
		} else {
			defaultBootUnit = Integer.parseInt(boots);
		}
	}

	public void reset() {
		memory.reset();
		cpu.reset();
		iopMgr.reset();
	}

	public int getDefaultBootUnit() {
		return defaultBootUnit;
	}

	public void load() {
		load(defaultBootUnit);
	}

	public void load(int bootUnitAddr) {
		memory.writeWord(0x20, 0x00000000);
		memory.writeWord(0x21, 0x00000000);
		memory.writeWord(0x22, 0x020000A8);
		memory.writeWord(0x23, 0x0E000058);
		memory.writeWord(0x24, 0x00000011);
		memory.writeWord(0x25, bootUnitAddr);
		memory.writeWord(0x26, 0x32000024); // LW,0 X'24' (IO doubleword address)
		memory.writeWord(0x27, 0xCC000025); // SIO,0 *.25
		memory.writeWord(0x28, 0xCD000025); // TIO,0 *.25
		memory.writeWord(0x29, 0x69C00028); // BCS,12 .28
	}

	public void run() {
		cpu.runFast();
	}

	public void step() {
		cpu.step();
	}

	public void setSenseSwitches(int senseSwitches) {
		pcp.setSenseSwitches(senseSwitches);
	}

	public void setPCP(ProcessorControlPanel pcp) {
		this.pcp = pcp;
		cpu.setPCP(pcp);
	}

	public void timeInstruction(int addr) {
		cpu.timeInstruction(addr);
	}

	public void dumpLoad() {
		MainMemory memory = getMemory();
		Disassembler dis = new Disassembler();
		dis.disassemble(memory, 0x20, 0x2A);
	}

	public void runTests() {
		dumpLoad();
		System.out.println();
		MainMemory memory = getMemory();
		memory.testRWByte();
		System.out.println();
		memory.testRWHalfWord();
		System.out.println();
		memory.timeMemory();
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
		sig6.setPCP(new Sigma6PCP());
		sig6.reset();
		if (args.length == 2) {
			String boots = args[1];
			int unit;
			if (boots.charAt(0) == '.') {
				unit = Integer.parseInt(boots.substring(1), 16);
			} else {
				unit = Integer.parseInt(boots);
			}
			sig6.load(unit);
		} else {
			sig6.load();
		}
		sig6.setSenseSwitches(0);
		// sig6.run();
		sig6.timeInstruction(0x26);
	}
}
