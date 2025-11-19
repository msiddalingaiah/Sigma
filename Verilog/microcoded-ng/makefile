
vcd/CPUTestBench: CPU.v CPUTestBench.v
	iverilog -g2009 -o vcd/CPUTestBench CPUTestBench.v
	vvp vcd/CPUTestBench

CPU.v roms/microcode.asm: Pipeline.py
	python Pipeline.py CPU.v roms/microcode.asm

run:
	vvp vcd/CPUTestBench

all: CPU.v roms/microcode.asm vcd/CPUTestBench

test:
	python roms/CompilerTest.py
