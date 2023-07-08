@echo off

iverilog -o vcd/Multiplier Multiplier.v

if %ERRORLEVEL% == 0 goto :next
goto :endofscript

:next
vvp vcd/Multiplier
echo Success

:endofscript
