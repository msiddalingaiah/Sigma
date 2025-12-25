
# Python 3.13 installed from the Microsoft store or winget fails with python313.dll: Access is denied.
# miniconda with Python 3.14 (latest) fails to install cocotb.
# miniconda with Python 3.13 works. Here are the steps I followed:

# Install miniconda
# conda create -n p3.13 python=3.13
# conda activate p3.13
# pip install cocotb
# (vscode only) ctrl+shift+P | Python: Select Interpreter | p3.13

from __future__ import annotations

import logging

import os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_tools.runner import get_runner
from cocotb.simtime import get_sim_time

OPCODES = ['NAO00', 'NAO01', 'LCFI', 'NAO03', 'CAL1', 'CAL2', 'CAL3', 'CAL4', 'PLW', 'PSW', 'PLM', 'PSM', 'NAO0C',
           'NAO0D', 'LPSD', 'XPSD', 'AD', 'CD', 'LD', 'MSP', 'NAO14', 'STD', 'NAO16', 'NAO17', 'SD', 'CLM', 'LCD',
           'LAD', 'FSL', 'FAL', 'FDL', 'FML', 'AI', 'CI', 'LI', 'MI', 'SF', 'S', 'NAO26', 'NAO27', 'CVS', 'CVA',
           'LM', 'STM', 'NAO2C', 'NAO2D', 'WAIT', 'LRP', 'AW', 'CW', 'LW', 'MTW', 'NAO34', 'STW', 'DW', 'MW', 'SW',
           'CLR', 'LCW', 'LAW', 'FSS', 'FAS', 'FDS', 'FMS', 'TTBS', 'TBS', 'NAO42', 'NAO43', 'ANLZ', 'CS', 'XW',
           'STS', 'EOR', 'OR', 'LS', 'AND', 'SIO', 'TIO', 'TDV', 'HIO', 'AH', 'CH', 'LH', 'MTH', 'NAO54', 'STH',
           'DH', 'MH', 'SH', 'NAO59', 'LCH', 'LAH', 'NAO5C', 'NAO5D', 'NAO5E', 'NAO5F', 'CBS', 'MBS', 'NAO62', 'EBS',
           'BDR', 'BIR', 'AWM', 'EXU', 'BCR', 'BCS', 'BAL', 'INT', 'RD', 'WD', 'AIO', 'MMC', 'LCF', 'CB', 'LB',
           'MTB', 'STFC', 'STB', 'PACK', 'UNPK', 'DS', 'DA', 'DD', 'DM', 'DSA', 'DC', 'DL', 'DST']

@cocotb.test()
async def sigma_test(dut):
    logging.getLogger("cocotb").setLevel(logging.WARNING)

    # Create a 100ns period clock driver on port `clock`
    clock = Clock(dut.clock, 100, unit="ns")
    # Start the clock. Start it low to avoid issues on the first RisingEdge?
    clock.start(start_high=True)
    dut.reset.value = 0
    await Timer(10, unit='ns')
    dut.reset.value = 1
    await Timer(100, unit='ns')
    dut.reset.value = 0

    for i in range(610):
        await RisingEdge(dut.clock)
        time = int(get_sim_time(unit="ns"))
        upc = int(dut.cpu.seq.pc.value)
        if dut.cpu.ende.value:
            o = int(dut.cpu.o.value)
            c = int(dut.cpu.c.value)
            c17 = (c >> 24) & 0x7f
            if OPCODES[c17] != 'WAIT':
                print(f"{time} ns, uPC: {upc:3x}, {OPCODES[c17]} ({c17:2x})")
            else:
                print(f"{time} ns, uPC: {upc:3x}, WAIT encountered.")
                break
    print("That's all folks!")


if __name__ == "__main__":
    proj_dir = os.getcwd().replace('\\', '/')
    sources = ["verilog/CPUTestBench.v", "verilog/CPU.v", "verilog/Sequencer.v", "verilog/IOP.v"]
    runner = get_runner("icarus")
    runner.build(
        sources=sources,
        hdl_toplevel="Sigma",
        build_dir="vcd",
        always=True,
        defines={"PROJ_DIR": proj_dir},
    )

    runner.test(hdl_toplevel="Sigma", test_module="CocoTest,", waves=True)
