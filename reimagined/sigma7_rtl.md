# SDS/Xerox Sigma 7 — Instruction Register Transfer Language

## Notation

| Symbol | Meaning |
|--------|---------|
| RR[n] | User-visible register n (0–15), mapped to word addresses 0–15 |
| R | 4-bit register field register, loaded from instruction bits 8–11 |
| r | Value held in R; selects destination/source user register |
| x | X field of instruction (3 bits, bits 12–14); index register selector (0 = no index). X can only select registers 1–7. |
| i | I field of instruction (1 bit); 1 = indirect addressing |
| A | 32-bit primary ALU input/result register |
| B | 32-bit secondary register. Loads via B_sel: B_CMUX (←C_mux, for memory reads) or B_ALU (←alu_out, for multiply/divide). Used as registered TOS scratch in PSW/PLW; future A:B 64-bit pair for multiply/divide. |
| C | 32-bit memory interface register (transparent latch); C_mux = bus_data_r when C_load=1, else C |
| D | 32-bit secondary ALU input; loaded from C_mux (instruction in ENDE, indirect pointer in PREP2, operand in EX1) |
| E | 8-bit floating-point exponent register |
| O | 7-bit opcode register |
| P | 19-bit effective address register (bits 15–33); P[15:31]=word address, P[32:33]=byte offset |
| Q | 17-bit instruction address register (bits 15–31); holds IA word address after PREP1 |
| CC | 4-bit condition code register (bits 1–4) |
| AWZ | A Was Zero flip-flop; used for 64-bit zero detection in doubleword operations |
| alu_out | Combinatorial ALU output; inputs are A and D |
| p_inc | Combinatorial P+4 wire |
| IA | Instruction address — the byte address of the currently executing instruction |
| M[addr] | 32-bit word memory access at byte address addr (synchronous: address on cycle N → data on cycle N+1) |
| M.H[addr] | 16-bit halfword memory access; returned in bits 16:31 of bus_data_r, bits 0:15 = 0 |
| M.B[addr] | 8-bit byte memory access; returned in bits 24:31 of bus_data_r, bits 0:23 = 0 |
| bus_size | Memory access width: 2'b10=word, 2'b01=halfword, 2'b00=byte |
| imm20 | Sign-extended 20-bit immediate: {{12{D[12]}}, D[12:31]} |
| sext(v) | Sign extend v to 32 bits |
| ENDE | End-of-instruction signal; fires in last execute phase |

---

## Address Family Decode

The opcode table is organised into rows and columns. The address family decode
derives operand size from the opcode (from C or O, which hold the instruction):

```
fa_row_00     = op[1:5] == 0            ; rows 0x00–0x03 of any column
fa_rows_10_1f = op[3]                   ; upper half of column (0x10–0x1F etc.)
fa_rows_08_0f = op[3:4] == 01           ; rows 0x08–0x0F of column 00
fa_col_00     = op[1:2] == 00           ; column 00 (0x00–0x1F)
fa_col_20     = op[1:2] == 01           ; column 20 (0x20–0x3F)
fa_col_40     = op[1:2] == 10           ; column 40 (0x40–0x5F)
fa_col_60     = op[1:2] == 11           ; column 60 (0x60–0x7F)
fa_b          = fa_col_60 & fa_rows_10_1f               ; byte (0x70–0x7F)
fa_h          = fa_col_40 & fa_rows_10_1f               ; halfword (0x50–0x5F)
fa_d          = fa_col_00 & (fa_rows_08_0f | fa_rows_10_1f) ; doubleword (0x08–0x1F)
fa_imm        = fa_row_00 & (fa_col_00 | fa_col_20)     ; immediate word
fa_imm_b      = fa_row_00 & (fa_col_40 | fa_col_60)     ; immediate byte
fa_w          = ~fa_b & ~fa_h & ~fa_d & ~fa_imm & ~fa_imm_b ; word (all else)
```

---

## Index Register Alignment

