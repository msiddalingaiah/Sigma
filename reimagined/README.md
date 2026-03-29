# Sigma 7 CPU Implementation

A Verilog RTL implementation of the SDS/Xerox Sigma 7 CPU, a 32-bit mainframe processor originally built with custom DTL (Diode-Transistor Logic) in the late 1960s.

## Reference Documents

- [CPU Design Reference](sigma7_cpu_design.md) — architecture overview, register descriptions, instruction formats, addressing modes, and condition code encoding
- [RTL Equations](sigma7_rtl.md) — register transfer level description of all implemented instructions, phase-by-phase
- [Prep Phase Optimization](sigma7_prep_optimization.md) — proposed restructuring of ENDE and prep phases to absorb instruction load into ENDE, with cycle count analysis and open questions

## Architecture Highlights

- 32-bit big-endian (bit 0 = MSB throughout)
- Hardwired control unit with PCP5 stable reset/halt state, up to 4 PREP phases and up to 16 EX phases
- 16 × 32-bit user register file (RR), memory-mapped at word addresses 0–15
- Synchronous memory interface (FPGA block RAM style)
- Sel-based control signals (0=hold, non-zero=load from source)
- ALU with carry and overflow detection
- 4-bit CC register (CC1=carry, CC2=overflow, CC3=positive, CC4=negative)

## Project Structure

```
verilog/
  Sigma7CPU.v       — CPU core (control unit, datapath, phase sequencer, ALU)
  Memory.v          — Synchronous byte-addressable memory (512KB)
  Sigma7System.v    — Top-level system (CPU + Memory)
  Sigma7TB.v        — Verilog testbench wrapper for cocotb
  BusArbiter.v      — Bus arbiter (CPU/IOP priority)
  IOProcessor.v     — I/O processor stub
py/
  Sigma7TB.py       — cocotb testbench (Python runner, Icarus Verilog)
sigma7_sim.py       — Python functional simulator (105/105 tests passing)
gtkwave/
  phase.txt         — GTKWave translate filter for phase_enc signal
```

## GTKWave Tips

- Add `phase_name` signal and set **Data Format → ASCII** to see phase names (PCP5, PREP1, etc.) directly in the waveform

## Progress Summary

**Implemented and verified in simulation (6 passing tests):**

| Instruction | Description | Test |
|-------------|-------------|------|
| LCFI | Load Conditions and FP Immediate (no-op on reset) | test_boot_sequence |
| LI | Load Immediate (20-bit sign-extended) | test_li |
| LW | Load Word (direct addressing) | test_lw |
| STW | Store Word | test_stw |
| AW | Add Word | test_word_arithmetic |
| SW | Subtract Word | test_word_arithmetic |
| AND | Logical AND | test_word_arithmetic |
| OR | Logical OR | test_word_arithmetic |
| EOR | Logical Exclusive OR | test_word_arithmetic |
| CW | Compare Word (CC update only) | test_cw |

**Key design decisions proven in simulation:**
- PCP5 asserts ENDE immediately on reset release — fetches first instruction cleanly
- Synchronous memory timing: address on cycle N → data on cycle N+1
- P/Q dance: Q saves next instruction address in PREP1, P restored from Q before ENDE
- Transparent C latch routes all memory data to datapath
- `bus_data_r` used directly in PREP1 to break combinatorial loop through `rr_access`

**RTL documented, pending Verilog implementation:**
- Immediate arithmetic: AI, CI
- Word: LCW, LAW
- Branch: BCR, BCS, BAL, BDR, BIR (CC register now ready)
- Halfword: AH, SH, CH, LH, STH, LCH, LAH, MTH
- Byte: LB, STB, CB, MTB
- Doubleword: LD, STD, AD, SD, CD, LCD, LAD
- Shift, multiply/divide, floating point, I/O