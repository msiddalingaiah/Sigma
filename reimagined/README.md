# Sigma 7 CPU Implementation

A Verilog RTL implementation of the SDS/Xerox Sigma 7 CPU, a 32-bit mainframe
processor originally built with custom DTL (Diode-Transistor Logic) in the late 1960s.

## Reference Documents

- [CPU Design Reference](sigma7_cpu_design.md) — architecture overview, register descriptions, instruction formats, addressing modes, and condition code encoding
- [RTL Equations](sigma7_rtl.md) — register transfer level description of all implemented instructions, phase-by-phase
- [I/O and Monitor Plan](sigma7_io_plan.md) — console I/O architecture, RD/WD implementation, Python assembler, and monitor program development plan

## Architecture Highlights

- 32-bit big-endian (bit 0 = MSB throughout)
- Hardwired control unit with one-hot phase register (PCP4, PCP5, PREP1–3, EX1–EX5); EX2 self-loops for variable-length shift execution
- 16 × 32-bit user register file (RR)
- Internal registers: A (primary ALU input/result), B (ALU second operand; TOS scratch
  for push-down; future multiply/divide via B_ALU path), C (transparent memory latch),
  D (secondary ALU input from C_mux), O (opcode), R (register field), P (EA), Q (IA)
- B loads through C_mux (B_CMUX) for memory reads, or from alu_out (B_ALU) for
  multiply/divide — no direct bus_data_r path
- ALU shift operations: SHL1, SHR1, SHL4, SHR4 (logical, fill with 0s)
- P[25:31] serves as the shift loop counter — P±4 and P±16 count toward zero each step
- Synchronous memory interface (FPGA block RAM compatible)
- ALU with A and D as inputs; carry and overflow detection
- 4-bit CC register (CC1=carry, CC2=overflow, CC3=positive, CC4=negative)
- Address family decode (fa_w, fa_h, fa_b, fa_d, fa_imm) from opcode table structure
- Full indexed and indirect addressing via PREP1–PREP3 phase sequence
- Console I/O via RD/WD direct instructions (devices 0x1001, 0x1002)
- Push-down stack via PSW/PLW (doubleword-addressed Stack Pointer Doubleword in memory)
- EA 0–15 always resolves to the register file (RR), never to core memory — enabling register-to-register operations via normal memory-reference instructions

## Project Structure

```
Sigma7CPU.v       — CPU core (control unit, datapath, phase sequencer, ALU)
Memory.v          — Synchronous byte-addressable memory (512KB)
Sigma7System.v    — Top-level system (CPU + Memory + Console)
Console.v         — Console I/O ($fgetc/$fwrite simulation model)
Sigma7TB.v        — Verilog testbench wrapper for cocotb
Sigma7Sim.v       — Standalone simulation top-level (for interactive monitor)
Sigma7TB.py       — cocotb testbench (16 passing unit tests)
Sigma7Mon.py      — Interactive monitor runner (cocotb-based)
sigma7asm.py      — Two-pass Sigma 7 assembler (outputs $readmemh hex)
monitor.s7        — Monitor program source (Sigma 7 assembly)
monitor.hex       — Assembled monitor ($readmemh format, loaded by Memory.v)
```

## Running the Tests

```bash
# Compile
iverilog -o sim_tb -DPROJ_DIR='""' \
  Sigma7TB.v Sigma7System.v Sigma7CPU.v Memory.v Console.v

# Run (cocotb v2)
COCOTB_TEST_MODULES=Sigma7TB TOPLEVEL=Sigma7TB TOPLEVEL_LANG=verilog \
  PYGPI_PYTHON_BIN=$(which python3) \
  vvp -M$(python3 -c "import pathlib,cocotb; print(pathlib.Path(cocotb.__file__).parent/'libs')") \
      -mlibcocotbvpi_icarus sim_tb
```

Requires: Python 3, cocotb (`pip install cocotb`), Icarus Verilog.

## Running the Monitor

```bash
# Compile with monitor hex loaded
iverilog -o sim_mon -DMONITOR_HEX='"monitor.hex"' -DCONSOLE_INPUT \
  Sigma7Sim.v Sigma7System.v Sigma7CPU.v Memory.v Console.v

# Run interactively
vvp sim_mon
```

## Assembler Usage

```
python sigma7asm.py source.s7 -o output.hex [-s]   # -s prints symbol table
```

