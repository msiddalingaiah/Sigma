
pushd .
cd roms
python Compiler.py
popd

iverilog -o CPUTestBench CPUTestBench.v
vvp CPUTestBench
