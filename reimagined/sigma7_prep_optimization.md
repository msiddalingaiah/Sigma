# Sigma 7 Prep Phase Optimization

## Overview

This document describes a proposed optimization to the instruction fetch and
address calculation pipeline that eliminates one cycle per instruction by
absorbing the instruction load into ENDE.

The key insight is that ENDE already has a free bus cycle — it presents the
next instruction address and waits. If that address is presented **one cycle
before ENDE**, the instruction arrives on the bus exactly when ENDE fires,
and can be loaded into C/D/O/R in the same cycle.

---

## Constraint

The next instruction address must be presented on bus_addr **one cycle before
ENDE** in all cases:

- **Sequential flow:** present `{Q, 2'b00}` during EX(n-1) — always known
- **Taken branch:** present `ea` during EX1 (branch target resolved) — one extra EX cycle needed
- **Immediate instructions:** present `{Q, 2'b00}` during the free bus cycle before ENDE

---

## Phase Definitions

### ENDE

```
C/D/O/R  ← bus_data_r              ; instruction word loaded
P        ← p_inc                   ; increment to next instruction byte address
P[32:33] ← byte_offset(opcode, RR[X])  ; byte offset from opcode + low bits of index
A        ← RR[X] if X≠0, else 0   ; index register (or zero) for EA calculation
Q        ← (not yet — P is being incremented this cycle)
bus_addr ← bus_data_r[15:31]       ; present reference address (direct EA or indirect pointer)
phase    → PREP1
```

Note: bus_addr uses bus_data_r[15:31] directly (combinatorial from the
transparent C latch), which is the reference address field of the instruction.
For direct instructions this is the base word address; for indirect it is the
address of the indirect pointer word. Either way the correct value goes on the
bus immediately.

### PREP1

```
Q        ← P                       ; save incremented next instruction address
if indirect:
    C/D      ← bus_data_r          ; resolved indirect pointer word loaded
    bus_addr ← A + C_mux[15:31]    ; C_mux transparent — pointer available immediately
if direct:
    bus_addr ← A + D[15:31]        ; D now registered from ENDE
phase    → PREP2
```

Note: in the indirect case, D is being loaded this cycle so cannot be used
combinatorially. C_mux is used instead, exploiting the transparent latch
exactly as elsewhere in the design.

### PREP2

```
P[15:31] ← A + D[15:31]            ; uniform in all cases — no conditional
phase    → EX1
; operand arrives at EX1
```

By PREP2, A and D are always correctly set up:
- **A** = RR[X] (indexed) or 0 (non-indexed) — loaded in ENDE
- **D** = reference address field (direct) or resolved pointer word address
  (indirect) — loaded in ENDE or PREP1 respectively

So PREP2 is identical regardless of addressing mode.

---

## Addressing Cases

| Case | ENDE bus_addr | PREP1 action | PREP2 |
|------|--------------|--------------|-------|
| Direct, non-indexed | inst[15:31] | bus_addr ← D[15:31] (redundant, harmless) | P[15:31] ← 0 + D[15:31] ✓ |
| Direct, indexed | inst[15:31] | bus_addr ← A + D[15:31] | P[15:31] ← A + D[15:31] ✓ |
| Indirect, non-indexed | inst[15:31] | D ← bus_data_r; bus_addr ← C_mux[15:31] | P[15:31] ← 0 + D[15:31] ✓ |
| Indirect, indexed | inst[15:31] | D ← bus_data_r; bus_addr ← A + C_mux[15:31] | P[15:31] ← A + D[15:31] ✓ |

P[32:33] (byte offset) is computed in ENDE for all cases — it depends only
on the opcode and the low bits of RR[X], both known immediately.

---

## C Register Load Points

C is a transparent latch. It is loaded:

- **ENDE:** C ← instruction word (always)
- **PREP1:** C ← resolved indirect pointer word (indirect only)

This is the same transparent-latch mechanism already used elsewhere: C_mux
reflects the arriving data combinatorially within the same cycle it is loaded,
making it available for bus_addr before the clock edge registers it into D.

---

## Cycle Count Comparison

| Instruction type | Current cycles | Proposed cycles | Saving |
|-----------------|---------------|-----------------|--------|
| Immediate (LI, AI, LCFI) | ENDE + PREP1 + EX | ENDE + EX | 1 |
| Direct non-indexed | ENDE + PREP1 + PREP3 + EX | ENDE + PREP1 + PREP2 + EX | 0 |
| Direct indexed | ENDE + PREP1 + PREP3 + EX | ENDE + PREP1 + PREP2 + EX | 0 |
| Indirect | ENDE + PREP1 + PREP2 + PREP3 + EX | ENDE + PREP1 + PREP2 + EX | 1 |
| Taken branch | ENDE + PREP1 + PREP3 + EX | ENDE + PREP1 + PREP2 + EX + 1 | -1 |

Notes:
- Direct instructions save nothing in total cycle count — the saving from
  absorbing the instruction load into ENDE is offset by PREP2 being needed
  where PREP3 was before. The benefit is structural simplicity.
- Immediate and indirect instructions save one cycle each.
- Taken branches cost one extra cycle for the address presentation delay.
- The real gain is uniformity: all non-branch instructions now have exactly
  two prep phases (PREP1, PREP2), and ENDE always loads the instruction.

---

## Open Questions

1. **Branch penalty:** is one extra EX cycle for taken branches acceptable?
   For non-taken conditional branches (BCR/BCS), no penalty — {Q, 2'b00} is
   already known and can be presented before ENDE.

2. **Immediate instructions:** these currently skip PREP entirely. With this
   scheme they still skip PREP1 and PREP2 (no EA needed), but ENDE still
   loads the instruction. The free bus cycle before ENDE needs to present
   {Q, 2'b00} — is there always a free bus cycle in the EX sequence of
   immediate instructions?

3. **PCP5 boot:** the initial fetch (ENDE from PCP5) still works unchanged —
   P is preset to 0x94 so p_inc = 0x98, which is presented on the bus and
   the instruction arrives at the first ENDE.
