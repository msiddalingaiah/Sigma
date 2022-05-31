
package com.madhu.sigma;

import com.madhu.sigma.cpu.*;
import com.madhu.sigma.iop.*;

/**
 * An abstract representation of a Sigma computer system
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public abstract class SigmaComputer {
	protected MainMemory memory;
	protected SigmaCPU cpu;
	protected ProcessorControlPanel pcp;
	protected IOPManager iopMgr;

	public SigmaComputer() {
	}

	public SigmaCPU getCPU() {
		return cpu;
	}

	public MainMemory getMemory() {
		return memory;
	}


	public abstract void setPCP(ProcessorControlPanel pcp);
	public abstract void reset();
	public abstract int getDefaultBootUnit();
	public abstract void load(int bootUnitAddr);
	public abstract void run();
	public abstract void step();
}
