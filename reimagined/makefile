
test: py/Sigma7TB.py verilog/*.v
	python py/Sigma7TB.py

mon: py/Sigma7Mon.py verilog/*.v
	python py/Sigma7Mon.py

asm:
	python py/sigma7asm.py verilog/monitor.s7 -o py/monitor.hex -s

clean:
	del vcd\Sigma7TB.vvp