For indexed instructions (X≠0, non-immediate), the index register is
interpreted in units of the operand size:

```
idx_reg  = RR[X]
idx_data = fa_b ? RR[X] >> 2 : fa_h ? RR[X] >> 1 : RR[X]   ; word-address contribution
idx_boff = fa_b ? RR[X][30:31]                               ; byte offset (2 bits)
         : fa_h ? {RR[X][31], 1'b0}                          ; halfword offset (P[32]=select, P[33]=0)
         :        2'b00                                       ; word/dw always 00
```

The index register value is therefore interpreted as:
- **Word:** word address (idx_data = RR[X], idx_boff = 00)
- **Halfword:** halfword address (idx_data = RR[X]>>1, P[32] = RR[X][31])
- **Byte:** byte address (idx_data = RR[X]>>2, P[32:33] = RR[X][30:31])

---

## Condition Code Encoding

**Arithmetic, Load, and Logical instructions — CC_ARITH:**
| Bit | Name | Set when |
|-----|------|----------|
| CC1 | Carry | Carry out of ALU |
| CC2 | Overflow | Fixed point overflow |
| CC3 | Positive | alu_out[0] = 0 AND alu_out ≠ 0 |
| CC4 | Negative | alu_out[0] = 1 |
Zero result: CC1–CC4 all clear.

**Compare instructions (CW, CH, CB, CI, CD) — CC_COMPARE:**
| Bit | Name | Set when |
|-----|------|----------|
| CC1 | — | Always 0 |
| CC2 | Bits compare | Bitwise AND of register and operand is non-zero |
| CC3 | Greater | Register value > operand (alu_out[0]=0 and alu_out≠0) |
| CC4 | Less | Register value < operand (alu_out[0]=1) |

**Load Complement (LCW, LCH, LCD) — CC_ARITH:**
- CC2 and CC4 both set on fixed point overflow (negating most-negative value)

**Load Absolute (LAW, LAH, LAD) — CC_ABS:**
- CC3 set if result is non-zero and no overflow; CC2 and CC4 both set on overflow

**Doubleword instructions — CC_ARITH_DW:**
- CC1=carry from high word, CC2=overflow from high word
- CC3=64-bit result non-zero and non-negative, CC4=high word bit 0 = 1

---

## Boot Sequence and Common Phases

### PCP4 — Stable Reset/Halt State

```
PCP4: if !reset: bus_addr ← p_inc; phase → PCP5
      ; otherwise hold in PCP4
```

### PCP5 — Boot ENDE

```
PCP5: ENDE        ; instruction fetched by PCP4 arrives; load and proceed
```

### ENDE Signal

ENDE fires at the last execute phase of every instruction, and from PCP5 on boot.
The cycle **before** ENDE must present `{Q, 2'b00}` on bus_addr (= IA, the current
instruction byte address) so the next instruction arrives on time. ENDE then
increments P to IA+4 = next instruction byte address.

```
ENDE: C/D/O/R ← bus_data_r    ; load arriving instruction
      A ← 0                    ; clear for EA calculation (index loaded in PREP1)
      P ← P + 4                ; P was IA (restored in EX(n-1)); now P = next instr addr
      bus_addr ← {Q, 2'b00}   ; harmless — next instruction already fetched
      if immediate: phase → EX1
      if memory:    phase → PREP1
```

### Prep Phases

```
PREP1: Q ← P[15:31]            ; Q ← IA word address (P = next instr addr after ENDE)
       if indexed: A ← idx_data; P[32:33] ← idx_boff  (registered at clock edge)
       else:       A ← 0
       bus_addr ← {C[15:31], 2'b00}   ; present reference address (C = instruction)
       if i=1: phase → PREP2
       else:   phase → PREP3
```

```
PREP2: C_load; D ← C_mux       ; D ← indirect pointer word (C_mux = arriving pointer)
       bus_addr ← {C[15:31], 2'b00}   ; C still holds instruction (safe, no comb. path)
       ; auto-shifts to PREP3
```

