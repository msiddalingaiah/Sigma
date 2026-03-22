# SDS/Xerox Sigma 7 — Instruction Register Transfer Language

## Notation

| Symbol | Meaning |
|--------|---------|
| RR[n] | User-visible register n (0–15), mapped to word addresses 0–15 |
| R | 4-bit register field register (bits 28–31), loaded from instruction bits 8–11 |
| r | Value held in R; selects destination/source user register |
| x | X field of instruction (3 bits); index register selector for memory-reference instructions; repurposed as part of immediate operand for immediate instructions |
| i | I field of instruction (1 bit); 1 = indirect addressing |
| C | 32-bit memory interface register (transparent latch) |
| D | 32-bit secondary ALU input register |
| A | 32-bit primary ALU input register |
| B | 32-bit multiply/divide partner register (forms 64-bit A:B pair) |
| E | 8-bit floating-point exponent register |
| O | 7-bit opcode register |
| P | 19-bit effective address register (bits 15–33) |
| Q | 17-bit next instruction address register (bits 15–31) |
| CC | 4-bit condition code register (bits 1–4) |
| S | Sum bus — combinational ALU output, no dedicated register |
| M[addr] | 32-bit word memory access at byte address addr |
| M.H[addr] | 16-bit halfword memory access |
| M.B[addr] | 8-bit byte memory access |
| EA | Effective byte address, held in P after prep phases |
| sext(v) | Sign extend v to 32 bits |
| ENDE | End-of-instruction signal; fires in last execute phase |
| >> n | Right shift by n bits |
| << n | Left shift by n bits |
| ~ | Bitwise invert |

---

## Common Sequences

### ENDE Signal

ENDE fires at the last execute phase of every instruction. It simultaneously fetches
the next instruction and sets up registers for the following instruction's prep phases:

```
ENDE: C ← M[Q]                          ; fetch next instruction word
      O ← C[1:7]                         ; load opcode from bits 1-7
      D ← C                              ; instruction word into D via transparent C latch
      R ← C[8:11]                        ; load R field into 4-bit R register
      P ← P + 4                          ; increment to next instruction byte address

      ; Set up A and P[32:33] for EA calculation:
      if x=0:              A ← 0;              P[32:33] ← 00
      if x≠0, byte:        A ← RR[x] >> 2;    P[32:33] ← byte_offset
      if x≠0, halfword:    A ← RR[x] >> 1;    P[32:33] ← halfword_offset
      if x≠0, word:        A ← RR[x];         P[32:33] ← 00
      if x≠0, doubleword:  A ← RR[x] << 1;    P[32:33] ← 00
```

### Prep Phases

The prep phases calculate the effective address using the instruction word in D,
and save the next instruction address to Q:

```
PREP1: Q ← P[15:31]; if i=0 goto PREP3

PREP2: C ← M[C[15:31]]; D ← C           ; indirect: hardware masks C to bits 15-31
                                          ; resolved pointer loaded into D via transparent C

PREP3: P[15:31] ← S where S ← A + D[15:31]  ; word EA into P[15:31]
                                              ; P[32:33] retains byte offset from ENDE
```

After PREP3, P holds the complete effective byte address:
- **P[15:31]:** word address from EA calculation
- **P[32:33]:** byte offset within word, set during ENDE

---

## Word Arithmetic Instructions

### AW — Add Word (0x30)
```
PREP1-3: EA → P
EX1: A ← RR[r]
EX2: C ← M[P]; D ← C; S ← A + D; A ← S; RR[r] ← S
EX3: CC ← test(A); ENDE
```

### SW — Subtract Word (0x38)
```
PREP1-3: EA → P
EX1: A ← RR[r]
EX2: C ← M[P]; D ← C; S ← A + ~D + 1; A ← S; RR[r] ← S
EX3: CC ← test(A); ENDE
```

### CW — Compare Word (0x31)
```
PREP1-3: EA → P
EX1: A ← RR[r]
EX2: C ← M[P]; D ← C; S ← A + ~D + 1; A ← S
EX3: CC ← test(A); ENDE
```

### AI — Add Immediate (0x20)
```
PREP1: C ← sext(inst[12:31])            ; 20-bit sign-extended immediate (X field unused)
EX1: A ← RR[r]; D ← C
EX2: S ← A + D; A ← S; RR[r] ← S
EX3: CC ← test(A); ENDE
```

