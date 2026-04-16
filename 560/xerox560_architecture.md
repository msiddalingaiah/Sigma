# Xerox 560 CPU Architecture Reference

**Status:** Reconstructed from fragmentary field service documentation, RTL descriptions,
and cross-reference with the Xerox/SDS Sigma 9 Reference Manual (901733A, October 1970).
This document should be treated as a best-effort reconstruction, not an authoritative primary source.

---

## 1. Overview

The Xerox 560 was a time-sharing computer produced by Xerox Data Systems (XDS) in the
early 1970s, derived from the Scientific Data Systems (SDS) Sigma series. Xerox acquired
SDS in 1969 and continued development of the Sigma line under the XDS brand.

The 560 is architecturally compatible with the Sigma 9: it executes the same instruction
set and runs the same operating systems (primarily CP-V). The key difference is
implementation — the 560 uses faster ECL logic and a higher-speed control store ROM,
yielding a 180 ns microcycle versus the Sigma 9's slower timing.

The 560 ran CP-V (Control Program Five), a time-sharing OS capable of supporting
approximately 40 simultaneous users alongside real-time data acquisition workloads.

---

## 2. Key Parameters

| Parameter | Value | Notes |
|---|---|---|
| Microcycle time | 180 ns | One micro-instruction per cycle |
| Control store size | 2048 × 60 bits | ~2K micro-instructions |
| Microcode style | Horizontal | No vertical decoding |
| Word size | 32 bits | |
| Address space | 17-bit virtual (word) | 128K words virtual |
| Physical memory | 18-bit (word) | 256K words max |
| Page size | 512 words (2 KB) | Virtual address bits [16:9] index MAP RAM |
| Register file | 16 × 32-bit GPRs | 4 blocks of 16 (64 registers total) |
| Floating point | Hexadecimal (IBM-style) | Base-16 exponent |
| Memory latency | ~900 ns | 5 microcycles |

---

## 3. Board-Level Architecture

The CPU is organized across several physical boards in a card cage. Two naming conventions
appear in the source documentation (functional names from architectural docs, physical
designators from field service docs). Both are listed where known.

| Physical Board | Functional Name | Contents |
|---|---|---|
| A2 / A3 | AR1 | 64 × 32-bit register file (4 blocks × 16 GPRs), REG_BLK select logic |
| A5 | AR2 | 33-bit ECL ALU, A/B input muxes |
| A6 | — | MAR, IA, PSW latches, 24-bit address adder, fast incrementer. Also contains 3-input adder for double-indexed addressing |
| A7 | — | 32-bit 4:1 byte mux (BYTE_SEL_LATCH → selects byte from MDR word), sign-extend block |
| C1 | — | IA counter, trap vector mux |
| C2 | CTL1 | 2K × 60 control store ROM, micro-PC, branch mux, IRQ logic, dispatch ROM (128 × 12) |
| C3 | — | IRQ_PENDING OR tree, IRQ_INHIBIT flip-flop |
| C4 | — | TEMP0, TEMP1 scratch registers |
| M1 / M2 | MAP | 256 × 16 ECL MAP RAM, permission logic. Receives word address MAR[23:2] only — MAP is word-granular, not byte-granular |

### Internal Buses

- **A_BUS** (32-bit): Left ALU input
- **B_BUS** (32-bit): Right ALU input
- **D_BUS** (32-bit): ALU output, connects to register file write port and MDR

---

## 4. Micro-Instruction Format

Each micro-instruction is 60 bits wide. Fields drive hardware directly with no
vertical decoding — every bit controls a specific mux, gate, or register enable.

| Bits | Field | Function |
|---|---|---|
| 0–3 | ALU_FUNC | ADD, SUB, AND, OR, XOR, PASS_A, PASS_B, INC |
| 4–5 | ALU_CIN | Carry-in control for add/subtract |
| 6–10 | A_MUX | Left ALU input: R0–R15, PSD, Map Data, Memory Data, 0 |
| 11–15 | B_MUX | Right ALU input: R0–R15, Displacement, 0, −1, etc. |
| 16–19 | DEST | ALU output destination: R0–R15, PSD, MAR, MDR, Temp |
| 20–22 | SHIFTER | None, Left Logical 1–4, Right Arith, Right Logical, Byte Swap |
| 23–25 | CC_LOAD | Load CC from ALU result / force 0 / force 1 / hold |
| 26–28 | MEM_CTRL | None, Read, Write, IFETCH, MAP_XLATE |
| 29–31 | REG_BLK | Active 16-register block select (0–3 in base config) |
| 32–35 | NEXT_ADDR | Base address for next micro-instruction |
| 36–37 | BRANCH_TYPE | No branch / Branch if ALU=0 / Branch if CC / Branch if IRQ |
| 38–41 | BRANCH_MASK | CC mask or IRQ level to test |
| 42–47 | MISC | LPSD pulse, XPSD pulse, Privilege check, Trap, Halt |
| 48–59 | SPARE/Parity | Unused bits + parity |

A single microcycle can simultaneously: read two registers, perform an ALU operation,
shift the result, write a register, initiate a memory read, and conditionally branch —
all in 180 ns.

### Branch Mux Inputs (Board C2)

The microsequencer branch mux has approximately 16 test inputs selectable via BRANCH_TYPE:

- `ZERO_FLAG` — ALU result was zero
- `CC1`–`CC4` — Condition code bits
- `IRQ_PENDING` — Interrupt request pending
- `INDIRECT_BIT` — I-bit of current instruction word (used for AW indirect chaining)
- `ALU_CARRY` — Carry/borrow out of ALU