Assembly syntax:
```
* comment
LABEL   LW   R1, ADDR        ; memory-reference: op R, [X,] addr
        LI   R2, 42          ; immediate: op R, imm
        BCR  0, TARGET       ; branch: op R, addr [,X]
        BAL  R7, SUBROUTINE  ; branch and link
        PSW  R7, SPD         ; push R7 onto stack (save link register)
        PLW  R7, SPD         ; pop  R7 from stack (restore link register)
        S    R1, 4           ; shift R1 left by 4 (positive count=left, negative=right)
        S    R1, -4          ; shift R1 right by 4 (use negative immediate)
        ORG  0x26            ; set location counter (word address)
CONST   DC   0xDEADBEEF      ; define constant word
STR     DB   'Hello\r\n\0'   ; define bytes with escape sequences
        DS   4               ; define storage (4 words, zeroed)
NAME    EQU  42              ; define symbol
        LI   R6, BA(LABEL)   ; BA(x) = x<<2 (word address to byte address)
```

## GTKWave Tips

- Add `phase_name` signal, set **Data Format → ASCII** to see phase names
  (PCP4, PCP5, PREP1, PREP2, PREP3, EX1–EX5) in the waveform

## Monitor Program

The monitor implements a command loop with stack-based subroutine calling.
R7 is the sole link register, saved and restored via PSW/PLW on every call.
The Stack Pointer Doubleword (SPD) lives at word address 0x120 (initial TOS = 0x140).

Subroutines:
- **PUTCHAR** — write one character (R1) to console
- **GETCHAR** — read one character from console into R1 (no echo)
- **PUTS** — print null-terminated string at byte address R6
- **GETLINE** — read a line into buffer (R6=buffer addr); returns R3=char count,
  buffer null-terminated. Handles backspace with visual erase (BS-space-BS).

Boot sequence: print banner → command loop (prompt, read line, dispatch).
Current commands: `H` — help text.

## Implemented Instructions (18 passing tests)

| Instruction | Opcode | Description |
|-------------|--------|-------------|
| LCFI | 0x02 | Load Conditions and FP Immediate; all-zero = no-op/halt |
| PLW  | 0x08 | Pull Word from push-down stack (load RR[r], decrement TOS) |
| PSW  | 0x09 | Push Word onto push-down stack (increment TOS, store RR[r]) |
| S    | 0x25 | Shift (logical single register implemented; double/circular/arithmetic pending) |
| AI   | 0x20 | Add Immediate (20-bit sign-extended) |
| CI   | 0x21 | Compare Immediate |
| LI   | 0x22 | Load Immediate |
| AW   | 0x30 | Add Word |
| CW   | 0x31 | Compare Word |
| LW   | 0x32 | Load Word |
| STW  | 0x35 | Store Word |
| SW   | 0x38 | Subtract Word |
| EOR  | 0x48 | Logical Exclusive OR |
| OR   | 0x49 | Logical OR |
| AND  | 0x4B | Logical AND |
| LH   | 0x52 | Load Halfword (sign-extended) |
| STH  | 0x55 | Store Halfword |
| LB   | 0x72 | Load Byte (zero-extended) |
| STB  | 0x75 | Store Byte |
| BCR  | 0x68 | Branch on Conditions Reset (R=0 → unconditional) |
| BCS  | 0x69 | Branch on Conditions Set |
| BAL  | 0x6A | Branch and Link (subroutine call) |
| RD   | 0x6C | Read Direct (console input) |
| WD   | 0x6D | Write Direct (console output) |

All addressing modes implemented: direct, indexed (word/halfword/byte), indirect,
and indirect indexed. Index registers 1–7 only (X field is 3 bits).

## Register-File Address Mapping

Word addresses 0–15 always resolve to the current register block (RR[0]–RR[15]),
never to core memory. This is a fundamental architectural property — not an
addressing mode — and applies to all memory-reference instructions.

This enables register-to-register operations using ordinary load/store/arithmetic
instructions:

```
LW  R3, 1      ; R3 ← RR[1]          (register-to-register load)
STW R2, 4      ; RR[4] ← R2          (register-to-register store)
AW  R5, 1      ; R5 ← R5 + RR[1]    (register-to-register arithmetic)
STW R1, 2      ; RR[2] ← R1          (save a working copy)
```

**Implementation:** Two wires and one override at the end of the control block:
- `reg_access = (P[15:27] == 0)` — true when EA is 0–15
- `ea_data = reg_access ? RR[reg_addr] : bus_data_r` — plugs into C_mux so
  all load paths (C_load, A_CMUX, B_CMUX, D_sel) receive register data transparently
