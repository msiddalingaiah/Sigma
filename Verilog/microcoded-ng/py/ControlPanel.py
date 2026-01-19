
# Python 3.13 installed from the Microsoft store or winget fail with python313.dll: Access is denied.
# miniconda with Python 3.14 (latest) fails to install cocotb.
# miniconda with Python 3.13 works. Here are the steps I followed:

# Install miniconda
# conda create -n p3.13 python=3.13
# conda activate p3.13
# pip install cocotb
# (vscode only) ctrl+shift+P | Python: Select Interpreter | p3.13

from __future__ import annotations

import logging

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_tools.runner import get_runner
from cocotb.simtime import get_sim_time

import wx
import time
import os
import threading
import traceback
from dataclasses import dataclass
import queue

import Pipeline as pipe

OPCODES = ['NAO00', 'NAO01', 'LCFI', 'NAO03', 'CAL1', 'CAL2', 'CAL3', 'CAL4', 'PLW', 'PSW', 'PLM', 'PSM', 'NAO0C',
           'NAO0D', 'LPSD', 'XPSD', 'AD', 'CD', 'LD', 'MSP', 'NAO14', 'STD', 'NAO16', 'NAO17', 'SD', 'CLM', 'LCD',
           'LAD', 'FSL', 'FAL', 'FDL', 'FML', 'AI', 'CI', 'LI', 'MI', 'SF', 'S', 'NAO26', 'NAO27', 'CVS', 'CVA',
           'LM', 'STM', 'NAO2C', 'NAO2D', 'WAIT', 'LRP', 'AW', 'CW', 'LW', 'MTW', 'NAO34', 'STW', 'DW', 'MW', 'SW',
           'CLR', 'LCW', 'LAW', 'FSS', 'FAS', 'FDS', 'FMS', 'TTBS', 'TBS', 'NAO42', 'NAO43', 'ANLZ', 'CS', 'XW',
           'STS', 'EOR', 'OR', 'LS', 'AND', 'SIO', 'TIO', 'TDV', 'HIO', 'AH', 'CH', 'LH', 'MTH', 'NAO54', 'STH',
           'DH', 'MH', 'SH', 'NAO59', 'LCH', 'LAH', 'NAO5C', 'NAO5D', 'NAO5E', 'NAO5F', 'CBS', 'MBS', 'NAO62', 'EBS',
           'BDR', 'BIR', 'AWM', 'EXU', 'BCR', 'BCS', 'BAL', 'INT', 'RD', 'WD', 'AIO', 'MMC', 'LCF', 'CB', 'LB',
           'MTB', 'STFC', 'STB', 'PACK', 'UNPK', 'DS', 'DA', 'DD', 'DM', 'DSA', 'DC', 'DL', 'DST']

class CommandQueue(object):
    def __init__(self, q1 = queue.Queue(), q2 = queue.Queue()):
        self.q1 = q1
        self.q2 = q2

    def getReverseQueue(self):
        return CommandQueue(self.q2, self.q1)

    def readline(self):
        return self.q2.get()

    def writeline(self, line):
        self.q1.put(line)

commandQueue = CommandQueue()

@cocotb.test()
async def sigma_test(dut):
    logging.getLogger("cocotb").setLevel(logging.WARNING)
    # Create a 10us period clock driver on port `clock`
    # clock = Clock(dut.clock, 100, unit="ns")
    # Start the clock. Start it low to avoid issues on the first RisingEdge?
    # clock.start(start_high=True)

    dut.clock.value = 0
    dut.reset.value = 0
    await Timer(10, unit='ns')
    dut.reset.value = 1
    await Timer(90, unit='ns')
    dut.clock.value = 1
    await Timer(10, unit='ns')
    dut.reset.value = 0
    await Timer(90, unit='ns')
    dut.clock.value = 0
    await Timer(50, unit='ns')

    t = MainApp()
    t.start()

    line = commandQueue.readline()
    while line != "quit":
        await execute_line(commandQueue, dut, line)
        line = commandQueue.readline()

