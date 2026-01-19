
vcd/CPUTestBench.vvp: verilog/CPU.v verilog/IOP.v verilog/CPUTestBench.v roms/microcode.txt programs/init.txt programs/papertape.txt
	iverilog -g2009 -DPROJ_DIR=\".\" -o vcd/CPUTestBench.vvp verilog/CPUTestBench.v verilog/CPU.v verilog/IOP.v verilog/Sequencer.v
	vvp vcd/CPUTestBench.vvp

verilog/CPU.v roms/microcode.asm: py/Pipeline.py
	python py/Pipeline.py verilog/CPU.v roms/microcode.asm

roms/microcode.txt: roms/microcode.asm py/Compiler.py py/Generator.py
	python py/Compiler.py roms/microcode.asm roms/microcode.txt

programs/init.txt: programs/init.asm py/Assembler.py
	python py/Assembler.py programs/init.asm programs/init.txt

programs/papertape.txt: programs/papertape.asm py/Assembler.py
	python py/Assembler.py programs/papertape.asm programs/papertape.txt

coco: py/CocoTest.py verilog/CPU.v verilog/IOP.v verilog/CPUTestBench.v roms/microcode.txt programs/init.txt programs/papertape.txt
	python py/CocoTest.py

gui: py/ControlPanel.py verilog/CPU.v verilog/IOP.v verilog/CPUTestBench.v roms/microcode.txt programs/init.txt programs/papertape.txt
	python py/ControlPanel.py

run: vcd/CPUTestBench.vvp
	vvp vcd/CPUTestBench.vvp

all: verilog/CPU.v roms/microcode.asm vcd/CPUTestBench.vvp

test:
	python py/CompilerTest.py

clean:
	del vcd\CPUTestBench.vvp vcd\sim.vvp vcd\sigma.vcd vcd\CPUTestBench.vcd
	del programs\init.txt programs\papertape.txt roms\microcode.txt