```
PREP3: P[15:31] ← A + D[15:31] ; EA word address via ALU (A=index or 0, D=base)
       P[32:33] ← idx_boff      ; byte offset from index register
       bus_addr ← {alu_out[15:31], idx_boff}  ; full EA on bus
       bus_size ← word/halfword/byte based on O
       ; auto-shifts to EX1
```

After PREP3, P holds the complete effective byte address.
Note: for indirect instructions PREP2 re-loads D with the resolved pointer,
so PREP3 computes A + resolved_pointer[15:31] = indexed indirect EA.

### EX(n-1) — One Cycle Before ENDE

Every instruction must, in the cycle immediately before ENDE fires:
```
P_sel ← P_Q            ; P ← {Q, 2'b00} = IA (restores P from EA so p_inc is correct)
Q_sel ← 1              ; Q ← P[15:31] = IA word address (redundant but explicit)
bus_addr ← {Q, 2'b00}  ; present IA so next instruction arrives at ENDE
```

---

## Implemented Instructions

### LCFI — Load Conditions and FP Immediate (0x02)

Immediate (ENDE → EX1). All-zero fields = no-op / halt.

```
EX1:   Q_sel; bus_addr ← {P[15:31], 2'b00}   ; P=IA, Q←IA word addr, present IA
EX2/ENDE: if D[10]: CC ← D[24:27]
```

### LI — Load Immediate (0x22)

Immediate. imm20 = sign-extended D[12:31].

```
EX1:   Q_sel; bus_addr ← {P[15:31], 2'b00}
EX2/ENDE: RR[r] ← imm20; CC ← CC_ARITH(imm20)
```

### LW — Load Word (0x32)

```
PREP1-3: EA → P; bus_size=word
EX1:   C_load; D_sel; A ← C_mux          ; C and D ← M[EA]
EX2:   RR[r] ← A; CC ← CC_ARITH(A)
       Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX3/ENDE:
```

### STW — Store Word (0x35)

```
PREP1-3: EA → P
EX1:   A ← RR[r]
EX2:   M[P] ← A; bus_size=word           ; bus busy with write
EX3:   Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX4/ENDE:
```
*STW does not update CC.*

### AW — Add Word (0x30)

```
PREP1-3: EA → P; bus_size=word
EX1:   C_load; D_sel; A ← RR[r]
EX2:   alu_out←A+D; RR[r]←alu_out; CC←CC_ARITH(alu_out)
       Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX3/ENDE:
```

### SW — Subtract Word (0x38)

```
PREP1-3: EA → P; bus_size=word
EX1:   C_load; D_sel; A ← RR[r]
EX2:   alu_out←A-D; RR[r]←alu_out; CC←CC_ARITH(alu_out)
       Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX3/ENDE:
```

### CW — Compare Word (0x31)

```
PREP1-3: EA → P; bus_size=word
EX1:   C_load; D_sel; A ← RR[r]
EX2:   alu_out←A-D; CC←CC_COMPARE(A,D,alu_out)
       Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX3/ENDE:
```
*CW does not write back to RR.*

### AND (0x4B), OR (0x49), EOR (0x48)

```
PREP1-3: EA → P; bus_size=word
EX1:   C_load; D_sel; A ← RR[r]
EX2:   alu_out←A AND/OR/XOR D; RR[r]←alu_out; CC←CC_ARITH(alu_out)
       Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX3/ENDE:
```

### LH — Load Halfword (0x52)

Memory returns sign-extended halfword in bits 16:31.

```
PREP1-3: EA → P; bus_size=halfword; P[32]=halfword_select (from idx_boff)
EX1:   C_load; bus_size=halfword
       A ← sign_extend(C_mux[16:31])     ; A_SEXT_H
EX2:   RR[r]←A; CC←CC_ARITH(A)
       Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX3/ENDE:
```

### STH — Store Halfword (0x55)