---

## 5. Register File

- **Physical size:** 64 × 32-bit words — 4 blocks of 16 registers (boards A2/A3)
- **Logical view:** 4 banks of 16 general-purpose registers (R0–R15)
- **Active bank:** Selected by PSW field (2-bit field → 4 banks)
- **Bank switching:** Changing the register block select field instantly re-maps R0–R15
  to a different 16-word slice. No push/pop to memory needed.

**Source:** Authoritative — confirmed directly by the Xerox 560 Reference Manual
(903076A), which states "Four blocks of 16 general-purpose registers."
The Sigma 9 had up to 32 blocks; the 560 has exactly 4.

### Base Configuration (Single Block)

For this implementation, only one register block is installed. Register block select
is always 0. Register file behaves as a simple 16 × 32-bit array.

### Special Registers (by convention)

| Register | Convention |
|---|---|
| R14 | Stack pointer |
| R15 | CAL return linkage / syscall number |

### Scratch Registers

- **TEMP0, TEMP1** — 32-bit scratch registers on board C4, used by XPSD and CAL
  to hold the new PSD during the doubleword swap. Not architecturally visible to software.

---

## 6. Program Status Doubleword (PSD)

The PSD is a 64-bit register (board A6) holding all CPU state. A single XPSD instruction
atomically swaps the entire PSD with a doubleword in memory, enabling context switches,
interrupts, and syscalls in ~1.44 μs.

| Bits | Field | Notes |
|---|---|---|
| 63:48 | Reserved / mode bits / interrupt inhibits | |
| 47:40 | Interrupt mask | |
| 39:34 | Register block select | Switches R0–R15 instantly |
| 33:32 | REG_BLK for XPSD temp | Upper 2 bits of register number |
| 31 | Slave mode | 1 = slave (user), 0 = master (OS) |
| 30:28 | CC4, CC3, CC2, CC1 | Condition codes |
| 27:24 | Reserved | |
| 23:0 | IA | Instruction Address (virtual) |

---

## 7. Memory System

### Effective Address Calculation

The EA calculation is common to all memory instructions. It produces a **24-bit byte
address** (following Sigma 9 convention in the RTL documents, though the 560's virtual
space may only use the lower 19 bits — see address space note below):

```
EA[23:0] = DISP_sext + (X==0 ? 0 : R[X])
```

For **word instructions** (LW, STW, AW, etc.):
- EA[1:0] must be `00` — misalignment fires a SPECIFICATION trap
- MAR ← EA[23:0] directly (word-aligned by contract)

