
vcd/CPUTestBench: *.v roms/microcode.txt programs/init.txt
	iverilog -o vcd/CPUTestBench CPUTestBench.v
	vvp vcd/CPUTestBench

CPU.v roms/sigma.txt: Pipeline.py
	python Pipeline.py CPU.v roms/microcode.asm

roms/microcode.txt: roms/microcode.asm roms/Compiler.py roms/Generator.py
	python roms/Compiler.py roms/microcode.asm roms/microcode.txt

programs/init.txt: programs/init.asm roms/Assembler.py
	python roms/Assembler.py programs/init.asm programs/init.txt

run:
	vvp vcd/CPUTestBench

test:
	python roms/CompilerTest.py
