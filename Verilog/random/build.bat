@echo off

iverilog -o vcd/OneHot OneHot.v

if %ERRORLEVEL% == 0 goto :next
goto :endofscript

:next
vvp vcd/OneHot
echo Success

:endofscript