async def execute_line(commandQueue, dut, line):
    parts = line.split()
    if len(parts) == 0:
        return
    match parts[0]:
        case "reset" if len(parts) == 1:
            dut.reset.value = 0
            await Timer(10, unit='ns')
            dut.reset.value = 1
            await Timer(90, unit='ns')
            dut.clock.value = 1
            await Timer(10, unit='ns')
            dut.reset.value = 0
            await Timer(90, unit='ns')
            dut.clock.value = 0
            await Timer(50, unit='ns')
        case "clock" if len(parts) == 1:
            dut.clock.value = 1
            await Timer(50, unit='ns')
            dut.clock.value = 0
            await Timer(50, unit='ns')
        case "run" if len(parts) == 2:
            count = int(parts[1])
            while count > 0:
                dut.clock.value = 1
                await Timer(50, unit='ns')
                dut.clock.value = 0
                await Timer(50, unit='ns')
                count -= 1
                time = int(get_sim_time(unit="ns"))
                upc = int(dut.cpu.seq.pc.value)
                if dut.cpu.ende.value:
                    o = int(dut.cpu.o.value)
                    c = int(dut.cpu.c.value)
                    c17 = (c >> 24) & 0x7f
                    if OPCODES[c17] == 'WAIT':
                        print(f"{time} ns, uPC: {upc:3x}, WAIT encountered.")
                        break

        case "get" if len(parts) == 2:
            value = int(dut[parts[1]].value)
            commandQueue.writeline(f"{value}")

def run_verilog():
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
    runner.test(hdl_toplevel="Sigma", test_module="ControlPanel,", waves=False, extra_env={"PROJ_DIR": proj_dir})

