"""
SDS/Xerox Sigma 7 Monitor — Interactive cocotb simulation module.

Runs the monitor program with Python handling console I/O:
  - Output: monitors tx_valid/tx_char signals, writes to stdout
  - Input:  reads stdin in a background thread, drives rx_data/rx_ready

Run via Makefile 'make mon' target.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
import threading
import sys
import os
import logging

# Suppress all cocotb logging — monitor output only
logging.getLogger("cocotb").setLevel(logging.CRITICAL)
logging.getLogger("cocotb.test").setLevel(logging.CRITICAL)
logging.getLogger("cocotb.regression").setLevel(logging.CRITICAL)


# ---------------------------------------------------------------------------
# Hex loader
# ---------------------------------------------------------------------------
async def load_hex(dut, hexfile):
    """Load a $readmemh hex file into memory via DUT handles."""
    addr = 0
    with open(hexfile) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('//'):
                continue
            if line.startswith('@'):
                addr = int(line[1:], 16)
            else:
                word = int(line, 16)
                byte_addr = addr * 4
                dut.sys.memory.mem[byte_addr + 0].value   = (word >> 24) & 0xFF
                dut.sys.memory.mem[byte_addr + 1].value   = (word >> 16) & 0xFF
                dut.sys.memory.mem[byte_addr + 2].value   = (word >>  8) & 0xFF
                dut.sys.memory.mem[byte_addr + 3].value   = (word >>  0) & 0xFF
                addr += 1


# ---------------------------------------------------------------------------
# Input thread — reads stdin without blocking the simulation
# ---------------------------------------------------------------------------
class ConsoleInput:
    def __init__(self):
        self._queue   = []
        self._lock    = threading.Lock()
        self._done    = False
        self._thread  = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        """Background thread: read stdin character by character."""
        try:
            import tty, termios
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            tty.setraw(fd)
            try:
                while True:
                    ch = sys.stdin.read(1)
                    if not ch:
                        break
                    if ch == '\x1d':    # Ctrl-] → clean exit (Ctrl-C still force-kills)
                        self._done = True
                        break
                    if ch == '\r':
                        ch = '\n'
                    with self._lock:
                        self._queue.append(ord(ch))
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            for line in sys.stdin:
                for ch in line:
                    if ch == '\x1d':
                        self._done = True
                        return
                    with self._lock:
                        self._queue.append(ord(ch))

    def get(self):
        """Return next character code or None if none available."""
        with self._lock:
            return self._queue.pop(0) if self._queue else None

    @property
    def done(self):
        return self._done


# ---------------------------------------------------------------------------
# Main monitor test
# ---------------------------------------------------------------------------
@cocotb.test()
async def run_monitor(dut):
    """Run the Sigma 7 monitor interactively."""

    cocotb.start_soon(Clock(dut.clock, 10, unit="ns").start())

    # Load monitor hex
    hexfile = os.path.join(os.path.dirname(__file__), 'monitor.hex')
    await load_hex(dut, hexfile)

    # Reset CPU
    dut.reset.value = 1
    for _ in range(4):
        await RisingEdge(dut.clock)
    dut.reset.value = 0

    # Print separator so monitor output is distinct from build noise
    sys.stdout.write("\r\n--- Sigma 7 Simulation (Ctrl-] to exit) ---\r\n\r\n")
    sys.stdout.flush()

    # Initialise console RX signals
    dut.sys.rx_ready.value = 0
    dut.sys.rx_data.value  = 0

    # Start input handler
    console_in = ConsoleInput()

    # Main loop — run until Ctrl-]
    rx_pending = False
    rx_char    = 0

    while True:
        await RisingEdge(dut.clock)

        # Check for clean exit
        if console_in.done:
            sys.stdout.write("\r\n[Exiting]\r\n")
            sys.stdout.flush()
            break

        # --- Output: capture tx_valid ---
        if int(dut.sys.tx_valid.value) == 1:
            ch = int(dut.sys.tx_char.value)
            sys.stdout.write(chr(ch))
            sys.stdout.flush()

        # --- Input: feed characters to CPU ---
        if rx_pending:
            if int(dut.sys.rx_read.value) == 1:
                dut.sys.rx_ready.value = 0
                dut.sys.rx_data.value  = 0
                rx_pending = False
        else:
            ch = console_in.get()
            if ch is not None:
                rx_char = ch
                dut.sys.rx_data.value  = rx_char
                dut.sys.rx_ready.value = 1
                rx_pending = True


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import os
    from cocotb_tools.runner import get_runner

    proj_dir = os.getcwd().replace('\\', '/')
    os.makedirs("vcd", exist_ok=True)
    files = ["Sigma7TB.v", "Sigma7System.v", "Sigma7CPU.v", "Memory.v", "Console.v", "BusArbiter.v", "IOProcessor.v"]
    sources = [f"verilog/{f}" for f in files]

    runner = get_runner("icarus")
    runner.build(
        sources=sources,
        hdl_toplevel="Sigma7TB",
        build_dir="vcd",
        always=True,
        defines={"PROJ_DIR": proj_dir},
    )
    runner.test(hdl_toplevel="Sigma7TB", test_module="Sigma7Mon,", waves=False)