
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
import socket
import threading
import traceback
from dataclasses import dataclass

HOST = "127.0.0.1"
PORT = 8001

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

    server = TCPServer()
    line = server.readline()
    while line != "quit":
        # print(line)
        await execute_line(server, dut, line)
        line = server.readline()
    server.close()

async def execute_line(server, dut, line):
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
        case "get" if len(parts) == 2:
            value = int(dut[parts[1]].value)
            server.writeline(f"{value}")

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
    runner.test(hdl_toplevel="Sigma", test_module="ControlPanel,", waves=False)

class TCPServer(object):
    def __init__(self, port=PORT):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((HOST, port))
        self.sock.listen()
        print(f"Waiting on port {port}")
        self.conn, addr = self.sock.accept()
        print(f"Server connected to {addr}")
    
    def readline(self):
        line = ""
        data = self.conn.recv(1024)
        while True:
            for b in data:
                if b == ord('\n'):
                    return line
                if b < 0x80 and b >= 0x20:
                    line += chr(b)
            data = self.conn.recv(1024)

    def writeline(self, line):
        line += '\n'
        self.conn.sendall(line.encode())

    def close(self):
        self.conn.close()
        self.sock.close()

class TCPClient(object):
    def __init__(self, host=HOST, port=PORT):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        n = 5
        while n > 1:
            try:
                self.sock.connect((HOST, PORT))
                print(f"Client connected to {host}")
                n = 0
            except Exception as e:
                print("Client connect failed, retrying...")
                time.sleep(1)
                n -= 1
                if n == 0:
                    raise e
    
    def readline(self):
        line = ""
        data = self.sock.recv(1024)
        while True:
            for b in data:
                if b == ord('\n'):
                    return line
                if b < 0x80 and b >= 0x20:
                    line += chr(b)
            data = self.sock.recv(1024)

    def writeline(self, line):
        line += '\n'
        self.sock.sendall(line.encode())

    def close(self):
        self.sock.close()

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
            RInfo("cpu.p", "P", "00000", "05X", green),
            RInfo("cpu.q", "Q", "00000", "05X", green),
            RInfo("cpu.o", "O", "00", "02X", green),
            RInfo("cpu.r", "R", "0", "01X", green),
            RInfo("cpu.b", "B", "00000000", "08X", green),
            RInfo("cpu.c", "C", "00000000", "08X", green),
            RInfo("cpu.a", "A", "00000000", "08X", green),
            RInfo("cpu.d", "D", "00000000", "08X", green),
            RInfo("cpu.s", "Sum", "00000000", "08X", blue),
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
        client = TCPClient()
        try:
            fontDir = "fonts"
            font = "DSEG14Classic-BoldItalic.ttf"
            wx.Font.AddPrivateFont(f"{fontDir}/{font}")
            app = wx.App(False) 
            frame = ControlPanel(client)
            frame.Show(True)
            app.MainLoop()
            wx._core._wxPyCleanup()
        except Exception as e:
            client.writeline("quit")
            client.close()
            print(traceback.format_exc())
            wx.Exit()

if __name__ == "__main__":
    t = MainApp()
    t.start()
    run_verilog()