- Write override: when `cpu_write && reg_access`, set `reg_write=1` and clear
  `cpu_write` to suppress the memory bus write

No changes to any EX phase handlers — the distinction is entirely invisible to
the instruction control logic.

## S — Shift (logical, single register)

The S instruction uses the effective address itself (not a memory operand) to encode
the shift type and count. After PREP3, P holds the EA whose bit fields are:

- **P[21:23]:** shift type — 000=logical single (implemented), 001=logical double,
  010=circular single, 011=circular double, 100=arithmetic single, 101=arithmetic double
- **P[25]:** direction — 0=left (positive count), 1=right (negative count, two's complement)
- **P[26:31]:** count magnitude

**P as the loop counter:** P[25:31] is the 7-bit signed count. Each EX2 cycle
performs one shift step and adjusts P toward zero:

| Step | ALU op | P adjustment |
|------|--------|-------------|
| Left  4-bit | SHL4 | P ← P − 16 (P_DEC16) |
| Left  1-bit | SHL1 | P ← P − 4  (P_DEC4)  |
| Right 4-bit | SHR4 | P ← P + 16 (P_INC16) |
| Right 1-bit | SHR1 | P ← P + 4  (P_INC)   |

The loop uses 4-bit steps when `|count| ≥ 4` (`can_4bit = shift_count >= 4 || shift_count <= -4`)
and 1-bit steps for the remainder. Maximum iterations: 16 × 4-bit + 3 × 1-bit = 19 cycles.

**Phase sequence:**
```
EX1:   A ← RR[r]                     ; load register; no memory operand used
EX2:   if P[25:31]==0: → EX3          ; termination check at top of loop
       else: A←shift(A); P±=step; → EX2  ; self-loop
EX3:   RR[r]←A; CC←CC_ARITH(A); P_sel←P_Q; bus_addr←{Q,00}
EX4/ENDE
```

**Condition codes:** CC3/CC4 set from result (positive/negative). CC1/CC2 (parity of
bits shifted off, overflow) not yet implemented.

**Assembler:** `S R1, 4` (left 4), `S R1, -4` (right 4). Negative counts are
embedded as 7-bit two's complement in the address field bits 25–31.

## Push-Down Stack (PSW/PLW)

The Stack Pointer Doubleword (SPD) is a 64-bit structure in memory:
- **Word 0 bits 15–31:** 17-bit top-of-stack word address (TOS)
- **Word 1 bits 33–47:** 15-bit space count (free locations)
- **Word 1 bits 49–63:** 15-bit word count (words on stack)
- **Bit 32:** TS — trap-on-space inhibit
- **Bit 48:** TW — trap-on-word inhibit

Current implementation manages TOS only (word 0); space/word counts and
overflow trapping are not yet implemented.

**PSW timing (5 execution phases):**

| Phase | bus_addr | Action |
|-------|----------|--------|
| EX1 | SPD (default) | C_load; B←C_mux=SPD[0]; D←SPD[0]; A←RR[r] |
| EX2 | {B[15:31]+1, 00} | M[TOS+1] ← A (write value) |
| EX3 | {P[15:31], 00} | M[SPD] ← {15'b0, B[15:31]+1} (write new TOS) |
| EX4 | {Q, 00} | P ← Q |
| EX5/ENDE | — | ENDE |

**PLW timing (5 execution phases):**

| Phase | bus_addr | Action |
|-------|----------|--------|
| EX1 | SPD (default) | C_load; B←C_mux=SPD[0]; D←SPD[0] |
| EX2 | {B[15:31], 00} | (present TOS address; M[TOS] arrives in EX3) |
| EX3 | {P[15:31], 00} | C_load; A←C_mux=M[TOS]; M[SPD]←{15'b0,B[15:31]-1} |
| EX4 | {Q, 00} | RR[r]←A; CC←A; P←Q |
| EX5/ENDE | — | ENDE |

Note: the SPD write in PLW EX3 and the M[TOS] read from bus_data_r are
independent — bus_data_r carries M[TOS] from EX2's bus_addr regardless of
what is written via bus_data_w in the same cycle.

## Pending Instructions

Word: LCW, LAW | Halfword: AH, CH, SH, LCH, LAH, MTH | Byte: CB, MTB
Branches: BDR, BIR | Doubleword: LD, STD, AD, SD, CD, LCD, LAD
Shift modes: S logical double, circular single/double, arithmetic single/double; SF (floating-point shift)
Multiply/divide, floating point, SIO/TIO/HIO channel I/O
PSM/PLM (push/pull multiple), MSP (modify stack pointer)