
package com.madhu.sigma.iop;

import java.util.Properties;
import java.util.ArrayList;

import com.madhu.sigma.*;
import com.madhu.sigma.cpu.*;

/**
 * A collection of IO processors
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class IOPManager {
	protected ArrayList iops;

	public IOPManager(Properties props,
		SigmaCPU cpu, MainMemory memory) throws Exception {

		iops = new ArrayList();
		int index = 1;
		while (true) {
			String name = "iop." + index;
			String value = props.getProperty(name);
			if (value == null) {
				break;
			}
			String[] strs = value.split(",");
			IOProcessor iop = (IOProcessor)
				Class.forName(strs[0]).newInstance();
			iop.setCPU(cpu);
			iop.setMemory(memory);
			if (strs[1].charAt(0) == '.') {
				iop.setUnit(Integer.parseInt(strs[1].substring(1), 16));
			} else {
				iop.setUnit(Integer.parseInt(strs[1]));
			}
			iop.setName(strs[2]);
			int n = strs.length - 3;
			String[] params = null;
			if (n > 0) {
				params = new String[n];
				for (int i=0; i<n; i+=1) {
					params[i] = strs[i+3];
				}
			}
			iop.init(params);
			iops.add(iop);
			index += 1;
		}
	}

	public IOProcessor getIOP(int ioAddr) {
		int n = iops.size();
		for (int i=0; i<n; i+=1) {
			IOProcessor iop = (IOProcessor) iops.get(i);
			if (iop.getUnit() == ioAddr) {
				return iop;
			}
		}
		return null;
	}

	public IOProcessor getInterruptReqIOP() {
		int n = iops.size();
		for (int i=0; i<n; i+=1) {
			IOProcessor iop = (IOProcessor) iops.get(i);
			if (iop.isInterruptPending()) {
				return iop;
			}
		}
		return null;
	}

	public void reset() {
		int n = iops.size();
		for (int i=0; i<n; i+=1) {
			IOProcessor iop = (IOProcessor) iops.get(i);
			iop.reset();
		}
	}
}