```
PREP1-3: EA → P; P[32]=halfword_select
EX1:   A ← RR[r]
EX2:   M.H[P] ← A[16:31]; bus_size=halfword; bus busy
EX3:   Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX4/ENDE:
```
*STH does not update CC.*

### LB — Load Byte (0x72)

Memory returns zero-extended byte in bits 24:31.

```
PREP1-3: EA → P; bus_size=byte; P[32:33]=byte_select (from idx_boff)
EX1:   C_load; bus_size=byte
       A ← C_mux                         ; zero-extended by memory
EX2:   RR[r]←A; CC←CC_ARITH(A)
       Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX3/ENDE:
```

### STB — Store Byte (0x75)

```
PREP1-3: EA → P; P[32:33]=byte_select
EX1:   A ← RR[r]
EX2:   M.B[P] ← A[24:31]; bus_size=byte; bus busy
EX3:   Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX4/ENDE:
```
*STB does not update CC.*

### AI — Add Immediate (0x20)

Immediate (ENDE → EX1). D is loaded with imm20 in EX1 alongside A←RR[r].

```
EX1:   A←RR[r]; D←imm20; Q_sel; bus_addr←{P[15:31],00}
EX2/ENDE: alu_out←A+D; RR[r]←alu_out; CC←CC_ARITH(alu_out)
```

### CI — Compare Immediate (0x21)

```
EX1:   A←RR[r]; D←imm20; Q_sel; bus_addr←{P[15:31],00}
EX2/ENDE: alu_out←A-D; CC←CC_COMPARE(A,D,alu_out)
```
*CI does not write back to RR.*

### BCR — Branch on Conditions Reset (0x68)

Branch taken when CC AND R = 0. R=0 → unconditional branch.

```
PREP1-3: EA → P
EX1 (taken):     bus_addr←{P[15:31],00}     ; present EA; P unchanged (=EA)
EX1 (not taken): P_sel←P_Q; bus_addr←{Q,00} ; restore P=IA, present IA
EX2:             (pass through)
EX3/ENDE: ENDE fires; P←P+4
          taken:     P was EA → p_inc = EA+4 ✓
          not taken: P was IA → p_inc = IA+4 ✓
```

### BCS — Branch on Conditions Set (0x69)

Branch taken when CC AND R ≠ 0. R=0 → effective no-op.

Same phase sequence as BCR with inverted condition.

### BAL — Branch and Link (0x6A)

Always branches. Saves return word address in RR[r]. One fewer EX cycle than BCR/BCS since branch is unconditional — no fall-through path needed.

```
PREP1-3: EA → P
EX1:   RR[r] ← {15'b0, Q}     ; Q = IA word address = return address
       bus_addr ← {P[15:31],00} ; present EA; P unchanged (=EA)
EX2/ENDE: ENDE fires; P←EA+4  ; first instruction of subroutine
```

Return via: `BCR 0, 0, Rr` — unconditional branch to address in RR[r].

### RD — Read Direct (0x6C)

Reads 32 bits from an I/O device into RR[r]. Phase sequence mirrors LW but with `io_select=1` asserted during EX phases. Data register returns character in bits 24:31. CC set from value read.

```
PREP1-3: EA → P (device address)
EX1:   io_select; C_load; A←C_mux   ; read from device (data arrives)
EX2:   RR[r]←A; CC←CC_ARITH(A)
       Q_sel; P_sel←P_Q; bus_addr←{Q,00}
       io_select
EX3/ENDE:
```

**Console device addresses:**

| Address | Register |
|---------|----------|
| 0x1001  | Data — RD reads char in bits 24:31; WD writes char from bits 24:31 |
| 0x1002  | Status — bit 31=RX ready, bit 30=TX ready (always 1 in simulation) |

### WD — Write Direct (0x6D)

Writes RR[r] to an I/O device. Phase sequence mirrors STW.

```
PREP1-3: EA → P (device address)
EX1:   A←RR[r]; io_select
EX2:   device←A; io_select; bus busy (write)
EX3:   Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX4/ENDE:
```

