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

### PCP5 — Stable Reset/Halt State

Phase held during reset. On release of reset, ENDE is asserted immediately:

```
PCP5: if !reset: ENDE
      ; otherwise hold in PCP5
```

### ENDE Signal

ENDE fires at the last execute phase of every instruction. It increments P
and presents the next instruction address to memory, then jumps to PREP1:

```
ENDE: P ← P + 4                          ; increment to next instruction byte address
      bus_addr ← p_inc                   ; present to memory: instruction arrives at PREP1
      phase → PREP1
```

### Prep Phases

PREP1 loads the instruction that arrived from memory (presented during previous ENDE),
decodes it, saves P to Q, and resets A to 0 for EA calculation:

```
PREP1: C ← bus_data_r                    ; instruction word into C (transparent latch)
       D ← bus_data_r                    ; instruction word into D (for EA calc)
       O ← bus_data_r[1:7]               ; opcode
       R ← bus_data_r[8:11]              ; R field
       Q ← P[15:31]                      ; save next instruction word address
       A ← 0                             ; clear A for EA calculation (no indexing yet)
       if i=0 and immediate: phase → EX1 ; LCFI, LI skip EA calc
       if i=0 and memory:    phase → PREP3
       ; else fall through to PREP2 (indirect)
```

```
PREP2: C ← bus_data_r                    ; indirect pointer word (D[15:31] was on bus)
       D ← bus_data_r                    ; resolved pointer into D
       bus_addr ← {D[15:31], 2'b00}      ; present resolved address for PREP3/EX1
```

```
PREP3: P ← ea                            ; EA = {A[15:31] + D[15:31], P[32:33]}
       bus_addr ← ea                     ; present EA: M[EA] arrives at EX1
```

After PREP3, P holds the complete effective byte address.

---

## Implemented Instructions

### LCFI — Load Conditions and FP Immediate (0x02)

Immediate instruction (skips PREP3). With all-zero fields, acts as a no-op.
Loaded into C/D/O on reset as the first instruction to execute.

```
PREP1: (immediate) phase → EX1
EX1:   (no-op)
EX2:   if D[10]: CC ← D[24:27]           ; direct CC load
       ENDE
```

### LI — Load Immediate (0x22)

Immediate instruction. imm20 = sign-extended D[12:31].

```
PREP1: (immediate) phase → EX1
EX1:   (no-op)
EX2:   RR[r] ← imm20
       CC ← CC_ARITH(imm20)              ; alu_op=PASSA, alu_out=imm20
       ENDE
```

### LW — Load Word (0x32)

```
PREP1-3: EA → P; bus_addr=EA             ; M[EA] arrives at EX1
EX1:     C ← bus_data_r                  ; C_mux = M[EA]
         A ← C_mux
EX2:     RR[r] ← A
         CC ← CC_ARITH(A)               ; alu_op=PASSA, alu_out=A
         P ← {Q, 2'b00}                 ; restore next instruction address to P
EX3:     ENDE
```

### STW — Store Word (0x35)

```
PREP1-3: EA → P
EX1:     A ← RR[r]
EX2:     M[P] ← A                        ; write to EA (still in P)
         P ← {Q, 2'b00}                 ; restore next instruction address to P
EX3:     ENDE
```
*Note: STW does not update CC.*

### AW — Add Word (0x30)

```
PREP1-3: EA → P; bus_addr=EA
EX1:     C ← bus_data_r                  ; C_mux = M[EA]
         A ← RR[r]
EX2:     alu_out ← A + C_mux
         A ← alu_out
         RR[r] ← alu_out
         CC ← CC_ARITH(alu_out)
         P ← {Q, 2'b00}
EX3:     ENDE
```

### SW — Subtract Word (0x38)

```
PREP1-3: EA → P; bus_addr=EA
EX1:     C ← bus_data_r
         A ← RR[r]
EX2:     alu_out ← A + ~C_mux + 1
         A ← alu_out
         RR[r] ← alu_out
         CC ← CC_ARITH(alu_out)
         P ← {Q, 2'b00}
EX3:     ENDE
```

### CW — Compare Word (0x31)

```
PREP1-3: EA → P; bus_addr=EA
EX1:     C ← bus_data_r
         A ← RR[r]
EX2:     alu_out ← A + ~C_mux + 1
         A ← alu_out
         CC ← CC_COMPARE(A, C_mux, alu_out)
         P ← {Q, 2'b00}
EX3:     ENDE
```
*Note: CW does not write back to RR.*

### AND (0x4B), OR (0x49), EOR (0x48)

```
PREP1-3: EA → P; bus_addr=EA
EX1:     C ← bus_data_r
         A ← RR[r]
EX2:     alu_out ← A AND/OR/XOR C_mux
         A ← alu_out
         RR[r] ← alu_out
         CC ← CC_ARITH(alu_out)
         P ← {Q, 2'b00}
EX3:     ENDE
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

### BCR — Branch on Condition Register (0x68)

```
PREP1: (immediate) phase → EX1
EX1:   if CC AND R ≠ 0: P ← {D[15:31], 2'b00}; bus_addr ← P; ENDE
       else: ENDE                         ; fall through to next instruction
```

### BCS — Branch on Condition and Skip (0x69)

```
PREP1: (immediate) phase → EX1
EX1:   if CC AND R ≠ 0: ENDE             ; branch not taken: skip next instruction
       else: P ← P + 4; ENDE             ; branch taken: skip next word
```

### BAL — Branch and Link (0x6A)

```
PREP1-3: EA → P
EX1:   RR[r] ← {0, Q}                   ; save return address (Q = next instruction)
       P ← ea
       ENDE
```

### BDR — Branch and Decrement Register (0x64)

```
PREP1-3: EA → P
EX1:   RR[r] ← RR[r] - 1
       if RR[r] ≠ 0: P ← ea; ENDE       ; branch taken
       else: P ← {Q, 2'b00}; ENDE       ; branch not taken
```

### BIR — Branch and Increment Register (0x65)

```
PREP1-3: EA → P
EX1:   RR[r] ← RR[r] + 1
       if RR[r] ≠ 0: P ← ea; ENDE       ; branch taken
       else: P ← {Q, 2'b00}; ENDE       ; branch not taken
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