### CI — Compare Immediate (0x21)
```
PREP1: C ← sext(inst[12:31])            ; 20-bit sign-extended immediate (X field unused)
EX1: A ← RR[r]; D ← C
EX2: S ← A + ~D + 1; A ← S
EX3: CC ← test(A); ENDE
```

### LI — Load Immediate (0x22)
```
PREP1: C ← sext(inst[12:31])            ; 20-bit sign-extended immediate (X field unused)
EX1: A ← C
EX2: S ← A; RR[r] ← S
EX3: CC ← test(A); ENDE
```


---

## Halfword Arithmetic Instructions

### AH — Add Halfword (0x50)
```
PREP1-3: EA → P                          ; P[32:33] = halfword offset
EX1: A ← RR[r]
EX2: C ← M.H[P]; D ← sext(C[16:31]); S ← A + D; A ← S; RR[r] ← S
EX3: CC ← test(A); ENDE
```

### SH — Subtract Halfword (0x58)
```
PREP1-3: EA → P
EX1: A ← RR[r]
EX2: C ← M.H[P]; D ← sext(C[16:31]); S ← A + ~D + 1; A ← S; RR[r] ← S
EX3: CC ← test(A); ENDE
```

### CH — Compare Halfword (0x51)
```
PREP1-3: EA → P
EX1: A ← RR[r]
EX2: C ← M.H[P]; D ← sext(C[16:31]); S ← A + ~D + 1; A ← S
EX3: CC ← test(A); ENDE
```

---

## Halfword Load/Store Instructions

### LH — Load Halfword (0x52)
```
PREP1-3: EA → P
EX1: C ← M.H[P]; A ← sext(C[16:31])    ; sign extend halfword to 32 bits
EX2: S ← A; RR[r] ← S
EX3: CC ← test(A); ENDE
```

### STH — Store Halfword (0x55)
```
PREP1-3: EA → P
EX1: A ← RR[r]
EX2: S ← upward_align_halfword(A)        ; replicate low halfword to both halfword positions
     M.H[P] ← S                          ; write mask selects correct halfword
```
*Note: STH does not update CC.*

### LCH — Load Complemented Halfword (0x5A)
```
PREP1-3: EA → P
EX1: C ← M.H[P]; D ← sext(C[16:31])
EX2: S ← ~D + 1; A ← S; RR[r] ← S
EX3: CC ← test(A); ENDE
```

### LAH — Load Absolute Halfword (0x5B)
```
PREP1-3: EA → P
EX1: C ← M.H[P]; D ← sext(C[16:31])
EX2: if D[0]=0: S ← D;      A ← S; RR[r] ← S; goto EX4
     if D[0]=1: S ← ~D + 1; A ← S; RR[r] ← S
EX3: RR[r] ← S
EX4: CC ← test(A); ENDE
```

### MTH — Modify and Test Halfword (0x53)
```
PREP1-3: EA → P
EX1: C ← M.H[P]; A ← sext(C[16:31])    ; load halfword, sign extend to 32 bits
EX2: D ← sext(R, 16); S ← A + D; A ← S ; add sign-extended 4-bit R field as 16-bit increment
EX3: M.H[P] ← S                          ; write back modified halfword
EX4: CC ← test(A); ENDE
```

### LW — Load Word (0x32)
```
PREP1-3: EA → P
EX1: C ← M[P]; A ← C
EX2: S ← A; RR[r] ← S; P[15:31] ← Q
EX3: P ← P + 4; CC ← test(A); ENDE
```

### STW — Store Word (0x35)
```
PREP1-3: EA → P
EX1: A ← RR[r]
EX2: S ← A; M[P] ← S
```
*Note: STW does not update CC.*

### LCW — Load Complemented Word (0x3A)
```
PREP1-3: EA → P
EX1: C ← M[P]; D ← C
EX2: S ← ~D + 1; A ← S; RR[r] ← S
EX3: CC ← test(A); ENDE
```

### LAW — Load Absolute Word (0x3B)
```
PREP1-3: EA → P
EX1: C ← M[P]; D ← C
EX2: if D[0]=0: S ← D;       A ← S; RR[r] ← S; goto EX4
     if D[0]=1: S ← ~D + 1;  A ← S; RR[r] ← S
EX3: RR[r] ← S
EX4: CC ← test(A); ENDE
```
