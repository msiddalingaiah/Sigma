
package com.madhu.sigma;

import java.util.regex.*;

/**
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class OpCode {
	private static OpCode[] opCodes;
	private static Pattern instPattern = Pattern.compile(
		"([a-zA-Z0-9]{1,4})\\s*,\\s*([0-9]+)\\s+((\\*?)([\\.0-9a-fA-F]+))(\\s*,\\s*(([0-9]+)))?");
	protected static final int NAME_GROUP = 1;
	protected static final int REGR_GROUP = 2;
	protected static final int IND_GROUP = 4;
	protected static final int ADDR_GROUP = 5;
	protected static final int REGX_GROUP = 7;

	protected static final String[] bcrNames = {
		"B", "BGE", "BLE", "BE", "BAZ"
	};

	protected static final String[] bcsNames = {
		"BCS", "BL", "BG", "BNE", "BANZ"
	};

	protected static final String[] shiftNames = {
		"SLS", "SLD", "SCS", "SCD", "SAS", "SAD", "SSS", "SSD"
	};


	protected int code;
	protected String name;
	protected String description;

	public OpCode(int code, String name, String description) {
		this.code = code;
		this.name = name;
		this.description = description;
	}

	public String getName() {
		return name;
	}

	public String decode(int iword) {
		boolean ind = iword < 0;
		int code = (iword >>> 24) & 0x7f;
		int regR = (iword >>> 20) & 0x0f;
		int regX = (iword >>> 17) & 0x07;
		int addr = iword & 0x1ffff;
		StringBuffer sb = new StringBuffer(20);
		sb.append(getName());
		sb.append(",");
		sb.append(Integer.toString(regR));

		int nChars = 9;
		int n = sb.length();
		for (int i=0; i<nChars-n; i++) {
			sb.append(' ');
		}

		if (ind) {
			sb.append("*");
		}
		sb.append(".");
		sb.append(Integer.toHexString(addr).toUpperCase());
		if (regX != 0) {
			sb.append(",");
			sb.append(Integer.toString(regX));
		}
		return sb.toString();
	}

	public int encode(Matcher m) {
		int regR = Integer.parseInt(m.group(REGR_GROUP));
		int addr = 0;
		String addrs = m.group(ADDR_GROUP);
		if (addrs.charAt(0) == '.') {
			addr = Integer.parseInt(addrs.substring(1), 16);
		} else {
			addr = Integer.parseInt(addrs);
		}
		int regX = 0;
		String regXs = m.group(REGX_GROUP);
		if (regXs != null) {
			regX = Integer.parseInt(regXs);
		}
		int iWord = code << 24;
		iWord |= regR << 20;
		iWord |= regX << 17;
		iWord |= addr;
		if (m.group(IND_GROUP).length() != 0) {
			iWord |= 0x80000000;
		}
		return iWord;
	}

	public static int encode(String assy) {
		assy = assy.trim();
		Matcher m = instPattern.matcher(assy);
		if (m.matches()) {
			OpCode[] insts = getOpCodes();
			String name = m.group(NAME_GROUP).toUpperCase();
			int n = insts.length;
			for (int i=0; i<n; i+=1) {
				if (name.equals(insts[i].getName())) {
					return insts[i].encode(m);
				}
			}
		} else {
			if (assy.charAt(0) == '.') {
				long lv = Long.parseLong(assy.substring(1), 16);
				return (int) (lv & 0x0FFFFFFFFL);
			} else {
				return Integer.parseInt(assy);
			}
		}
		throw new IllegalArgumentException(assy);
	}

	public static OpCode getOpCode(int code) {
		OpCode[] inst = getOpCodes();
		return inst[code];
	}

	public static OpCode[] getOpCodes() {
		if (opCodes != null) {
			return opCodes;
		}
		opCodes = new OpCode[128];
		opCodes[0x00] = new OpCode(0x00, "?.00", "");
		opCodes[0x01] = new OpCode(0x01, "?.01", "");
		opCodes[0x02] = new ImmediateOpCode(0x02, "LCFI", "");
		opCodes[0x03] = new OpCode(0x03, "?.03", "");
		opCodes[0x04] = new OpCode(0x04, "CAL1", "");
		opCodes[0x05] = new OpCode(0x05, "CAL2", "");
		opCodes[0x06] = new OpCode(0x06, "CAL3", "");
		opCodes[0x07] = new OpCode(0x07, "CAL4", "");
		opCodes[0x08] = new OpCode(0x08, "PLW", "");
		opCodes[0x09] = new OpCode(0x09, "PSW", "");
		opCodes[0x0A] = new OpCode(0x0A, "PLM", "");
		opCodes[0x0B] = new OpCode(0x0B, "PSM", "");
		opCodes[0x0C] = new OpCode(0x0C, "?.0C", "");
		opCodes[0x0D] = new OpCode(0x0D, "?.0D", "");
		opCodes[0x0E] = new OpCode(0x0E, "LPSD", "");
		opCodes[0x0F] = new OpCode(0x0F, "XPSD", "");
		opCodes[0x10] = new OpCode(0x10, "AD", "");
		opCodes[0x11] = new OpCode(0x11, "CD", "");
		opCodes[0x12] = new OpCode(0x12, "LD", "");
		opCodes[0x13] = new OpCode(0x13, "MSP", "");
		opCodes[0x14] = new OpCode(0x14, "?.14", "");
		opCodes[0x15] = new OpCode(0x15, "STD", "");
		opCodes[0x16] = new OpCode(0x16, "?.16", "");
		opCodes[0x17] = new OpCode(0x17, "?.17", "");
		opCodes[0x18] = new OpCode(0x18, "SD", "");
		opCodes[0x19] = new OpCode(0x19, "CLM", "");
		opCodes[0x1A] = new OpCode(0x1A, "LCD", "");
		opCodes[0x1B] = new OpCode(0x1B, "LAD", "");
		opCodes[0x1C] = new OpCode(0x1C, "FSL", "");
		opCodes[0x1D] = new OpCode(0x1D, "FAL", "");
		opCodes[0x1E] = new OpCode(0x1E, "FDL", "");
		opCodes[0x1F] = new OpCode(0x1F, "FML", "");
		opCodes[0x20] = new ImmediateOpCode(0x20, "AI", "");
		opCodes[0x21] = new ImmediateOpCode(0x21, "CI", "");
		opCodes[0x22] = new ImmediateOpCode(0x22, "LI", "");
		opCodes[0x23] = new ImmediateOpCode(0x23, "MI", "");
		opCodes[0x24] = new OpCode(0x24, "SF", "");
		opCodes[0x25] = new ShiftOpCode(0x25, "S", "", shiftNames);
		opCodes[0x26] = new OpCode(0x26, "?.26", "");
		opCodes[0x27] = new OpCode(0x27, "?.27", "");
		opCodes[0x28] = new OpCode(0x28, "CVS", "");
		opCodes[0x29] = new OpCode(0x29, "CVA", "");
		opCodes[0x2A] = new OpCode(0x2A, "LM", "");
		opCodes[0x2B] = new OpCode(0x2B, "STM", "");
		opCodes[0x2C] = new OpCode(0x2C, "?.2C", "");
		opCodes[0x2D] = new OpCode(0x2D, "?.2D", "");
		opCodes[0x2E] = new OpCode(0x2E, "WAIT", "");
		opCodes[0x2F] = new OpCode(0x2F, "LRP", "");
		opCodes[0x30] = new OpCode(0x30, "AW", "");
		opCodes[0x31] = new OpCode(0x31, "CW", "");
		opCodes[0x32] = new OpCode(0x32, "LW", "");
		opCodes[0x33] = new OpCode(0x33, "MTW", "");
		opCodes[0x34] = new OpCode(0x34, "?.34", "");
		opCodes[0x35] = new OpCode(0x35, "STW", "");
		opCodes[0x36] = new OpCode(0x36, "DW", "");
		opCodes[0x37] = new OpCode(0x37, "MW", "");
		opCodes[0x38] = new OpCode(0x38, "SW", "");
		opCodes[0x39] = new OpCode(0x39, "CLR", "");
		opCodes[0x3A] = new OpCode(0x3A, "LCW", "");
		opCodes[0x3B] = new OpCode(0x3B, "LAW", "");
		opCodes[0x3C] = new OpCode(0x3C, "FSS", "");
		opCodes[0x3D] = new OpCode(0x3D, "FAS", "");
		opCodes[0x3E] = new OpCode(0x3E, "FDS", "");
		opCodes[0x3F] = new OpCode(0x3F, "FMS", "");
		opCodes[0x40] = new ImmediateOpCode(0x40, "TTBS", "");
		opCodes[0x41] = new ImmediateOpCode(0x41, "TBS", "");
		opCodes[0x42] = new OpCode(0x42, "?.42", "");
		opCodes[0x43] = new OpCode(0x43, "?.43", "");
		opCodes[0x44] = new OpCode(0x44, "ANLZ", "");
		opCodes[0x45] = new OpCode(0x45, "CS", "");
		opCodes[0x46] = new OpCode(0x46, "XW", "");
		opCodes[0x47] = new OpCode(0x47, "STS", "");
		opCodes[0x48] = new OpCode(0x48, "EOR", "");
		opCodes[0x49] = new OpCode(0x49, "OR", "");
		opCodes[0x4A] = new OpCode(0x4A, "LS", "");
		opCodes[0x4B] = new OpCode(0x4B, "AND", "");
		opCodes[0x4C] = new OpCode(0x4C, "SIO", "");
		opCodes[0x4D] = new OpCode(0x4D, "TIO", "");
		opCodes[0x4E] = new OpCode(0x4E, "TDV", "");
		opCodes[0x4F] = new OpCode(0x4F, "HIO", "");
		opCodes[0x50] = new OpCode(0x50, "AH", "");
		opCodes[0x51] = new OpCode(0x51, "CH", "");
		opCodes[0x52] = new OpCode(0x52, "LH", "");
		opCodes[0x53] = new OpCode(0x53, "MTH", "");
		opCodes[0x54] = new OpCode(0x54, "?.54", "");
		opCodes[0x55] = new OpCode(0x55, "STH", "");
		opCodes[0x56] = new OpCode(0x56, "DH", "");
		opCodes[0x57] = new OpCode(0x57, "MH", "");
		opCodes[0x58] = new OpCode(0x58, "SH", "");
		opCodes[0x59] = new OpCode(0x59, "?.59", "");
		opCodes[0x5A] = new OpCode(0x5A, "LCH", "");
		opCodes[0x5B] = new OpCode(0x5B, "LAH", "");
		opCodes[0x5C] = new OpCode(0x5C, "?.5C", "");
		opCodes[0x5D] = new OpCode(0x5D, "?.5D", "");
		opCodes[0x5E] = new OpCode(0x5E, "?.5E", "");
		opCodes[0x5F] = new OpCode(0x5F, "?.5F", "");
		opCodes[0x60] = new ImmediateOpCode(0x60, "CBS", "");
		opCodes[0x61] = new ImmediateOpCode(0x61, "MBS", "");
		opCodes[0x62] = new OpCode(0x62, "?.62", "");
		opCodes[0x63] = new ImmediateOpCode(0x63, "EBS", "");
		opCodes[0x64] = new BranchOpCode(0x64, "BDR", "");
		opCodes[0x65] = new BranchOpCode(0x65, "BIR", "");
		opCodes[0x66] = new OpCode(0x66, "AWM", "");
		opCodes[0x67] = new OpCode(0x67, "EXU", "");
		opCodes[0x68] = new BCRBCSOpCode(0x68, "BCR", "", bcrNames);
		opCodes[0x69] = new BCRBCSOpCode(0x69, "BCS", "", bcsNames);
		opCodes[0x6A] = new BranchOpCode(0x6A, "BAL", "");
		opCodes[0x6B] = new OpCode(0x6B, "INT", "");
		opCodes[0x6C] = new OpCode(0x6C, "RD", "");
		opCodes[0x6D] = new OpCode(0x6D, "WD", "");
		opCodes[0x6E] = new OpCode(0x6E, "AIO", "");
		opCodes[0x6F] = new OpCode(0x6F, "MMC", "");
		opCodes[0x70] = new OpCode(0x70, "LCF", "");
		opCodes[0x71] = new OpCode(0x71, "CB", "");
		opCodes[0x72] = new OpCode(0x72, "LB", "");
		opCodes[0x73] = new OpCode(0x73, "MTB", "");
		opCodes[0x74] = new OpCode(0x74, "STFC", "");
		opCodes[0x75] = new OpCode(0x75, "STB", "");
		opCodes[0x76] = new OpCode(0x76, "PACK", "");
		opCodes[0x77] = new OpCode(0x77, "UNPK", "");
		opCodes[0x78] = new OpCode(0x78, "DS", "");
		opCodes[0x79] = new OpCode(0x79, "DA", "");
		opCodes[0x7A] = new OpCode(0x7A, "DD", "");
		opCodes[0x7B] = new OpCode(0x7B, "DM", "");
		opCodes[0x7C] = new OpCode(0x7C, "DSA", "");
		opCodes[0x7D] = new OpCode(0x7D, "DC", "");
		opCodes[0x7E] = new OpCode(0x7E, "DL", "");
		opCodes[0x7F] = new OpCode(0x7F, "DST", "");
		return opCodes;
	}
}

class ImmediateOpCode extends OpCode {
	public ImmediateOpCode(int code, String name, String description) {
		super(code, name, description);
	}

	public String decode(int iword) {
		int code = (iword >>> 24) & 0x7f;
		if (iword < 0) {
			return "?." + Integer.toHexString(code).toUpperCase();
		}
		int regR = (iword >>> 20) & 0x0f;
		int value = iword & 0xfffff;
		value <<= 12;
		value >>= 12;	// sign extend
		StringBuffer sb = new StringBuffer(20);
		sb.append(getName());
		sb.append(",");
		sb.append(Integer.toString(regR));

		int nChars = 9;
		int n = sb.length();
		for (int i=0; i<nChars-n; i++) {
			sb.append(' ');
		}

		sb.append(".");
		sb.append(Integer.toHexString(value).toUpperCase());
		sb.append(" (");
		sb.append(Integer.toString(value));
		sb.append(")");
		return sb.toString();
	}

	public int encode(Matcher m) {
		if (m.group(REGX_GROUP) != null ||
			m.group(IND_GROUP).length() != 0) {
			throw new IllegalArgumentException(m.group(0));
		}
		int regR = Integer.parseInt(m.group(REGR_GROUP));
		int value = 0;
		String values = m.group(ADDR_GROUP);
		if (values.charAt(0) == '.') {
			value = Integer.parseInt(values.substring(1), 16);
		} else {
			value = Integer.parseInt(values);
		}
		int iWord = code << 24;
		iWord |= regR << 20;
		iWord |= value;
		return iWord;
	}
}

class BranchOpCode extends OpCode {
	public BranchOpCode(int code, String name, String description) {
		super(code, name, description);
	}
}

class BCRBCSOpCode extends BranchOpCode {
	protected String[] nameMap;

	public BCRBCSOpCode(int code, String name,
		String description, String[] nameMap) {
		super(code, name, description);
		this.nameMap = nameMap;
	}

	public String decode(int iword) {
		boolean ind = iword < 0;
		int code = (iword >>> 24) & 0x7f;
		int regR = (iword >>> 20) & 0x0f;
		int regX = (iword >>> 17) & 0x07;
		int addr = iword & 0x1ffff;
		StringBuffer sb = new StringBuffer(20);
		if (regR < nameMap.length) {
			sb.append(nameMap[regR]);
		} else {
			sb.append(getName());
			sb.append(",");
			sb.append(Integer.toString(regR));
		}

		int nChars = 9;
		int n = sb.length();
		for (int i=0; i<nChars-n; i++) {
			sb.append(' ');
		}

		if (ind) {
			sb.append("*");
		}
		sb.append(".");
		sb.append(Integer.toHexString(addr).toUpperCase());
		if (regX != 0) {
			sb.append(",");
			sb.append(Integer.toString(regX));
		}
		return sb.toString();
	}
}

class ShiftOpCode extends OpCode {
	protected String[] nameMap;
	// Note, Sig6 does not include SSS, SSD

	public ShiftOpCode(int code, String name,
		String description, String[] nameMap) {
		super(code, name, description);
		this.nameMap = nameMap;
	}

	public String decode(int iword) {
		boolean ind = iword < 0;
		if (ind) {
			return super.decode(iword);
		}
		int code = (iword >>> 24) & 0x7f;
		int regR = (iword >>> 20) & 0x0f;
		int regX = (iword >>> 17) & 0x07;
		int type = (iword >>> 8) & 0x7;
		int count = iword & 0x7F;
		count <<= 25;
		count >>= 25;

		StringBuffer sb = new StringBuffer(20);
		sb.append(nameMap[type]);
		sb.append(",");
		sb.append(Integer.toString(regR));

		int nChars = 9;
		int n = sb.length();
		for (int i=0; i<nChars-n; i++) {
			sb.append(' ');
		}

		sb.append(Integer.toString(count));
		if (regX != 0) {
			sb.append(",");
			sb.append(Integer.toString(regX));
		}
		return sb.toString();
	}
}
