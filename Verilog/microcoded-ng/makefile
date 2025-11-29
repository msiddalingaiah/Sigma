
vcd/CPUTestBench: CPU.v IOP.v CPUTestBench.v roms/microcode.txt programs/init.txt programs/papertape.txt
	iverilog -g2009 -o vcd/CPUTestBench CPUTestBench.v
	vvp vcd/CPUTestBench

CPU.v roms/microcode.asm: Pipeline.py
	python Pipeline.py CPU.v roms/microcode.asm

roms/microcode.txt: roms/microcode.asm roms/Compiler.py roms/Generator.py
	python roms/Compiler.py roms/microcode.asm roms/microcode.txt

programs/init.txt: programs/init.asm roms/Assembler.py
	python roms/Assembler.py programs/init.asm programs/init.txt

programs/papertape.txt: programs/papertape.asm roms/Assembler.py
	python roms/Assembler.py programs/papertape.asm programs/papertape.txt

run:
	vvp vcd/CPUTestBench

all: CPU.v roms/microcode.asm vcd/CPUTestBench

test:
	python roms/CompilerTest.py

clean:
	del vcd\CPUTestBench
