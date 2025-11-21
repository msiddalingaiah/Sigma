
vcd/CPUTestBench: CPU.v CPUTestBench.v roms/microcode.txt
	iverilog -g2009 -o vcd/CPUTestBench CPUTestBench.v
	vvp vcd/CPUTestBench

CPU.v roms/microcode.asm: Pipeline.py
	python Pipeline.py CPU.v roms/microcode.asm

roms/microcode.txt: roms/microcode.asm roms/Compiler.py roms/Generator.py
	python roms/Compiler.py roms/microcode.asm roms/microcode.txt

run:
	vvp vcd/CPUTestBench

all: CPU.v roms/microcode.asm vcd/CPUTestBench

test:
	python roms/CompilerTest.py
