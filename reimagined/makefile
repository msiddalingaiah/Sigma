
vcd/Sigma7CPU.vvp: verilog/Sigma7CPU.v
	iverilog -g2009 -DPROJ_DIR=\".\" -o vcd/Sigma7TB.vvp verilog/Sigma7TB.v verilog/Sigma7CPU.v verilog/Memory.v verilog/BusArbiter.v verilog/IOProcessor.v verilog/Sigma7System.v

coco: py/Sigma7TB.py verilog/Sigma7TB.v
	python py/Sigma7TB.py

run: vcd/CPUTestBench.vvp
	vvp vcd/CPUTestBench.vvp

all: verilog/CPU.v

test:
	python py/CompilerTest.py

clean:
	del vcd\Sigma7TB.vvp