For **byte instructions** (LB, STB, etc.):
- EA[1:0] → BYTE_SEL_LATCH (board A7) — selects which byte of the word
- MAR ← {EA[23:2], 2'b00} — word address (low 2 bits cleared)
- No alignment trap — any byte address is valid

For **halfword instructions** (LH, STH, etc.):
- EA[1] must be `0` — halfword alignment required
- EA[1:0] → selects upper or lower halfword

#### Big-Endian Byte Ordering

| EA[1:0] | Byte selected | Word bits |
|---|---|---|
| 00 | Most significant | [31:24] |
| 01 | Second | [23:16] |
| 10 | Third | [15:8] |
| 11 | Least significant | [7:0] |

Low address = most significant byte (IBM 360 / big-endian convention).

#### Double Indexing (Sigma 9 feature)

`LB R,addr(X,Y)` computes EA = addr + R[X] + R[Y]. Board A6 has a 3-input adder
for this. Whether the 560 supports double indexing requires verification.

### Virtual Address Space

**Source:** Authoritative — confirmed by Xerox 560 Reference Manual (903076A).

- **17-bit virtual word address** → 128K word virtual space
- **19-bit virtual byte address** (17-bit word address + 2-bit byte select)
- **Page size: 512 words** (2 KB) — confirmed by manual
- Virtual word address bits [16:9] (8 bits) index the MAP RAM → **256 virtual pages**
- Virtual word address bits [8:0] (9 bits) are the page offset within a 512-word page
- Physical memory maximum: 256K words → 512 physical pages → 9-bit physical page number

**Address width note:** The RTL source documents use 24-bit EA throughout (Sigma 9
convention). The 560 likely only uses the lower 19 bits for byte addressing. The
functional mechanism is identical; upper bits of the 24-bit EA are zero on a 560.

### MAP RAM (Boards M1/M2)

- **256 × 16-bit** ECL RAM
- Indexed by virtual word address bits [16:9] (8-bit page number)
- MAP receives **MAR[23:2]** only (word address) — it has no visibility of byte offset
- 4 bytes within a word always share the same permissions; byte-granular protection
  is not possible

#### Physical Address Formation

```
word_addr[16:0]  = { MAP_RAM[vaddr[16:9]][8:0],   // 9-bit PPN
                      vaddr[8:0] }                   // 9-bit page offset
physical_addr    = { word_addr, BYTE_SEL }           // 19-bit byte addr
```

#### Permission Bits

| Bit | Meaning |
|---|---|
| [2] | Read permission (R) |
| [1] | Write permission (W) |
| [0] | Slave-mode write protect |

*Note: Exact permission bit positions require verification against the 560 Reference
Manual Chapter 2. Values above are inferred.*

Permission checks occur in parallel with physical address formation and trap before
the memory access completes if violated.

### Simplification for This Implementation

MAP RAM is bypassed. All virtual addresses are treated as physical addresses:
```verilog
assign physical_addr = virtual_addr[18:0]; // Identity mapping — replace later
```

---

## 8. Instruction Set

Opcodes are 7-bit values in hex (from Xerox 560 Reference Manual 903076A, authoritative,
and cross-referenced with Sigma 9 Reference Manual 901733A). The RTL source documents
used octal notation with values that do not directly correspond; the manual hex values
are used throughout.

### Instruction Format (32-bit word)

| Bits | Field | Width |
|---|---|---|
| 31:25 | OPCODE | 7 bits |
| 24:21 | R (destination/source register) | 4 bits |
| 20:17 | X (index register; 0 = no index) | 4 bits |
| 16 | I (indirect bit) | 1 bit |
| 15:0 | DISP (17-bit signed displacement, bits 15:0 + I) | 17 bits |

Note: IR[0] doubles as the I (indirect) bit and the LSB of displacement.

### Implemented Instructions

| Mnemonic | Opcode (hex) | Cycles | Time | Description |
|---|---|---|---|---|
| LW | 32 | 3 | 0.54 μs | Load Word |
| STW | 35 | 3 | 0.54 μs | Store Word |
| AW | 30 | 3–5+ | 0.54–0.90 μs+ | Add Word (with indirect) |
| BDR | 64 | 3 | 0.54 μs | Branch on Decrement Register |
| FAS | 3D | 10–15 | 1.80–2.70 μs | Floating Add Short |
| XPSD | 0F | 8 | 1.44 μs | Exchange Program Status Doubleword |
| CAL1 | 04 | 9 | 1.62 μs | Call 1 (syscall) |
| CAL2 | 05 | 9 | 1.62 μs | Call 2 |
| CAL3 | 06 | 9 | 1.62 μs | Call 3 |
| CAL4 | 07 | 9 | 1.62 μs | Call 4 |
| DW | 1E | 36 | 6.48 μs | Divide Word (non-restoring, 32-bit) |
| HALT | 00 | ∞ | — | Halt (loops FETCH0) |

All other opcodes: unimplemented instruction trap.

### AW Addressing Modes

| Mode | Cycles | Time |
|---|---|---|
| AW R,addr (direct) | 3 | 0.54 μs |
| AW R,addr(X) (indexed) | 3 | 0.54 μs |
| AW R,addr* (indirect) | 4 | 0.72 μs |
| AW R,addr(X)* (indexed + indirect) | 5 | 0.90 μs |
| Each additional indirect level | +2 | +0.36 μs |

Multi-level indirect chains loop until the I-bit of the fetched pointer word is clear,
or a watchdog timer fires (hardware limit ~256 levels).

---

## 9. Instruction RTL Descriptions

### 9.1 Instruction Fetch (FETCH0–FETCH2)

Every instruction begins and ends here. FETCH0 is at microcode address 0x000.

```
FETCH0:
  MAR ← IA
  MEM_READ ← 1
  IR ← 0

FETCH1:
  // MAP translation (bypassed in this implementation)
  // Wait state for memory

FETCH2:
  IR ← MDR
  OPCODE ← IR[31:25]
  IR.R   ← IR[24:21]
  IR.X   ← IR[20:17]
  IR.I   ← IR[16]
  IR.DISP← IR[15:0]
  if (IRQ_PENDING && !IRQ_INHIBIT) μPC ← IRQ_ENTRY
  else μPC ← DISPATCH[OPCODE]
```

Total: 3 cycles = 0.54 μs. IRQ is sampled only at FETCH2; all instructions are
non-interruptible once dispatched.

The dispatch table (128 × 12-bit PROM on board C2) maps each 7-bit opcode to a
12-bit microcode start address.

### 9.2 Load Word (LW)

```
Cycle 1: // EA calculation
  A_BUS ← (X==0) ? 0 : R[X]
  B_BUS ← DISP_sext
  MAR   ← A_BUS + B_BUS

Cycle 2: // MAP + memory read (MAP bypassed)
  MEM_READ ← 1

Cycle 3: // Writeback + advance
  R[IR.R] ← MDR
  IA ← IA + 1
  μPC ← FETCH0
```

### 9.3 Store Word (STW)

```
Cycle 1: // EA calculation
  A_BUS ← (X==0) ? 0 : R[X]
  B_BUS ← DISP_sext
  MAR   ← A_BUS + B_BUS

Cycle 2: // MAP + permission check (W bit); load MDR
  MDR      ← R[IR.R]
  MEM_READ ← 0  // Write path

Cycle 3: // Write + advance
  MEM_WRITE ← 1
  IA ← IA + 1
  μPC ← FETCH0
```

### 9.4 Add Word (AW) — Indexed + Indirect

```
Cycle 1: // EA calculation
  A_BUS ← (X==0) ? 0 : R[X]
  B_BUS ← DISP_sext
  MAR   ← A_BUS + B_BUS

Cycle 2: // Read pointer from EA
  MEM_READ ← 1

Cycle 3: // Pointer arrives; re-issue as address
  MAR ← MDR   // Indirect address (already virtual)

Cycle 4: // Read actual operand
  MEM_READ ← 1

Cycle 5: // Add and writeback
  A_BUS  ← R[IR.R]
  B_BUS  ← MDR
  ALU_OP ← ADD
  R[IR.R] ← ALU_OUT
  if (ALU_OVERFLOW) PSD.CC4 ← 1
  PSD.CC[1:3] ← sign(ALU_OUT)
  IA ← IA + 1
  μPC ← FETCH0

// Optional: if fetched pointer word has I-bit set, loop Cycles 3–4 (+2 cycles per level)
```

### 9.5 Branch on Decrement Register (BDR)

```
Cycle 1: // Decrement register
  A_BUS    ← R[IR.R]
  B_BUS    ← 32'h00000001
  ALU_OP   ← SUB
  R[IR.R]  ← ALU_OUT
  ZERO_FLAG← (ALU_OUT == 0)

Cycle 2: // Compute branch target EA
  A_BUS ← (X==0) ? 0 : R[X]
  B_BUS ← DISP_sext
  MAR   ← A_BUS + B_BUS

Cycle 3: // Conditional branch (Option A: datapath mux, not μPC branch)
  if (!ZERO_FLAG) IA ← MAR    // Branch taken: R != 0
  else            IA ← IA + 1 // Fall through: R == 0
  μPC ← FETCH0
```

Always 3 cycles regardless of branch outcome. EA is computed even if unused.

### 9.6 Floating Add Short (FAS)

```
Cycles 1–3: Fetch operand B from memory (same as LW)
  Cyc1: MAR ← R[X] + DISP
  Cyc2: MAP + MEM_READ
  Cyc3: TB ← MDR; TA ← R[IR.R]

FAS_ALIGN:
  Cyc4: EA ← TA[30:24]; EB ← TB[30:24]   // Exponents
        SA ← TA[31];    SB ← TB[31]       // Signs
        FA ← {1'b1, TA[23:0]}             // Fraction A (hidden bit inserted)
        FB ← {1'b1, TB[23:0]}             // Fraction B (hidden bit inserted)

  Cyc5: if (EA == EB) goto ADD_FRAC
        if (EA > EB) {
            SHIFT_AMT ← EA - EB; EXP ← EA
            FB ← (SHIFT_AMT > 6) ? 0 : FB >> (4*SHIFT_AMT)
        } else {
            SHIFT_AMT ← EB - EA; EXP ← EB
            FA ← (SHIFT_AMT > 6) ? 0 : FA >> (4*SHIFT_AMT)
        }

FAS_ADD_FRAC:
  Cyc6: if (SA == SB) { FRES ← FA + FB; SRES ← SA; }
        else {
            if (FA >= FB) { FRES ← FA - FB; SRES ← SA; }
            else          { FRES ← FB - FA; SRES ← SB; }
        }
        if (FRES == 0) goto ZERO_RESULT

FAS_NORMALIZE:
  Cyc7: if (FRES[24]) { FRES >>= 4; EXP++; goto PACK; }  // Carry out
  Cyc8: if (FRES[23:20] != 0) goto PACK    // Already normalized
        if (EXP == 0) goto UNDERFLOW
        FRES <<= 4; EXP--;
        goto Cyc8   // Loop; max 6 iterations

FAS_PACK:
  Cyc9: if (EXP > 127) goto OVERFLOW_TRAP
        RESULT ← {SRES, EXP[6:0], FRES[22:0]}
  Cyc10: R[IR.R] ← RESULT
         CC ← sign(RESULT)
         IA ← IA + 1; μPC ← FETCH0

ZERO_RESULT:
  R[IR.R] ← 0; CC ← EQ; IA ← IA + 1; μPC ← FETCH0

OVERFLOW_TRAP / UNDERFLOW:
  Trap to FP exception vector via XPSD.
  Underflow: result = 0 if traps masked.
```

**Cycle count:** 10 cycles (best case, operands aligned and normalized) to ~15 cycles
(worst case, 6 normalization iterations). Time: 1.80–2.70 μs.

**Note:** Shift alignment is in units of 4 bits (one hex digit) per exponent step,
consistent with IBM-style hexadecimal floating point. Up to 3 bits of precision may
be lost per operation due to alignment.

### 9.7 Exchange Program Status Doubleword (XPSD)

The mechanism for all context switches, interrupts, and syscalls.

```
Cycle 1: // EA calculation
  MAR ← (X==0) ? DISP_sext : R[X] + DISP_sext

Cycles 2–4: // Read NEWPSD from [EA] and [EA+1]
  Cyc2: MAP + MEM_READ (addr EA)
  Cyc3: TEMP0 ← MDR; MAR ← MAR + 1; MEM_READ ← 1
  Cyc4: TEMP1 ← MDR

Cycles 4–5: // Write OLDPSD to [EA] and [EA+1]
  Cyc4: MAR ← MAR - 1; MDR ← PSD[31:0]
        Check W permission; MEM_WRITE ← 1
  Cyc5: MAR ← MAR + 1; MDR ← PSD[63:32]; MEM_WRITE ← 1

Cycle 6: // Block interrupts before PSD changes
  IRQ_INHIBIT ← 1

Cycle 7: // Load NEWPSD word 0 — CRITICAL CYCLE
  PSD[31:0] ← TEMP0
  // Simultaneously:
  REG_BLK   ← TEMP0[39:34]  // Register block switches HERE
  SLAVE_MODE← TEMP0[31]
  CC[4:1]   ← TEMP0[30:27]

Cycle 8: // Load NEWPSD word 1, re-enable interrupts
  PSD[63:32] ← TEMP1
  IRQ_INHIBIT ← 0
  μPC ← FETCH0  // Fetch from NEW IA using NEW REG_BLK
```

**Total: 8 cycles = 1.44 μs.**

Key properties:
- Atomicity: IRQ_INHIBIT set in Cycle 6 prevents half-swapped PSD from being interrupted
- Trap during write (Cycle 4): TRAP_XPSD_PARTIAL handler cleans up TEMP0/TEMP1 and restarts
- Register block switch in Cycle 7 takes effect immediately; Cycle 8 already uses new block

### 9.8 CAL1–CAL4 (Supervisor Calls)

CAL instructions are XPSD with a forced vector address and R15 preload.

```
Cycle 1: // Load R15 with return linkage
  R[15] ← {CAL_ID[7:0], 8'h00, PSD.IA + 1}
  // CAL_ID: CAL1=01, CAL2=02, CAL3=03, CAL4=04

Cycle 2: // EA calculation + force vector address
  MAR ← (X==0) ? DISP_sext : R[X] + DISP_sext
  MAR[7:0] ← {5'b01000, IR[27:25]}  // Forces X'40'–X'43'

Cycles 3–9: // Identical to XPSD cycles 2–8
```

**Total: 9 cycles = 1.62 μs.**

All four CALs dispatch to the same microcode entry (CAL_ENTRY). The IR[27:25] field
distinguishes CAL1–CAL4 and selects the forced vector.

#### Vector Table Layout

| Address | Contents |
|---|---|
| X'40'–X'41' | CAL1 OS entry PSD |
| X'42'–X'43' | CAL1 user return PSD |
| X'44'–X'47' | CAL2 similarly |
| X'48'–X'4B' | CAL3 similarly |
| X'4C'–X'4F' | CAL4 similarly |
| X'50'–X'51' | IRQ save PSD |
| X'52'–X'53' | IRQ return PSD |

#### Return from CAL

OS executes `XPSD X'42'(0)` or `LPSD X'42'(0)`. This loads the saved user PSD,
restoring IA = R15[23:0] (original IA+1), slave mode, and register block.

### 9.9 Divide Word (DW)

The slowest integer instruction. Uses non-restoring division, 1 bit per microcycle
for 32 iterations. Opcode hex 1E (octal 036 in RTL source docs).

**Operands:** 64-bit dividend `{R, R+1}` ÷ M[EA]. Quotient → R, Remainder → R+1.
R must be even (R0/R1, R2/R3, etc.).

**Note on register pair ordering:** The dividend is `{R, R+1}` where R holds the
high word and R+1 holds the low word, consistent with Sigma doubleword conventions.

```
Cycle 1: // EA calc + even-register check
  if (IR.R[0] == 1) → TRAP(SPECIFICATION)   // X'44' — R must be even
  A_BUS ← (X==0) ? 0 : R[X]
  B_BUS ← DISP_sext
  MAR   ← A_BUS + B_BUS

Cycles 2–3: // Read divisor
  Cyc2: MAP + MEM_READ
  Cyc3: DIVISOR     ← MDR
        if (DIVISOR == 0) → TRAP(FIXED_POINT_DIVIDE)  // X'45'
        DIVIDEND_HI ← R[IR.R]      // High word (R)
        DIVIDEND_LO ← R[IR.R + 1]  // Low word (R+1)
        COUNT ← 32

Cycles 4–35: // Non-restoring division loop (32 iterations)
  Loop:
    {DIVIDEND_HI, DIVIDEND_LO} ← {DIVIDEND_HI, DIVIDEND_LO} << 1
    if (DIVIDEND_HI[31] == 0)      // Previous result positive
        DIVIDEND_HI ← DIVIDEND_HI - DIVISOR
    else                            // Previous result negative
        DIVIDEND_HI ← DIVIDEND_HI + DIVISOR
    DIVIDEND_LO[0] ← (DIVIDEND_HI[31] == 0) ? 1 : 0  // New quotient bit
    COUNT ← COUNT - 1
    if (COUNT != 0) goto Loop

Cycle 36: // Remainder correction + writeback
  if (DIVIDEND_HI[31] == 1)        // Remainder negative — restore
      DIVIDEND_HI ← DIVIDEND_HI + DIVISOR
  R[IR.R]     ← DIVIDEND_LO       // Quotient
  R[IR.R + 1] ← DIVIDEND_HI       // Remainder
  CC4 ← quotient_overflow          // Set if |quotient| > 2^31-1; no trap unless PSD[28]=1
  CC1 ← (quotient == 0)
  CC2 ← quotient[31]               // Negative
  CC3 ← ~quotient[31] & |quotient  // Positive
  IA ← IA + 1
  μPC ← FETCH0
```

**Total: 36 cycles = 6.48 μs** (12× slower than AW).

#### Implementation Notes

- **33-bit ALU path (board A5):** The non-restoring loop operates on
  `{carry, DIVIDEND_HI}` (33 bits). COUT from the ADD/SUB becomes the new sign bit.
  The ALU must support a 33-bit internal datapath even though all architectural
  registers are 32-bit.
- **Remainder sign:** Always the same sign as the dividend (Sigma convention).
  This differs from IBM 360 (remainder sign = divisor sign) — a known porting hazard.
- **Overflow (CC4=1):** Set when quotient does not fit in 32 signed bits. No trap
  unless PSD[28]=1. OS must test CC4 explicitly.
- **Performance note:** The FORTRAN compiler generated CAL3 to the `$$DIV` library
  routine for most divisions, which used shift-based methods for powers of two.
  DW was rarely emitted directly.

#### Trap Addresses (partially known)

| Trap | Vector | Condition |
|---|---|---|
| SPECIFICATION | X'44' | Odd R field |
| FIXED_POINT_DIVIDE | X'45' | Divisor = 0 |

---

## 10. Interrupt System

### Interrupt Entry

Interrupts are sampled only at FETCH2. When IRQ_PENDING && !IRQ_INHIBIT:

1. Hardware forces μPC ← IRQ_ENTRY (microcode address 0x010)
2. TEMP0 ← PSD[31:0]; TEMP1 ← PSD[63:32] (hardware pre-loads)
3. EA is forced to X'50' (interrupt vector table)
4. XPSD micro-routine executes from Cycle 2 onward

This is mechanically identical to `XPSD X'50'(0)`.

**Interrupt levels:** 14 internal + up to 48 external (in groups of 12), confirmed by
560 Reference Manual. This differs significantly from Sigma 9 (up to 238 levels).

### Interrupt Return

OS executes `XPSD X'52'(0)`, which restores the saved user PSD from X'52'–X'53'.

### IRQ_INHIBIT

Set by XPSD Cycle 6 (MISC field). Cleared by XPSD Cycle 8. Prevents interrupts
from occurring during the half-swapped PSD window (Cycles 7–8).

Also set by LPSD and CAL instructions during their PSD manipulation.

---

## 11. Condition Codes

Four condition code bits in PSD[30:28]: CC1, CC2, CC3, CC4.

| CC | Meaning (fixed-point) |
|---|---|
| CC1 | Result > 0 |
| CC2 | Result = 0 |
| CC3 | Result < 0 |
| CC4 | Overflow (carry out on add; borrow on subtract) |

CC4 is generated on board A5: `CC4 ← ~COUT` for subtract (borrow = no carry out).

---

## 12. Floating-Point Number Format (Short)

32-bit IBM-style hexadecimal floating point:

```
  Bit 31:    Sign (0=positive, 1=negative)
  Bits 30:24: Exponent (7 bits, biased by 64)
  Bits 23:0:  Fraction (24 bits, base-16 mantissa)
```

- Exponent counts in base-16 steps
- No IEEE hidden bit in storage; hidden bit inserted by microcode during FAS
- Normalization shifts by 4 bits (one hex digit) per step
- Significance: up to 3 bits lost per alignment shift

---

## 13. Timing Summary

| Event | Cycles | Time |
|---|---|---|
| Fetch (FETCH0–FETCH2) | 3 | 0.54 μs |
| LW | 3 | 0.54 μs |
| STW | 3 | 0.54 μs |
| AW (direct) | 3 | 0.54 μs |
| AW (indirect, no index) | 4 | 0.72 μs |
| AW (indexed + indirect) | 5 | 0.90 μs |
| AW (each extra indirect level) | +2 | +0.36 μs |
| LB (direct) | 4 | 0.72 μs |
| LB (indirect, each level) | +2 | +0.36 μs |
| FAS (best case) | 10 | 1.80 μs |
| FAS (worst case) | ~15 | ~2.70 μs |
| XPSD | 8 | 1.44 μs |
| CAL1–CAL4 | 9 | 1.62 μs |
| DW | 36 | 6.48 μs |
| Interrupt entry (XPSD) | 8 | 1.44 μs |
| Total interrupt latency | ~11 | ~2.0 μs |

---

## 14. Internal (Non-User-Visible) CPU Registers

These registers are not accessible to software but are required for correct CPU
operation. They are explicitly named in the RTL documents or can be definitively
inferred from instruction behavior.

### 14.1 Memory Interface Registers

| Register | Width | Board | Description |
|---|---|---|---|
| MAR | 18-bit | A6 | Memory Address Register. Holds the physical word address for the current or pending memory operation. Fed by the ALU output mux or the MAR incrementer. |
| MDR | 32-bit | — | Memory Data Register. Holds data read from memory (read path) or data to be written (write path). Connected to D_BUS on reads, loaded from register file or ALU on writes. |

### 14.2 Instruction Decode Registers

| Register | Width | Board | Description |
|---|---|---|---|
| IR | 32-bit | A6 | Instruction Register. Loaded from MDR at FETCH2. Holds the current 32-bit instruction word for the duration of its execution. |
| IR.OPCODE | 7-bit | — | Decoded from IR[31:25]. Drives the dispatch ROM on board C2. |
| IR.R | 4-bit | — | Destination/source register field, IR[24:21]. |
| IR.X | 4-bit | — | Index register field, IR[20:17]. Zero means no indexing. |
| IR.I | 1-bit | — | Indirect bit, IR[16]. Triggers indirect address chaining in AW. |
| IR.DISP | 16-bit | — | Displacement field, IR[15:0]. Sign-extended to 17 bits for EA calculation. |

*Note: IR sub-fields are likely latched combinationally from IR rather than stored
in separate flip-flops, but are named distinctly in the RTL.*

### 14.3 Instruction Address

| Register | Width | Board | Description |
|---|---|---|---|
| IA | 17-bit | A6 | Instruction Address. Shadowed from PSW for fast access. Has a dedicated incrementer (IA+1) used at the end of every instruction. Updated either to IA+1 (sequential) or to MAR (branch taken). |

### 14.4 PSW Scratch Registers

Used exclusively during XPSD and CAL to hold the incoming PSW during the atomic
doubleword swap. Not accessible to software under any circumstances.

| Register | Width | Board | Description |
|---|---|---|---|
| TEMP0 | 32-bit | C4 | Holds word 0 of the new PSW during XPSD cycles 3–7. Also pre-loaded by hardware before IRQ entry. |
| TEMP1 | 32-bit | C4 | Holds word 1 of the new PSW during XPSD cycles 4–8. |

### 14.5 Sequencer and Control Registers

| Register | Width | Board | Description |
|---|---|---|---|
| IRQ_INHIBIT | 1-bit | C3 | Set by XPSD cycle 6 (MISC field). Cleared by XPSD cycle 8. Blocks interrupt sampling at FETCH2 during the half-swapped PSW window. Also set by LPSD and CAL during PSW manipulation. |
| IRQ_PENDING | 1-bit | C3 | OR of all armed and enabled interrupt request lines. Sampled only at FETCH2. |
| ZERO_FLAG | 1-bit | C2 | Latched ALU zero result. Set in BDR cycle 1, consumed in BDR cycle 3 for conditional branch. One of ~16 inputs to the branch mux. |
| COUNT | 6-bit | — | Loop counter for DW. Loaded with 32 at the start of the division loop, decremented each iteration. Not present in any other instruction. |

### 14.6 Sub-Word Addressing Registers (Board A7)

Used during byte and halfword instructions (LB, STB, LH, STH, etc.). Not present
in word or doubleword operations.

| Register | Width | Board | Description |
|---|---|---|---|
| BYTE_SEL | 2-bit | A7 | Latched from EA[1:0] during cycle 1 of any byte instruction. Drives the 4:1 byte mux to select which byte of the MDR word to extract. 00=bits[31:24], 01=bits[23:16], 10=bits[15:8], 11=bits[7:0]. |

Board A7 contains:
- **BYTE_SEL_LATCH:** 2-bit register clocked from EA[1:0] at end of cycle 1
- **4:1 byte mux:** selects one byte from 32-bit MDR word based on BYTE_SEL
- **Sign-extend block:** extends selected byte (or halfword) to 32 bits for register writeback. LB zero-extends; LBNZ sign-extends (microcode selects via IR[8] in cycle 3)

Used only during DW execution. All are internal to the microcode execution unit.

| Register | Width | Board | Description |
|---|---|---|---|
| DIVISOR | 32-bit | — | Loaded from MDR in DW cycle 3. Held constant for all 32 loop iterations. |
| DIVIDEND_HI | 33-bit | A5 | High word of the working dividend / accumulates remainder. 33-bit to capture carry out of the non-restoring ADD/SUB step. COUT becomes the new sign bit each iteration. |
| DIVIDEND_LO | 32-bit | — | Low word of the working dividend / accumulates quotient bits. LSB is set or cleared each iteration based on DIVIDEND_HI sign. |

### 14.8 Floating-Point Scratch Registers (FAS)

Used only during FAS (and by inference FAL, FSS, FSL, FMS, FML, FDS, FDL). The RTL
names these values explicitly but does not assign them to physical board locations.
For Verilog implementation they must be explicit registers in the FSM.

| Register | Width | Description |
|---|---|---|
| TA | 32-bit | Operand A (from register file), held from FAS cycle 3 through ADD_FRAC. |
| TB | 32-bit | Operand B (from memory via MDR), held from FAS cycle 3 through ADD_FRAC. |
| EA | 7-bit | Exponent of operand A, extracted from TA[30:24]. |
| EB | 7-bit | Exponent of operand B, extracted from TB[30:24]. |
| SA | 1-bit | Sign of operand A, from TA[31]. |
| SB | 1-bit | Sign of operand B, from TB[31]. |
| FA | 25-bit | Fraction of operand A with hidden bit prepended: {1, TA[23:0]}. Shifted right during alignment. |
| FB | 25-bit | Fraction of operand B with hidden bit prepended: {1, TB[23:0]}. Shifted right during alignment. |
| EXP | 7-bit | Result exponent. Set to max(EA, EB) during alignment, adjusted during normalization. |
| SHIFT_AMT | 3-bit | Number of hex-digit positions to shift the smaller operand (0–6). |
| FRES | 25-bit | Fraction result from ADD_FRAC step. May have carry out into bit 24. |
| SRES | 1-bit | Sign of result, determined during ADD_FRAC. |

*Total FP scratch state: approximately 120 bits. On the real hardware these are
likely distributed latches on the A5 (ALU) board, clocked by the MISC field of
the relevant micro-instructions.*

### 14.9 Virtual Address Fault Register

| Register | Width | Description |
|---|---|---|
| V_ADDR | 24-bit | Latched copy of the full byte EA computed in cycle 1 of any memory instruction. Preserved for fault handler use if a MAP protection trap fires in cycle 2. Referenced in LW RTL as "save for fault handling." |

---

## 15. Verilog Implementation Notes

### Design Approach

Behavioral RTL implementation: instructions are implemented as state machines with
states corresponding to documented microcycles. The 60-bit control store is not
recreated; FSM logic is hardcoded per instruction. Timing is cycle-accurate
(one state = one 180 ns clock period).

### Module Breakdown

```
cpu_top.sv          — Top-level FSM, fetch + dispatch
cpu_pkg.sv          — State enum, constants, field widths
register_file.sv    — 16×32 GPRs (A2/A3), synchronous write, async read
alu.sv              — 33-bit ALU + 32-bit shifter (A5); 33-bit path required for DW
byte_mux.sv         — 4:1 byte/halfword mux + sign-extend (A7)
psd.sv              — 64-bit PSW register with named field extractions (A6)
mar_ia.sv           — MAR, IA, fast incrementer (A6)
temp_regs.sv        — TEMP0, TEMP1 scratch registers (C4)
memory_interface.sv — MDR, MEM_READ, MEM_WRITE strobes
```

### State Enum (cpu_pkg.sv)

```verilog
typedef enum logic [5:0] {
    // Fetch
    FETCH0, FETCH1, FETCH2,
    // LW
    LW0, LW1, LW2,
    // STW
    STW0, STW1, STW2,
    // AW
    AW0, AW1, AW2, AW3, AW4,
    // DW (DIV) — loop state is reused 32 times
    DW0, DW1, DW2, DW_LOOP, DW_DONE,
    // FAS
    FAS0, FAS1, FAS2, FAS3, FAS4,
    FAS5, FAS6, FAS7, FAS8, FAS9,
    FAS_ZERO,
    // XPSD (shared with CAL and IRQ)
    XPSD0, XPSD1, XPSD2, XPSD3,
    XPSD4, XPSD5, XPSD6, XPSD7,
    // CAL (unique setup, then joins XPSD at XPSD1)
    CAL0, CAL1_ST,
    // IRQ entry (joins XPSD at XPSD1)
    IRQ0,
    // Trap
    TRAP
} cpu_state_t;
```

### Dispatch Table

```verilog
always_comb begin
    case (opcode)
        7'h32: next_state = LW0;
        7'h35: next_state = STW0;
        7'h30: next_state = AW0;
        7'h64: next_state = BDR0;
        7'h3D: next_state = FAS0;
        7'h0F: next_state = XPSD0;
        7'h04: next_state = CAL0;  // CAL1
        7'h05: next_state = CAL0;  // CAL2
        7'h06: next_state = CAL0;  // CAL3
        7'h07: next_state = CAL0;  // CAL4
        7'h1E: next_state = DW0;
        7'h00: next_state = FETCH0; // HALT — loop
        default: next_state = TRAP;
    endcase
end
```

### MAP RAM Bypass

```verilog
// Identity translation — replace with MAP RAM lookup later
assign physical_addr = virtual_addr[17:0];
```

---

## 16. Known Unknowns

The following aspects are not yet confirmed from the authoritative Xerox 560 Reference
Manual (903076A). The PDF fetcher cannot reach past the front matter in one pass;
these items need verification from Chapter 2 (System Organization) onward:

- **PSD/PSW field layout** — The 560 manual refers to "Program Status Words" (plural,
  PSW) rather than "Program Status Doubleword" (PSD). Exact bit field positions for
  the 560 need verification; the Sigma 9 PSD layout has been used as a proxy.
- **MAP RAM permission bit positions** — Inferred from Sigma 9; 560-specific layout
  unconfirmed.
- **Instruction timing** — No timing appendix retrieved yet. RTL-derived timing used.
- **Complete instruction set** — 11 instructions documented from RTL; full 560 opcode
  table not yet retrieved from manual Chapter 3.
- **Trap vector addresses** — Partially known (X'44', X'45' from DIV RTL); full table
  in manual Table 3 not yet retrieved.
- **Double indexing** — `LB R,addr(X,Y)` uses a 3-input adder on A6. Whether the 560 supports this (vs Sigma 9 only) needs verification.
- **Halfword alignment trap** — EA[1] must be 0 for halfword ops; trap vector unconfirmed.
- **LW alignment trap** — EA[1:0] must be 00; trap vector not yet confirmed (may be same SPECIFICATION vector as DW odd-R trap at X'44').
- **Memory interface timing** — Write buffer, STW→LW hazard behavior
- **Trap handler microcode sequences** (TRAP_XPSD_PARTIAL, FP traps, etc.)
- **Detailed I/O subsystem interface**
- **Watchdog timer implementation and indirect chain limit**
- **Opcode discrepancy** — RTL source docs used octal notation that doesn't map
  directly to the manual's hex opcodes; root cause unknown

---

## 17. Source Documents

| Document | Type | Confidence |
|---|---|---|
| `microcode.txt` | Micro-instruction format, board overview, XPSD description | High — consistent with field service style |
| `LW_rtl.txt` | Load Word RTL | High |
| `FAS_rtl.txt` | Floating Add Short RTL | High |
| `AW_rtl.txt` (inline) | Add Word RTL + timing table | High |
| `STW_rtl.txt` (inline) | Store Word RTL | High |
| `BDR.txt` (inline) | Branch on Decrement RTL | High |
| `XPSD.txt` | XPSD RTL, board details | High — most detailed document |
| `FETCH0.txt` | Fetch micro-routine, dispatch ROM | High |
| `CAL1.txt` | CAL1–4 RTL | High |
| `EA.txt` | Byte addressing EA calculation, BYTE_SEL, board A7, LB vs LW comparison | High |
| Xerox 560 Reference Manual 903076A (Jan 1974) | **Authoritative primary source** for all 560-specific parameters: register blocks (4), virtual address space (128K words), page size (512 words), physical memory (256K words max), interrupt levels (14+48). Chapter 2+ not yet fully retrieved. | Authoritative |
| SDS/XDS Sigma 9 Reference Manual 901733A (Oct 1970) | Opcodes, instruction set structure. Used as proxy where 560 manual not yet retrieved; differences noted. | Secondary |

*Provenance of RTL documents: believed derived from Xerox/SDS field service manuals,
possibly including the Sigma 9 CPU Technical Manual. Primary sources not confirmed.*