---

### PSW — Push Word (0x09)

Pushes RR[r] onto the push-down stack defined by the Stack Pointer Doubleword
at the effective address. B captures TOS from SPD[0] via C_mux in EX1, providing
a registered (not combinatorial) address for the EX2 memory write.

```
PREP1-3: EA → P (SPD word address); P[15:31] = SPD address
EX1:   C_load; B_sel←B_CMUX   ; B[15:31] ← SPD[0][15:31] = TOS (via C_mux)
       D_sel                    ; D ← SPD[0]
       A_sel←A_RR               ; A ← RR[r] (value to push)
EX2:   bus_addr←{B[15:31]+1,00} ; present TOS+1 address
       bus_data_w←A; cpu_write   ; M[TOS+1] ← RR[r]
EX3:   bus_addr←{P[15:31],00}   ; present SPD address
       bus_data_w←{15'b0,B[15:31]+1}; cpu_write  ; M[SPD] ← new TOS
EX4:   P_sel←P_Q; bus_addr←{Q,00}
EX5/ENDE:
```

### PLW — Pull Word (0x08)

Pulls from the push-down stack into RR[r]. B captures TOS from SPD[0] via C_mux
in EX1. EX2 presents M[TOS] address so M[TOS] arrives in bus_data_r at EX3.
The SPD write (new TOS = TOS-1) and the M[TOS] capture into A both happen in EX3 —
they are independent: bus_data_r carries M[TOS] from EX2's bus_addr regardless of
the write issued via bus_data_w in the same cycle.

```
PREP1-3: EA → P (SPD word address)
EX1:   C_load; B_sel←B_CMUX   ; B[15:31] ← SPD[0][15:31] = TOS (via C_mux)
       D_sel                    ; D ← SPD[0]
EX2:   bus_addr←{B[15:31],00}  ; present TOS address; M[TOS] arrives in EX3
EX3:   C_load; A_sel←A_CMUX    ; A ← M[TOS]  (from EX2's bus_addr)
       bus_addr←{P[15:31],00}
       bus_data_w←{15'b0,B[15:31]-1}; cpu_write  ; M[SPD] ← TOS-1
EX4:   alu_op←PASSA; CC_sel←CC_ARITH; rr_data←A; rr_write  ; RR[r] ← M[TOS]
       P_sel←P_Q; bus_addr←{Q,00}
EX5/ENDE:
```

*CC is set from the pulled value (A = M[TOS]) in EX4.*

---


## Pending Instructions

The following instructions are documented but not yet implemented in Verilog.
They follow the same timing model as the implemented instructions above.

### LCW — Load Complemented Word (0x3A)

```
PREP1-3: EA → P; bus_size=word
EX1:   C_load; D_sel; A←C_mux
EX2:   alu_out←0-D; RR[r]←alu_out
       Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX3:   CC←CC_ARITH(alu_out); ENDE
```

### LAW — Load Absolute Word (0x3B)

```
PREP1-3: EA → P; bus_size=word
EX1:   C_load; D_sel; A←C_mux
EX2:   if D[0]=0: RR[r]←A; goto EX4
       alu_out←0-D; A←alu_out; RR[r]←alu_out
       Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX3:   (negative path only)
EX4:   CC←CC_ABS(A); ENDE
```

### AH — Add Halfword (0x50)

```
PREP1-3: EA → P; bus_size=halfword
EX1:   C_load; bus_size=halfword; D←sext(C_mux[16:31]); A←RR[r]
EX2:   alu_out←A+D; RR[r]←alu_out; CC←CC_ARITH(alu_out)
       Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX3/ENDE:
```

### SH — Subtract Halfword (0x58)

```
PREP1-3: EA → P; bus_size=halfword
EX1:   C_load; bus_size=halfword; D←sext(C_mux[16:31]); A←RR[r]
EX2:   alu_out←A-D; RR[r]←alu_out; CC←CC_ARITH(alu_out)
       Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX3/ENDE:
```