class ButtonPanel(wx.Panel):
    def __init__(self, client, parent):
        super(ButtonPanel, self).__init__(parent)
        self.client = client
        self.parent = parent
        box = wx.StaticBox(self, label="Control")
        bsizer = wx.StaticBoxSizer(box, wx.VERTICAL)
        gs = wx.BoxSizer(wx.HORIZONTAL)
        self.reset = wx.Button(self, wx.ID_ANY, 'Reset')
        self.reset.Bind(wx.EVT_BUTTON, self.do_reset)
        gs.Add(self.reset, 0, wx.ALIGN_LEFT)

        self.step = wx.Button(self, wx.ID_ANY, 'Step')
        self.step.Bind(wx.EVT_BUTTON, self.do_step)
        gs.Add(self.step, 0, wx.ALIGN_LEFT)

        self.step = wx.Button(self, wx.ID_ANY, 'Run')
        self.step.Bind(wx.EVT_BUTTON, self.do_run)
        gs.Add(self.step, 0, wx.ALIGN_LEFT)

        self.clockCount = wx.TextCtrl(self, value="500", size=(50, -1))
        gs.Add(self.clockCount, 0, wx.ALIGN_LEFT)

        countLabel = wx.StaticText(self, label="clocks")
        gs.Add(countLabel, 0, wx.ALIGN_LEFT)

        self.quit = wx.Button(self, wx.ID_ANY, 'Quit')
        self.quit.Bind(wx.EVT_BUTTON, self.do_quit)
        gs.Add(self.quit, 0, wx.ALIGN_LEFT)
        bsizer.Add(gs, 0, wx.ALIGN_LEFT)
        main_sizer = wx.BoxSizer()
        main_sizer.Add(bsizer, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(main_sizer)

    def do_reset(self, event):
        self.client.writeline("reset")
        self.parent.update()

    def do_step(self, event):
        self.client.writeline("clock")
        self.parent.update()

    def do_run(self, event):
        value = self.clockCount.GetValue()
        if value.isnumeric():
            self.client.writeline(f"run {value}")
            self.parent.update()
        else:
            wx.MessageBox('clock value must be a positive integer', 'Info', wx.OK | wx.ICON_INFORMATION)

    def do_quit(self, event):
        self.client.writeline("quit")
        wx.Exit()

@dataclass
class RInfo:
    name: str
    label: str
    init: str
    format: str
    color: wx.Colour

class SignalPanel(wx.Panel):
    def __init__(self, label, client, names, columns, parent):
        super(SignalPanel, self).__init__(parent)
        self.client = client
        self.names = names
        self.registers = {}
        box = wx.StaticBox(self, label=label)
        bsizer = wx.StaticBoxSizer(box, wx.VERTICAL)
        box.SetForegroundColour(wx.Colour(255, 255, 0))
        self.SetBackgroundColour(wx.Colour(0, 0, 0))
        rows = int(len(names)/columns)
        if rows*columns < len(names):
            rows += 1
        gs = wx.FlexGridSizer(rows, 2*columns, 5, 5)
        font = wx.Font(20, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        ledFont = wx.Font(18, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, False, 'DSEG14 Classic')
        for r in names:
            if r is None:
                st = wx.StaticText(self, label = "")
                gs.Add(st, 0, wx.ALIGN_RIGHT)
                st = wx.StaticText(self, label = "")
                gs.Add(st, 0, wx.ALIGN_RIGHT)
            else:
                st = wx.StaticText(self, label = r.label)
                st.SetForegroundColour(wx.Colour(128, 128, 0))
                st.SetFont(font)
                gs.Add(st, 0, wx.ALIGN_RIGHT)

                reg = wx.StaticText(self, label = r.init)
                #reg.SetMinSize((100, -1))
                reg.SetForegroundColour(r.color)
                reg.SetFont(ledFont)
                gs.Add(reg, 0, wx.ALIGN_RIGHT)
                self.registers[r.name] = reg
        
        # for i in range(columns):
        #     gs.AddGrowableCol(2*i, 1)
        bsizer.Add(gs, 0, wx.CENTER)
        main_sizer = wx.BoxSizer()
        main_sizer.Add(bsizer, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(main_sizer)
        # self.update()

    def update(self):
        time.sleep(0.01)
        for r in self.names:
            if r is not None:
                reg = self.registers[r.name]
                self.client.writeline(f"get {r.name}")
                value = int(self.client.readline())
                fmt = "{:" + r.format + "}"
                reg.SetLabel(fmt.format(value))

class ControlPanel(wx.Frame):
    def __init__(self, client, parent=None):
        # Parent is None as it's the top-level window
        super(ControlPanel, self).__init__(parent, title="Sigma Control Panel", size=(500, 300))
        self.client = client

        gs = wx.BoxSizer(wx.VERTICAL)
        bp = ButtonPanel(self.client, self)
        gs.Add(bp, 0, wx.EXPAND | wx.ALL)
        red = wx.Colour(255, 0, 0)
        green = wx.Colour(0, 255, 0)
        blue = wx.Colour(0, 0, 255)
        cyan = wx.Colour(0, 255, 255)
        names = [
            RInfo("cpu.seq.pc", "μPC", "000", "03X", red),
            RInfo("cpu.pipeline", "μCode", "0000000000000000", "016X", red),
        ]
        self.seqPanel = SignalPanel("Sequencer", self.client, names, 2, self)
        gs.Add(self.seqPanel, 0, wx.EXPAND | wx.ALL)

        names = [
            None, RInfo("cpu.a", "A", "00000000", "08X", green), RInfo("cpu.b", "B", "00000000", "08X", green), None,
            RInfo("cpu.c", "C", "00000000", "08X", green), RInfo("cpu.d", "D", "00000000", "08X", green), None, None,
            None, RInfo("cpu.s", "Sum Bus", "00000000", "08X", blue), None, None,
            RInfo("cpu.p", "P", "00000", "05X", green),
            RInfo("cpu.q", "Q", "00000", "05X", green),
            RInfo("cpu.o", "O", "00", "02X", green),
            # RInfo("cpu.r", "R", "0", "01X", green),
            RInfo("cpu.cc", "CC", "0", "01X", green),
        ]
        self.intPanel = SignalPanel("Internal", self.client, names, 4, self)
        gs.Add(self.intPanel, 0, wx.EXPAND | wx.ALL)

        names = []
        for i in range(16):
            names.append(RInfo(f"cpu.rr[{i}]", f"R{i}", "00000000", "08X", cyan))
        self.regPanel = SignalPanel("Registers", self.client, names, 4, self)
        gs.Add(self.regPanel, 0, wx.EXPAND | wx.ALL)

        self.SetSizer(gs)
        self.Layout()
        self.Bind(wx.EVT_CLOSE, self.do_close)
        self.Fit()

    def do_close(self, event):
        self.client.writeline("quit")
        wx.Exit()

    def update(self):
        self.seqPanel.update()
        self.intPanel.update()
        self.regPanel.update()

class MainApp(threading.Thread):
    def run(self):
        client = commandQueue.getReverseQueue()
        try:
            fontDir = os.getenv("PROJ_DIR") + "/fonts"
            font = "DSEG14Classic-BoldItalic.ttf"
            wx.Font.AddPrivateFont(f"{fontDir}/{font}")
            app = wx.App(False) 
            frame = ControlPanel(client)
            frame.Show(True)
            app.MainLoop()
            wx._core._wxPyCleanup()
        except Exception as e:
            client.writeline("quit")
            print(traceback.format_exc())
            wx.Exit()

if __name__ == "__main__":
    run_verilog()
