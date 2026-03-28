# Sigma 7 CPU Implementation

A Verilog RTL implementation of the SDS/Xerox Sigma 7 CPU, a 32-bit mainframe processor originally built with custom DTL (Diode-Transistor Logic) in the late 1960s.

## Reference Documents

- [CPU Design Reference](sigma7_cpu_design.md) — architecture overview, register descriptions, instruction formats, addressing modes, and condition code encoding
- [RTL Equations](sigma7_rtl.md) — register transfer level description of all implemented instructions, phase-by-phase

## Architecture Highlights

- 32-bit big-endian (bit 0 = MSB throughout)
- Hardwired control unit with up to 4 PREP phases and up to 16 EX phases
- 16 × 32-bit user register file (RR), memory-mapped at word addresses 0–15
- Synchronous memory interface (FPGA block RAM style)
- PCP5 stable reset/halt state

## Project Structure

```
verilog/
  Sigma7CPU.v       — CPU core (control unit, datapath, phase sequencer)
  Memory.v          — Synchronous byte-addressable memory (512KB)
  Sigma7System.v    — Top-level system (CPU + Memory)
  Sigma7TB.v        — Verilog testbench wrapper for cocotb
  BusArbiter.v      — Bus arbiter (CPU/IOP priority)
  IOProcessor.v     — I/O processor stub
py/
  Sigma7TB.py       — cocotb testbench (Python runner, Icarus Verilog)
sigma7_sim.py       — Python functional simulator (105/105 tests passing)
```

## Progress Summary

**Completed and verified in simulation:**
- Boot sequence — PCP5 reset state asserts ENDE, fetches first instruction from word address 0x26 (byte 0x98)
- LCFI — Load Conditions and Floating-point Immediate (used as no-op on reset)
- LW — Load Word with direct addressing, correct P/Q dance and CC update
- Synchronous memory timing model fully worked out
- cocotb testbench infrastructure running under Icarus Verilog

**RTL documented, pending Verilog implementation:**
- Word arithmetic: AW, SW, CW, AI, CI, LI
- Word store: STW, LCW, LAW
- Halfword: AH, SH, CH, LH, STH, LCH, LAH, MTH
- Byte: LB, STB, CB, MTB
- Logical: AND, OR, EOR
- Doubleword: LD, STD, AD, SD, CD, LCD, LAD
- Branch: BCR, BCS, BAL, BDR, BIR
- Shift, multiply/divide, floating point, I/O