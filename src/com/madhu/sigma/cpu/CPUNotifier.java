
package com.madhu.sigma.cpu;

import java.util.Observable;

/**
 * 
 * @author Madhu Siddalingaiah
 * @author Keith Calkins
 */
public class CPUNotifier extends Observable {
	public void notifyObservers() {
		setChanged();
		super.notifyObservers();
	}
}
