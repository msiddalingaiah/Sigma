
@echo off

iverilog -o vcd/CPUTestBench CPUTestBench.v

if %ERRORLEVEL% == 0 goto :next
goto :endofscript

:next
vvp vcd/CPUTestBench

:endofscript
