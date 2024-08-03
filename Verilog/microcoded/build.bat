
python roms/Compiler.py roms/sigma.txt roms/sigma_microcode.txt

iverilog -o vcd/CPUTestBench CPUTestBench.v
vvp vcd/CPUTestBench
