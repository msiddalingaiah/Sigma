
vcd/CPUTestBench: *.v roms/sigma_microcode.txt programs/init.txt
	iverilog -o vcd/CPUTestBench CPUTestBench.v
	vvp vcd/CPUTestBench

CPU.v roms/sigma.txt: Pipeline.py
	python Pipeline.py CPU.v roms/sigma.txt

roms/sigma_microcode.txt: roms/sigma.txt roms/*.py
	python roms/Compiler.py roms/sigma.txt roms/sigma_microcode.txt

programs/init.txt: programs/init.asm roms/*.py
	python roms/Assembler.py programs/init.asm programs/init.txt

run:
	vvp vcd/CPUTestBench

test:
	python roms/CompilerTest.py
