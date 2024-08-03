
vcd/CPUTestBench: *.v roms/microcode.txt roms/sigma_microcode.txt programs/init.txt
	iverilog -o vcd/CPUTestBench CPUTestBench.v
	vvp vcd/CPUTestBench

roms/sigma_microcode.txt: roms/sigma.txt roms/*.py
	python roms/Compiler.py roms/sigma.txt roms/sigma_microcode.txt
