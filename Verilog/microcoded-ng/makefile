
vcd/CPUTestBench: verilog/CPU.v verilog/IOP.v verilog/CPUTestBench.v roms/microcode.txt programs/init.txt programs/papertape.txt
	iverilog -g2009 -o vcd/CPUTestBench.vvp verilog/CPUTestBench.v
	vvp vcd/CPUTestBench.vvp

CPU.v roms/microcode.asm: py/Pipeline.py
	python py/Pipeline.py verilog/CPU.v roms/microcode.asm

roms/microcode.txt: roms/microcode.asm py/Compiler.py py/Generator.py
	python py/Compiler.py roms/microcode.asm roms/microcode.txt

programs/init.txt: programs/init.asm py/Assembler.py
	python py/Assembler.py programs/init.asm programs/init.txt

programs/papertape.txt: programs/papertape.asm py/Assembler.py
	python py/Assembler.py programs/papertape.asm programs/papertape.txt

run:
	vvp vcd/CPUTestBench

all: CPU.v roms/microcode.asm vcd/CPUTestBench

test:
	python py/CompilerTest.py

clean:
	del vcd\CPUTestBench
