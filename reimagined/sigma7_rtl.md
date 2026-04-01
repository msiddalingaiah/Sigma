# SDS/Xerox Sigma 7 — Instruction Register Transfer Language

## Notation

| Symbol | Meaning |
|--------|---------|
| RR[n] | User-visible register n (0–15), mapped to word addresses 0–15 |
| R | 4-bit register field register, loaded from instruction bits 8–11 |
| r | Value held in R; selects destination/source user register |
| x | X field of instruction (3 bits); index register selector; repurposed as part of immediate for immediate instructions |
| i | I field of instruction (1 bit); 1 = indirect addressing |
| A | 32-bit primary ALU input/result register |
| B | 32-bit multiply/divide partner register (forms 64-bit A:B pair) |
| C | 32-bit memory interface register (transparent latch); C_mux = bus_data_r when loading, else C |
| D | 32-bit instruction word register; holds current instruction for EA calculation |
| E | 8-bit floating-point exponent register |
| O | 7-bit opcode register |
| P | 19-bit effective address register (bits 15–33) |
| Q | 17-bit next instruction word address register (bits 15–31) |
| CC | 4-bit condition code register (bits 1–4) |
| AWZ | A Was Zero flip-flop; used for 64-bit zero detection in doubleword operations |
| alu_out | Combinatorial ALU output; inputs are A and C_mux |
| M[addr] | 32-bit word memory access at byte address addr (synchronous: address on cycle N → data on cycle N+1) |
| M.H[addr] | 16-bit halfword memory access; always presented in bits 16:31 of bus_data_r |
| M.B[addr] | 8-bit byte memory access; always presented in bits 24:31 of bus_data_r |
| EA | Effective byte address, held in P after prep phases |
| ea | Combinatorial EA wire: {A[15:31] + D[15:31], P[32:33]} |
| p_inc | Combinatorial P+4 wire |
| next_ia | {Q+1, 2'b00} — next instruction byte address (Q = current instruction word address, set in PREP1) |
| imm20 | Sign-extended 20-bit immediate: {{12{D[12]}}, D[12:31]} |
| sext(v) | Sign extend v to 32 bits |
| ENDE | End-of-instruction signal; fires in last execute phase |

---

## Condition Code Encoding

**Arithmetic, Load, and Logical instructions (AW, SW, LW, LI, AND, OR, EOR, etc.) — CC_ARITH:**
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
Equal result: CC1–CC4 all clear.

**Load Byte (LB) and Modify and Test Byte (MTB) — CC_BYTE:**
- CC3 set if byte result is non-zero
- CC4 never set (bytes are unsigned/zero-extended)

**Load Complement (LCW, LCH, LCD) — CC_ARITH:**
- CC2 and CC4 both set on fixed point overflow (negating most-negative value)

**Load Absolute (LAW, LAH, LAD) — CC_ABS:**
- CC3 set if result is non-zero and no overflow
- CC2 and CC4 both set on overflow

**Doubleword instructions — CC_ARITH_DW:**
- CC1 — carry from high word
- CC2 — overflow from high word
- CC3 — 64-bit result non-zero and non-negative
- CC4 — high word bit 0 = 1 (negative)

---

## Boot Sequence and Common Phases

### PCP4 — Stable Reset/Halt State

Held during reset. On release, presents the initial instruction address on the
bus and jumps to PCP5:

```
PCP4: if !reset: bus_addr ← p_inc; phase → PCP5
      ; otherwise hold in PCP4
```

### PCP5 — Boot ENDE

Fires ENDE when the instruction fetched by PCP4 arrives on the bus:

```
PCP5: ENDE
```

After boot, ENDE jumps to PREP1 (memory-reference) or EX1 (immediate).

### ENDE Signal

ENDE fires at the last execute phase of every instruction, and from PCP5 on
boot. It loads the arriving instruction, updates registers, and presents the
instruction's reference address to memory:

```
ENDE: C/D/O/R ← bus_data_r              ; load arriving instruction
      A ← 0                             ; clear for EA calculation
      P ← P + 4                         ; increment to next instruction byte address
      bus_addr ← {C_mux[15:31], 2'b00}  ; present reference address field (transparent latch)
      if immediate: phase → EX1         ; skip prep phases
      if memory:    phase → PREP1       ; compute EA
```

The cycle **before** ENDE must always present the next instruction byte address
(`next_ia = {Q+1, 2'b00}`) on bus_addr so the instruction arrives in time.
For immediate instructions the cycle before ENDE uses `p_inc` (P still holds
the current instruction's byte address). For taken branches, the target address
is presented instead.

### Prep Phases

```
PREP1: Q ← P[15:31]                     ; save next instruction word address
       S ← D (ALU_PASSD)                ; S = reference address field
       bus_addr ← {S[15:31], 2'b00}     ; present EA (A=0 for non-indexed)
       phase → PREP3
```

When indexing is added: A=RR[X] from ENDE, alu_op=ALU_ADD → S=A+D = indexed EA.

```
PREP3: P[15:31] ← S[15:31]              ; register EA into P
       bus_addr ← {S[15:31], P[32:33]}  ; hold on bus: operand arrives at EX1
       ; auto-shifts to EX1
```

After PREP3, P holds the complete effective byte address.

---

## Implemented Instructions

### LCFI — Load Conditions and FP Immediate (0x02)

Immediate instruction (ENDE → EX1 directly). With all-zero fields, acts as a no-op.
Loaded into C/D/O on reset as the first instruction to execute.

```
EX1:   Q ← P[15:31]; bus_addr ← p_inc   ; save Q, present next instruction
EX2/ENDE: if D[10]: CC ← D[24:27]       ; direct CC load
```

### LI — Load Immediate (0x22)

Immediate instruction. imm20 = sign-extended D[12:31].

```
EX1:   Q ← P[15:31]; bus_addr ← p_inc   ; save Q, present next instruction
EX2/ENDE: RR[r] ← imm20
           CC ← CC_ARITH(imm20)
```

### LW — Load Word (0x32)

```
PREP1: Q←P; bus_addr←EA                 ; M[EA] arrives at EX1 via PREP3
PREP3: P[15:31]←EA
EX1:   C ← bus_data_r; A ← C_mux
EX2:   RR[r] ← A; CC ← CC_ARITH(A)
       P_sel←P_Q; bus_addr ← next_ia    ; present next instruction
EX3/ENDE:
```

### STW — Store Word (0x35)

```
PREP1: Q←P; bus_addr←EA
PREP3: P[15:31]←EA
EX1:   A ← RR[r]
EX2:   M[P] ← A                         ; bus busy with write
EX3:   P_sel←P_Q; bus_addr ← next_ia   ; bus free, present next instruction
EX4/ENDE:
```
*Note: STW does not update CC. One extra EX cycle because bus is busy in EX2.*

### AW — Add Word (0x30)

```
PREP1: Q←P; bus_addr←EA
PREP3: P[15:31]←EA
EX1:   C ← bus_data_r; A ← RR[r]
EX2:   alu_out ← A + C_mux; RR[r] ← alu_out
       CC ← CC_ARITH(alu_out)
       P_sel←P_Q; bus_addr ← next_ia
EX3/ENDE:
```

### SW — Subtract Word (0x38)

```
PREP1: Q←P; bus_addr←EA
PREP3: P[15:31]←EA
EX1:   C ← bus_data_r; A ← RR[r]
EX2:   alu_out ← A + ~C_mux + 1; RR[r] ← alu_out
       CC ← CC_ARITH(alu_out)
       P_sel←P_Q; bus_addr ← next_ia
EX3/ENDE:
```

### CW — Compare Word (0x31)

```
PREP1: Q←P; bus_addr←EA
PREP3: P[15:31]←EA
EX1:   C ← bus_data_r; A ← RR[r]
EX2:   alu_out ← A + ~C_mux + 1
       CC ← CC_COMPARE(A, C_mux, alu_out)
       P_sel←P_Q; bus_addr ← next_ia
EX3/ENDE:
```
*Note: CW does not write back to RR.*

### AND (0x4B), OR (0x49), EOR (0x48)

```
PREP1: Q←P; bus_addr←EA
PREP3: P[15:31]←EA
EX1:   C ← bus_data_r; A ← RR[r]
EX2:   alu_out ← A AND/OR/XOR C_mux; RR[r] ← alu_out
       CC ← CC_ARITH(alu_out)
       P_sel←P_Q; bus_addr ← next_ia
EX3/ENDE:
```

---

## Pending Instructions

The following instructions are documented but not yet implemented in Verilog.
They follow the same timing model as the implemented instructions above.

### AI — Add Immediate (0x20)

```
PREP1: (immediate) phase → EX1
EX1:   A ← RR[r]
EX2:   alu_out ← A + imm20
       A ← alu_out
       RR[r] ← alu_out
       CC ← CC_ARITH(alu_out)
       ENDE
```

### CI — Compare Immediate (0x21)

```
PREP1: (immediate) phase → EX1
EX1:   A ← RR[r]
EX2:   alu_out ← A + ~imm20 + 1
       A ← alu_out
       CC ← CC_COMPARE(A, imm20, alu_out)
       ENDE
```

### LCW — Load Complemented Word (0x3A)

```
PREP1-3: EA → P; bus_addr=EA
EX1:     C ← bus_data_r; A ← C_mux
EX2:     alu_out ← 0 + ~C_mux + 1        ; negate via ALU
         A ← alu_out
         RR[r] ← alu_out
         P ← {Q, 2'b00}
EX3:     CC ← CC_COMP(alu_out)
         ENDE
```

### LAW — Load Absolute Word (0x3B)

```
PREP1-3: EA → P; bus_addr=EA
EX1:     C ← bus_data_r; A ← C_mux
EX2:     if C_mux[0]=0: RR[r] ← A; P ← {Q,00}; phase → EX4
          if C_mux[0]=1: alu_out ← 0 + ~C_mux + 1; A ← alu_out; RR[r] ← alu_out; P ← {Q,00}
EX3:     (negative path only — skip for positive)
EX4:     CC ← CC_ABS(A)
         ENDE
```

### AH — Add Halfword (0x50)

```
PREP1-3: EA → P
EX1:     C ← M.H[P]; A ← RR[r]           ; halfword in bits 16:31 of bus_data_r
EX2:     alu_out ← A + sext(C_mux[16:31])
         A ← alu_out; RR[r] ← alu_out
         CC ← CC_ARITH(alu_out)
         P ← {Q, 2'b00}
EX3:     ENDE
```

### SH — Subtract Halfword (0x58)

```
PREP1-3: EA → P
EX1:     C ← M.H[P]; A ← RR[r]
EX2:     alu_out ← A + ~sext(C_mux[16:31]) + 1
         A ← alu_out; RR[r] ← alu_out
         CC ← CC_ARITH(alu_out)
         P ← {Q, 2'b00}
EX3:     ENDE
```

### CH — Compare Halfword (0x51)

```
PREP1-3: EA → P
EX1:     C ← M.H[P]; A ← RR[r]
EX2:     alu_out ← A + ~sext(C_mux[16:31]) + 1
         A ← alu_out
         CC ← CC_COMPARE(A, C_mux, alu_out)
         P ← {Q, 2'b00}
EX3:     ENDE
```

### LH — Load Halfword (0x52)

```
PREP1-3: EA → P
EX1:     C ← M.H[P]
         A ← sext(C_mux[16:31])
EX2:     RR[r] ← A
         CC ← CC_ARITH(A)
         P ← {Q, 2'b00}
EX3:     ENDE
```

### STH — Store Halfword (0x55)

```
PREP1-3: EA → P
EX1:     A ← RR[r]
EX2:     M.H[P] ← A[16:31]               ; memory module selects correct halfword
         P ← {Q, 2'b00}
EX3:     ENDE
```
*Note: STH does not update CC.*

### LB — Load Byte (0x72)

```
PREP1-3: EA → P
EX1:     C ← M.B[P]
         A ← {24'b0, C_mux[24:31]}       ; zero extend byte
EX2:     RR[r] ← A
         CC ← CC_BYTE(A)
         P ← {Q, 2'b00}
EX3:     ENDE
```

### STB — Store Byte (0x75)

```
PREP1-3: EA → P
EX1:     A ← RR[r]
EX2:     M.B[P] ← A[24:31]               ; memory module selects correct byte
         P ← {Q, 2'b00}
EX3:     ENDE
```
*Note: STB does not update CC.*

### CB — Compare Byte (0x71)

```
PREP1-3: EA → P
EX1:     C ← M.B[P]
         A ← {24'b0, RR[r][24:31]}       ; zero extend low byte of register
EX2:     alu_out ← A + ~{24'b0, C_mux[24:31]} + 1
         CC ← CC_COMPARE(A, C_mux, alu_out)
         P ← {Q, 2'b00}
EX3:     ENDE
```

### MTH — Modify and Test Halfword (0x53)

```
PREP1-3: EA → P
EX1:     C ← M.H[P]
         A ← sext(C_mux[16:31])
EX2:     alu_out ← A + sext(R, 16)       ; R field as 16-bit signed increment
         A ← alu_out
EX3:     M.H[P] ← alu_out[16:31]
EX4:     CC ← CC_ARITH(alu_out)
         ENDE
```

### MTB — Modify and Test Byte (0x73)

```
PREP1-3: EA → P
EX1:     C ← M.B[P]
         A ← {24'b0, C_mux[24:31]}
EX2:     alu_out ← A + sext(R, 8)        ; R field as 8-bit signed increment
         A ← alu_out
EX3:     M.B[P] ← alu_out[24:31]
EX4:     CC ← CC_BYTE(alu_out)
         ENDE
```

### LCH — Load Complemented Halfword (0x5A)

```
PREP1-3: EA → P
EX1:     C ← M.H[P]
         A ← sext(C_mux[16:31])
EX2:     alu_out ← 0 + ~A + 1
         A ← alu_out; RR[r] ← alu_out
         P ← {Q, 2'b00}
EX3:     CC ← CC_COMP(alu_out)
         ENDE
```

### LAH — Load Absolute Halfword (0x5B)

```
PREP1-3: EA → P
EX1:     C ← M.H[P]
         A ← sext(C_mux[16:31])
EX2:     if A[0]=0: RR[r] ← A; P ← {Q,00}; phase → EX4
         if A[0]=1: alu_out ← 0 + ~A + 1; A ← alu_out; RR[r] ← alu_out; P ← {Q,00}
EX3:     (negative path only)
EX4:     CC ← CC_ABS(A)
         ENDE
```

### BCR — Branch on Conditions Reset (0x68)

Word-index instruction (EA computed through PREP3).
Branch taken when `CC AND R = 0` (no condition bits match mask).
If R=0, always branches — unconditional branch.

```
PREP1-3: EA → P
EX1:   if (CC AND R) = 0: P ← ea; ENDE  ; branch taken
       else: P ← {Q, 2'b00}; ENDE       ; fall through
```

### BCS — Branch on Conditions Set (0x69)

Word-index instruction (EA computed through PREP3).
Branch taken when `CC AND R ≠ 0` (at least one condition bit matches mask).
If R=0, never branches — effective no-op.

```
PREP1-3: EA → P
EX1:   if (CC AND R) ≠ 0: P ← ea; ENDE ; branch taken
       else: P ← {Q, 2'b00}; ENDE       ; fall through
```

### BAL — Branch and Link (0x6A)

```
PREP1-3: EA → P
EX1:   RR[r] ← {15'b0, Q}               ; R[0:14]=0, R[15:31]=next instruction word addr
       P ← ea
       ENDE
```

### BDR — Branch on Decrementing Register (0x64)

Branch taken when result is **positive** (R[0]=0 and R≠0).
Zero and negative results fall through.

```
PREP1-3: EA → P
EX1:   RR[r] ← RR[r] - 1
       if RR[r][0]=0 and RR[r]≠0: P ← ea; ENDE   ; positive → branch taken
       else: P ← {Q, 2'b00}; ENDE                 ; zero or negative → fall through
```

### BIR — Branch on Incrementing Register (0x65)

Branch taken when result is **negative** (R[0]=1).
Zero and positive results fall through.

```
PREP1-3: EA → P
EX1:   RR[r] ← RR[r] + 1
       if RR[r][0]=1: P ← ea; ENDE      ; negative → branch taken
       else: P ← {Q, 2'b00}; ENDE       ; zero or positive → fall through
```

### LD — Load Doubleword (0x12)

```
PREP1-3: EA → P; bus_addr=EA             ; P[32:33] = 00 (doubleword aligned)
EX1:     C ← M[P]; A ← C_mux            ; high word
EX2:     RR[r] ← A; AWZ ← (A=0)
         bus_addr ← P + 4
EX3:     C ← bus_data_r; A ← C_mux      ; low word
EX4:     RR[r+1] ← A; AWZ ← AWZ AND (A=0)
         P ← {Q, 2'b00}
EX5:     CC ← CC_ARITH_DW(A, AWZ)
         ENDE
```

### STD — Store Doubleword (0x15)

```
PREP1-3: EA → P
EX1:     A ← RR[r]
EX2:     M[P] ← A                        ; high word
EX3:     A ← RR[r+1]
EX4:     M[P+4] ← A                      ; low word
         P ← {Q, 2'b00}
EX5:     ENDE
```
*Note: STD does not update CC.*

### AD — Add Doubleword (0x10)

```
PREP1-3: EA → P; bus_addr=EA
EX1:     C ← M[P]; A ← RR[r]            ; high words
EX2:     alu_out ← A + C_mux
         A ← alu_out; RR[r] ← alu_out
         bus_addr ← P + 4
EX3:     C ← bus_data_r; A ← RR[r+1]    ; low words
EX4:     alu_out ← A + C_mux + carry
         A ← alu_out; RR[r+1] ← alu_out; AWZ ← (alu_out=0)
         P ← {Q, 2'b00}
EX5:     CC ← CC_ARITH_DW(RR[r], AWZ)
         ENDE
```

### SD — Subtract Doubleword (0x18)

```
PREP1-3: EA → P; bus_addr=EA
EX1:     C ← M[P]; A ← RR[r]            ; high words
EX2:     alu_out ← A + ~C_mux + 1
         A ← alu_out; RR[r] ← alu_out
         bus_addr ← P + 4
EX3:     C ← bus_data_r; A ← RR[r+1]    ; low words
EX4:     alu_out ← A + ~C_mux + borrow
         A ← alu_out; RR[r+1] ← alu_out; AWZ ← (alu_out=0)
         P ← {Q, 2'b00}
EX5:     CC ← CC_ARITH_DW(RR[r], AWZ)
         ENDE
```

### CD — Compare Doubleword (0x11)

```
PREP1-3: EA → P; bus_addr=EA
EX1:     C ← M[P]; A ← RR[r]
EX2:     alu_out ← A + ~C_mux + 1
         bus_addr ← P + 4
EX3:     C ← bus_data_r; A ← RR[r+1]
EX4:     alu_out ← A + ~C_mux + borrow; AWZ ← (prev_alu_out=0)
         P ← {Q, 2'b00}
EX5:     CC ← CC_COMPARE_DW(RR[r], C_mux, alu_out, AWZ)
         ENDE
```

### LCD — Load Complemented Doubleword (0x1A)

```
PREP1-3: EA → P; bus_addr=EA
EX1:     C ← M[P]; A ← C_mux            ; high word
EX2:     alu_out ← 0 + ~A + 1
         A ← alu_out; RR[r] ← alu_out
         bus_addr ← P + 4
EX3:     C ← bus_data_r; A ← C_mux      ; low word
EX4:     alu_out ← 0 + ~A + carry
         A ← alu_out; RR[r+1] ← alu_out; AWZ ← (alu_out=0)
         P ← {Q, 2'b00}
EX5:     CC ← CC_COMP_DW(A, AWZ)
         ENDE
```

### LAD — Load Absolute Doubleword (0x1B)

```
PREP1-3: EA → P; bus_addr=EA
EX1:     C ← M[P]                        ; high word — check sign
EX2:     if C_mux[0]=0: phase → EX5      ; positive
         bus_addr ← P + 4
EX3:     C ← bus_data_r; A ← C_mux      ; negate low word
         alu_out ← 0 + ~A + 1; RR[r+1] ← alu_out; AWZ ← (alu_out=0)
EX4:     C ← M[P]; A ← C_mux            ; negate high word
         alu_out ← 0 + ~A + carry; RR[r] ← alu_out
         P ← {Q, 2'b00}; phase → EX7
EX5:     C ← bus_data_r; A ← C_mux      ; load low word, positive
         RR[r+1] ← A; AWZ ← (A=0); bus_addr ← P
EX6:     C ← M[P]; A ← C_mux            ; load high word, positive
         RR[r] ← A
         P ← {Q, 2'b00}
EX7:     CC ← CC_ABS_DW(A, AWZ)
         ENDE
```