### CH — Compare Halfword (0x51)

```
PREP1-3: EA → P; bus_size=halfword
EX1:   C_load; bus_size=halfword; D←sext(C_mux[16:31]); A←RR[r]
EX2:   alu_out←A-D; CC←CC_COMPARE(A,D,alu_out)
       Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX3/ENDE:
```

### BDR — Branch on Decrementing Register (0x64)

Branch taken when result is **positive** (result[0]=0 and result≠0).

```
PREP1-3: EA → P
EX1:   RR[r] ← RR[r] - 1
       if positive: bus_addr←{P[15:31],00}; Q_sel; P_sel←P_Q → EX2/ENDE (branch)
       else:        Q_sel; P_sel←P_Q; bus_addr←{Q,00} → EX2/ENDE (fall through)
```

### BIR — Branch on Incrementing Register (0x65)

Branch taken when result is **negative** (result[0]=1).

```
PREP1-3: EA → P
EX1:   RR[r] ← RR[r] + 1
       if negative: bus_addr←{P[15:31],00}; Q_sel; P_sel←P_Q → EX2/ENDE (branch)
       else:        Q_sel; P_sel←P_Q; bus_addr←{Q,00} → EX2/ENDE (fall through)
```

### LCH — Load Complemented Halfword (0x5A)

```
PREP1-3: EA → P; bus_size=halfword
EX1:   C_load; bus_size=halfword; A←sext(C_mux[16:31])
EX2:   alu_out←0-A; RR[r]←alu_out
       Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX3:   CC←CC_ARITH(alu_out); ENDE
```

### LAH — Load Absolute Halfword (0x5B)

```
PREP1-3: EA → P; bus_size=halfword
EX1:   C_load; bus_size=halfword; A←sext(C_mux[16:31])
EX2:   if A[0]=0: RR[r]←A; goto EX4
       alu_out←0-A; A←alu_out; RR[r]←alu_out
       Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX3:   (negative path only)
EX4:   CC←CC_ABS(A); ENDE
```

### CB — Compare Byte (0x71)

```
PREP1-3: EA → P; bus_size=byte
EX1:   C_load; bus_size=byte; D←{24'b0, C_mux[24:31]}; A←{24'b0, RR[r][24:31]}
EX2:   alu_out←A-D; CC←CC_COMPARE(A,D,alu_out)
       Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX3/ENDE:
```

### MTH — Modify and Test Halfword (0x53)

```
PREP1-3: EA → P; bus_size=halfword
EX1:   C_load; bus_size=halfword; A←sext(C_mux[16:31])
EX2:   alu_out←A+sext(R,16); A←alu_out
EX3:   M.H[P]←alu_out[16:31]; bus_size=halfword
EX4:   CC←CC_ARITH(alu_out); ENDE
```

### MTB — Modify and Test Byte (0x73)

```
PREP1-3: EA → P; bus_size=byte
EX1:   C_load; bus_size=byte; A←{24'b0, C_mux[24:31]}
EX2:   alu_out←A+sext(R,8); A←alu_out
EX3:   M.B[P]←alu_out[24:31]; bus_size=byte
EX4:   CC←CC_ARITH(alu_out); ENDE
```

### Doubleword Instructions (AD, SD, CD, LD, STD, LCD, LAD)

These require multiple memory accesses and the AWZ flip-flop for 64-bit zero
detection. Refer to the CPU design reference for detailed timing.

### Floating Point (FAS, FAL, FSS, FSL, FMS, FML, FDS, FDL)

Uses the same integer ALU datapath with E register for exponent arithmetic.
Optional instruction group — traps to X'41' if not implemented.

### Shift Instructions (S, SF)

Use the ALU shift capability (1-bit and 4-bit shifts).

### I/O Instructions (SIO, TIO, TDV, HIO, AIO)

Privileged channel I/O instructions. Interact with the IOP via the bus arbiter.
RD and WD (direct I/O) are already implemented — see Implemented Instructions above.