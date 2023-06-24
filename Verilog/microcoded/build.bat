
pushd .
cd roms
python Compiler.py
popd

iverilog -o vcd/CPUTestBench CPUTestBench.v
vvp vcd/CPUTestBench
