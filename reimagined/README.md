# Sigma 7 CPU Implementation

A Verilog RTL implementation of the SDS/Xerox Sigma 7 CPU, a 32-bit mainframe
processor originally built with custom DTL (Diode-Transistor Logic) in the late 1960s.

## Reference Documents

- [CPU Design Reference](sigma7_cpu_design.md) — architecture overview, register descriptions, instruction formats, addressing modes, and condition code encoding
- [RTL Equations](sigma7_rtl.md) — register transfer level description of all implemented instructions, phase-by-phase
- [I/O and Monitor Plan](sigma7_io_plan.md) — console I/O architecture, RD/WD implementation, Python assembler, and monitor program development plan

## Architecture Highlights

- 32-bit big-endian (bit 0 = MSB throughout)
- Hardwired control unit with one-hot phase register (PCP4, PCP5, PREP1–3, EX1–4)
- 16 × 32-bit user register file (RR)
- Synchronous memory interface (FPGA block RAM compatible)
- ALU with A and D as inputs; carry and overflow detection
- 4-bit CC register (CC1=carry, CC2=overflow, CC3=positive, CC4=negative)
- Address family decode (fa_w, fa_h, fa_b, fa_d, fa_imm) from opcode table structure
- Full indexed and indirect addressing via PREP1–PREP3 phase sequence
- Console I/O via RD/WD direct instructions (devices 0x1001, 0x1002)

## Project Structure

```
verilog/
  Sigma7CPU.v       — CPU core (control unit, datapath, phase sequencer, ALU)
  Memory.v          — Synchronous byte-addressable memory (512KB)
  Sigma7System.v    — Top-level system (CPU + Memory + Console)
  Console.v         — Console I/O ($fgetc/$fwrite simulation model)
  Sigma7TB.v        — Verilog testbench wrapper for cocotb
  BusArbiter.v      — Bus arbiter stub
  IOProcessor.v     — I/O processor stub
  monitor.s7        — Monitor banner program (Sigma 7 assembly source)
  monitor.hex       — Assembled monitor ($readmemh format)
py/
  Sigma7TB.py       — cocotb testbench (Python runner, Icarus Verilog)
sigma7asm.py        — Two-pass Sigma 7 assembler (outputs $readmemh hex)
```

## Running the Tests

```
python py/Sigma7TB.py
```

Requires: Python 3, cocotb, Icarus Verilog.

To enable interactive console input (e.g. running the monitor):

```
python py/Sigma7TB.py -DCONSOLE_INPUT
```

## Assembler Usage

```
python sigma7asm.py source.s7 -o output.hex [-s]   # -s prints symbol table
```

Assembly syntax:
```
* comment
LABEL   LW   R1, ADDR        ; memory-reference: op R, [X,] addr [,I]
        LI   R2, 42          ; immediate: op R, imm
        BCR  0, TARGET       ; branch: op R, addr [,X]
        BAL  R7, SUBROUTINE  ; branch and link
        ORG  0x26            ; set location counter (word address)
CONST   DC   0xDEADBEEF      ; define constant word
STR     DB   'Hello'         ; define bytes (null-terminated string)
        DS   4               ; define storage (4 words)
NAME    EQU  42              ; define symbol
        LI   R5, BA(LABEL)   ; BA(x) = x<<2 (byte address of word address)
```

## GTKWave Tips

- Add `phase_name` signal, set **Data Format → ASCII** to see phase names
  (PCP4, PCP5, PREP1, PREP2, PREP3, EX1–EX4) in the waveform

## Implemented Instructions (17 passing tests)

| Instruction | Opcode | Description |
|-------------|--------|-------------|
| LCFI | 0x02 | Load Conditions and FP Immediate; all-zero = no-op/halt |
| AI | 0x20 | Add Immediate (20-bit sign-extended) |
| CI | 0x21 | Compare Immediate |
| LI | 0x22 | Load Immediate |
| AW | 0x30 | Add Word |
| CW | 0x31 | Compare Word |
| LW | 0x32 | Load Word |
| STW | 0x35 | Store Word |
| SW | 0x38 | Subtract Word |
| EOR | 0x48 | Logical Exclusive OR |
| OR | 0x49 | Logical OR |
| AND | 0x4B | Logical AND |
| LH | 0x52 | Load Halfword (sign-extended) |
| STH | 0x55 | Store Halfword |
| LB | 0x72 | Load Byte (zero-extended) |
| STB | 0x75 | Store Byte |
| BCR | 0x68 | Branch on Conditions Reset (R=0 → unconditional) |
| BCS | 0x69 | Branch on Conditions Set |
| BAL | 0x6A | Branch and Link (subroutine call) |
| RD | 0x6C | Read Direct (console input) |
| WD | 0x6D | Write Direct (console output) |

All addressing modes implemented: direct, indexed (word/halfword/byte), indirect,
and indirect indexed. Index registers 1–7 only (X field is 3 bits).

## Pending Instructions

Word: LCW, LAW | Halfword: AH, CH, SH, LCH, LAH, MTH | Byte: CB, MTB
Branches: BDR, BIR | Doubleword: LD, STD, AD, SD, CD, LCD, LAD
Shifts, multiply/divide, floating point, SIO/TIO/HIO channel I/O