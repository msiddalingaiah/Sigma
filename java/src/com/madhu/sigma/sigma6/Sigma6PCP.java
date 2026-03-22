
package com.madhu.sigma.sigma6;

import com.madhu.sigma.ProcessorControlPanel;

/**
 * A concrete Sigma 6 Processor Control Panel (PCP)
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class Sigma6PCP implements ProcessorControlPanel {
	protected boolean[] switches;	// yes, there are many!
	protected int senseSwitches;

	public Sigma6PCP() {
	}

	public void setSenseSwitches(int senseSwitches) {
		this.senseSwitches = senseSwitches;
	}

	public int getSenseSwitches() {
		return senseSwitches;
	}
}
