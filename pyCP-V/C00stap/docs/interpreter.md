# A user-mode instruction interpreter

A design for running **real Sigma programs** on the translated monitor. A small interpreter
executes a user program's instructions in **slave (user) mode only**. Whenever the program
traps, with a `CAL` or anything else, control goes to the Python monitor, which is the one
that already runs: the CAL dispatch, the file system, the console and the scheduler.

The full emulator considered earlier (an instruction-level monitor, privileged instructions,
I/O, interrupts) is not the plan. The monitor stays hand-translated Python. Only user code is
interpreted.

> **Reference:** the instruction semantics come from Bob Supnik's Sigma simulator in simh,
> <https://github.com/simh/simh/tree/master/sigma> (copyright 2007–2008 Robert M Supnik,
> X11-style license: the translation keeps his notice). Citations like `sigma_cpu.c:870` are to
> that source, fetched 2026-11-04. Where the Sigma 7 and 9 differ, simh says so, and so does
> this note.

## 1. What simh settles at once

- **`INT`** (`sigma_cpu.c:870`–`:878`): CC ← bits 0–3, R ← bits 4–15, R|1 ← bits 16–31. For an odd R
  the second store wins, so R gets bits 16–31. This is exactly the assumption in
  [`recovery.md`](recovery.md) §6, and the boot types, `SEQPOS` and FIX1's `CHKCON` all rest on it.
- **`CLM`** (`:1215`–`:1222`): CC3 and CC4 compare the register with the **first** word, and CC1 and
  CC2 with the **second**. So in `SECCHK` ([`files.md`](files.md) §10), `BE` after `CLM,D2 NONE`
  means "equal to `NONE`" and `BCR,12` means "equal to `ALL`", as its comments say.
- **Registers are memory**: a byte address below X'40', word 0–15, is the current register
  block (`sigma_map.c:168`–`:169`). `cal.py`'s `fetch` already does this for the monitor (`CVREG`).
  A doubleword access is forced to an even register (`:182`–`:184`).

## 2. The user's machine

| State | simh | Here |
|---|---|---|
| Registers | `R`: the current block of 16 (`PSW2`'s register pointer) | `sched.uregs[u]`, the same 16 words `cal.py` already reads and writes |
| PSD word 1 | CC (bits 0–3); floating controls FR, FS, FZ, FN (4–7); MS (8, master/slave); MM (9, map); DM, AM (10, 11: decimal and arithmetic trap masks); PC (15–31, a 17-bit word address) (`sigma_defs.h:206`–`:241`) | MS always 1 (slave); CC in `sched.psd_cc[u]` as now; FR/FS/FZ/FN and DM/AM kept per user; the PC in the interpreter |
| PSD word 2 | write key, interrupt inhibits, register pointer (`:245`–`:277`) | not needed: one register block, and the monitor owns interrupts |
| Memory | word-addressed; byte address = word × 4; 17-bit virtual addresses; the map and access codes (`sigma_map.c`) | `sched.umem[u]` as **words (ints only)**. Today it also holds 4-character strings from `cal.py`'s `put_text`, and that changes (§7) |

The condition codes are four bits, **CC1** = 8, CC2 = 4, CC3 = 2, **CC4** = 1. The usual rules:
- **`CC34_W`** (`sigma_defs.h:435`): CC4 for a negative result, CC3 for positive, neither for 0;
- **`Add32`** (`sigma_cpu.c:2159`): CC1 is the carry, CC2 the overflow;
- **`Cmp32`** (`:2246`): a signed compare into CC3 (greater) or CC4 (less);
- **`CC234_CMP`**: CC2 is set when the operands have a 1 bit in common.

## 3. Decoding

Two formats (`sigma_cpu.c:55`–`:82`), both with the opcode in bits 1–7 and R in 8–11:
- **memory reference**: indirect (bit 0), index register X (12–14), address (15–31);
- **immediate**: a 20-bit literal, sign-extended. An immediate instruction with bit 0 set is a
  non-existent instruction (`ImmOp`, `:1883`).

**The effective address** (`Ea`, `:1897`): with the indirect bit, read the word at the address and
take its low 17 bits. Then add the index register, **scaled by the operand length**: a byte
instruction adds X as bytes, a doubleword one as doublewords (`R[xr] << lnt`, `:1917`). Shifts
take their type and count from the address instead (`EaSh`, `:1949`). `EXU` executes the word at
the effective address, and nesting is limited (`exu_lim` = 32, a simulator guard, `:179`,
`:1364`).

## 4. The instructions

**Phase 1** covers what `sigma_cpu.c` handles, except the privileged instructions:

| Group | Instructions | Notes |
|---|---|---|
| Loads | `LI`, `LB`, `LH`, `LCH`, `LAH`, `LW`, `LCW`, `LAW`, `LD`, `LCD`, `LAD`, `LS`, `LM` | `LM`/`STM` take the count from the CC (0 = 16, `:715`). Negating the most negative number sets CC2 and traps if AM is set |
| Stores | `STB`, `STH`, `STW`, `STD`, `STS`, `STM`, `XW` | `STH` sets CC2 when the register isn't a sign-extended halfword (`:777`) |
| CC and floating controls | `LCFI`, `LCF`, `STCF` | |
| Arithmetic | `AI`, `AH`, `AW`, `AD`, `AWM`, `SH`, `SW`, `SD`, `MI`, `MH`, `MW`, `DH`, `DW` | Multiply and divide use the R, R+1 pair (`SMul64`, `SDiv64`). A divide overflow sets CC2. **`TR_FIX`** if AM is set |
| Modify and test | `MTB`, `MTH`, `MTW` | R is the signed modifier; 0 only tests |
| Logical | `AND`, `OR`, `EOR` | |
| Compare | `CI`, `CB`, `CH`, `CW`, `CD`, `CS`, `CLR`, `CLM` | |
| Shift | `S` (8 types: logical, circular and arithmetic, single and double, and searching), `SF` | `Shift`, `:1973`. On the Sigma 5–7 the searching types act as arithmetic (`:1229`) |
| Convert | `CVA`, `CVS` | |
| Stack | `PSW`, `PLW`, `PSM`, `PLM`, `MSP` | A stack-pointer doubleword: the top's word address, then the space and word counts with their trap enables (`sigma_defs.h:281`–`:290`). Overflow traps **`TR_PSH`** unless disabled; then CC1/CC3 (`TestSP1`, `:2258`) |
| Control | `EXU`, `BCS`, `BCR`, `BIR`, `BDR`, `BAL` | `BCS`/`BCR` use R as a CC mask |
| Other | `INT`, `ANLZ`, `LAS` (an option), `CAL1`–`CAL4` | |
| Byte strings | `MBS`, `CBS`, `TBS`, `TTBS` | Immediate format. R+1 holds the count (bits 0–7) and the destination byte address; R the source (`S_GETMCNT`, `sigma_defs.h:171`–`:175`) |

**Later:**
- floating point (`FAS`, `FSS`, `FMS`, `FDS` and the long forms, `sigma_fp.c`);
- decimal, `EBS`, `PACK` and `UNPK` (`sigma_cis.c`).

Until then they trap as **unimplemented** (`TR_UNI`, X'41'), which is what a machine without the
option does (`:1609`).

**Privileged** in slave mode, so they trap (X'40' with CC3, `TR_PRV`): `LPSD`, `XPSD`, `LRP`, `MMC`,
`LRA`, `LMS`, `WAIT`, `RD`, `WD`, `AIO`, `SIO`, `TIO`, `TDV`, `HIO` (`:1443`–`:1603`). Some opcodes trap
as non-existent *and* privileged (`TR_NXI|TR_PRV`).

**Machine model**: the interpreter follows the configured machine (`--machine`; `sigma9` by
default). A few results differ by model:
- odd-register doubleword arithmetic is `TR_INVREG` on the Sigma 8/9 (`:916`);
- the searching shifts;
- `LAS`/`LMS`;
- `ANLZ`'s report of a protected address (`:833`–`:866`).

## 5. Traps

A trap rolls the PC back to the instruction that trapped and executes the trap location's
`XPSD` (`sigma_cpu.c:493`–`:504`, `cpu_trap_or_int`, `:1838`). The trap's CC bits are ORed into the
new PSD's CC, and can also step its PC (`:1865`–`:1869`):

| Location | Trap | CC | simh |
|---|---|---|---|
| X'40' | non-existent instruction | CC1 | `TR_NXI` |
| X'40' | non-existent memory | CC2 | `TR_NXM` |
| X'40' | privileged instruction | CC3 | `TR_PRV` |
| X'40' | memory protection | CC4 | `TR_MPR` |
| X'41' | unimplemented instruction | | `TR_UNI` |
| X'42' | push-down overflow | | `TR_PSH` |
| X'43' | fixed-point overflow | | `TR_FIX` |
| X'44' | floating point | | `TR_FLT` |
| X'45' | decimal | | `TR_DEC` |
| X'46' | watchdog timer | | `TR_WAT` |
| X'48'–X'4B' | `CAL1`–`CAL4` | R | `TR_C1`…`TR_C4` |

(`sigma_defs.h:351`–`:366`.) In CP-V each of these is an `XPSD` into the monitor. Here the
interpreter stops and hands the trap to Python:

- **`CAL1`**, trap X'48', goes to `cal.py` exactly as now. `cal1p11` already reads the CAL from
  the user's memory at the PSD's address, and follows indirect, index and `EXU` chains to the
  FPT. A new request type carries the CAL's address in place of `Cal1`'s placed FPT. The result
  comes back as it does to `cpv`:
  - **the CC**: resume after the CAL;
  - **`("ROUTINE", sr1, sr3)`**: resume at the user's error or abnormal address, with SR3 in R10
    (`IOSPRTN`, `cal.py` `finish`).

  Exits (`M:EXIT`, `M:ERR`, `M:XXX`) end the program as they do now.
- **`CAL2`–`CAL4`**: only CAL1 (X'48') is translated in `cal.py`. What CP-V does at X'49'–X'4B'
  hasn't been read. Until it is, they end the program as an abort.
- **Any other trap**: CP-V's trap handling for a user (its trap control CALs, `M:TRAP`/`M:TRTN`
  and the TCB) hasn't been read. Until it is, a trap ends the program with an abort, and the
  trap location, CC and the instruction's address are typed on the console.

## 6. Running under the scheduler

An interpreted program is one more kind of ghost program: a generator, as the stand-ins are, in
place of `pyprog`'s thread.
- **A slice:** it runs a slice of instructions and yields `Compute(n)`, so the clock, quantum and
  preemption work as for any user. The scheduler's clock unit is 2 ms. At roughly a microsecond
  an instruction on a Sigma 7, a slice of 2,000 instructions is one unit (a setting, not a
  measurement).
- **A CAL:** it yields the CAL request, and the monitor's answer comes back through the
  generator.
- **Preemption** happens between instructions, so a program that never calls a service no longer
  holds the system, which is one of `pyprog`'s open points
  ([`python-programs.md`](python-programs.md)).

The program's identity (its account, the program name for an execute vehicle) is set as
`pyprog` sets it now.

## 7. Memory

`umem[u]` becomes words only, a dict from word address to a 32-bit int, with absent words
reading as 0. Bytes and halfwords are big-endian within the word, as on the Sigma.
- **`cal.py`'s text helpers** (`put_text`, `read_text`, `write_bytes`) pack and unpack EBCDIC, or
  for now the characters they store, into words. Only their code changes, not their callers.
- **No protection in phase 1.** In CP-V a user's virtual space is mapped page by page, with access
  codes, and the monitor's pages are protected (`sigma_map.c`). Here every address a program
  touches is its own. Later, the pages the monitor gave the user (`JX:CMAP`, not modeled) could
  give `TR_MPR` and `TR_NXM`.
- **Where a program goes:** the load module decides (§8). Hand-written test programs go above the
  JIT (`J_JIT` = X'8C00', `cal.py:34`), where a user's own area starts.

## 8. Programs to run

1. **Test programs**, assembled with the Python port of AP (`Sigma/AP/ap_project`), at a fixed
   origin. Its output is an image of bytes, not Sigma's relocatable object format, which is
   enough at a fixed address. They cover:
   - each instruction group against simh's rules;
   - `M:TYPE`, file CALs and the error returns;
   - `M:EXIT`, `M:ERR`, `M:XXX`;
   - a trap that ends the program.
2. **Real load modules** from the Sigma tapes. This needs:
   - the tape format;
   - CP-V's load-module format, from its loader (`LDR`, `SEGLD`, `STEP`/`STPNR`), documented
     first as usual;
   - a loader stand-in, so that `GJOB NAME` starts a real processor.

The diagnostics in `Sigma/SigmaFiles` (`7decimal.abs`, `7intrap.abs` and others) run on the bare
machine and use privileged instructions. Parts of them may still serve as instruction checks
once the interpreter can load an absolute image.

## Phase 1: what is built (2026-11-04)

| Piece | Code | Notes |
|---|---|---|
| The CPU | `python/uts/cpu.py` | The §4 phase 1 groups, ported from `sigma_cpu.c` with its notice. Traps as §5. The machine model (`sigma9` or `sigma7`) decides `TR_INVREG`, the searching shifts and `LAS`. `SF` traps as unimplemented with floating point, although it is a standard instruction, because it needs `sigma_fp.c`'s `ShiftF` |
| A small assembler | `python/uts/asm.py` | For test programs: labels, `ORG`, `DATA`, `TEXT`, `TEXTC`, `RES`, `BOUND`, `EQU`, `END`, the mnemonics from the opcode table, shifts as `SLS`…`SSD`, `BA()`. The Python port of AP has no instruction mnemonics of its own, because they come from `SIG7FDP`, a Meta-Symbol procedure file built on `S:SIN`. That is left for when real sources are assembled |
| Interpreted ghosts | `python/uts/interp.py` | An absolute image is kept as a keyed file (a header record and word records), so `GJOB NAME` finds it and a disc image keeps it. `--file host.s=NAME` assembles and stores one. A CAL1 is a `CalAt` request (`sched.py`); `cal.trap` takes the CAL from memory |
| Words-only memory | `cal.py` | `put_text`, `read_text` and `write_bytes` pack Latin-1 bytes into words; `write_bytes` keeps the other bytes of a word it touches |

Tests: `python/tests/test_cpu.py` (instructions against simh's rules) and `test_interp.py`
(programs under the scheduler: console output, `M:KEYIN`, a trap that ends the program, a program
that never calls the monitor, `--file`).

**Speed:** about 0.8 million instructions a second in CPython on this machine, near a real Sigma
7. The slice (`interp.SLICE` = 2,000 a clock unit) means a program that never calls the monitor
runs about 10 million instructions in each 10 simulated seconds of a key-in session.

**Limits of phase 1:**
- **Where programs go.** They belong at X'D000' and up: the `pyprog` stand-ins use X'A000'–X'C1FF'
  for their FPT, CAL and buffers, and an aborting program's message and `CAL1,9` go there too.
- **File I/O** works with the program's own DCBs, read and written in place in its memory
  ([`dcb.md`](dcb.md)). An image's DCB table, its `F:`/`M:` labels, goes in the user's `J:DCBLINK`.
  Device DCBs in memory aren't handled yet.
- **`EXU` past 32 levels** traps as a non-existent instruction. In simh it stops the simulator.
- **No pre-checks.** The readability checks before a branch or a string move (§7, no protection)
  aren't made.

## 9. Departures from the machine

| Machine | Here | Why |
|---|---|---|
| Traps go to the monitor through `XPSD` at X'40'–X'4B' | The interpreter stops and Python handles the trap: CAL1 through `cal.py`, the others as an abort | The monitor is Python; CP-V's user trap handling isn't read |
| Paged virtual memory with access protection | One flat word space per user, no protection | The monitor's paging (`JX:CMAP`) isn't modeled |
| 16 register blocks, `LRP`, interrupts | One block per user | User mode only |
| Real time per instruction | A slice of instructions per clock unit | The scheduler's clock |
| Floating point, decimal, `EBS` | Trap as unimplemented until phase 2 | Phase 1 is the integer core |

## Open questions

- **CAL2–CAL4 and user traps** in CP-V: where they go, and how `M:TRAP`, `M:TRTN` and the TCB
  return a trap to the user. Not read.
- **The slice size**: instructions per clock unit is a guess, and so is the instruction timing.
- **The EBCDIC question**: memory text is characters today. Real programs will expect EBCDIC
  bytes, and so will the files they read. The file system already keeps keys and names in
  EBCDIC.
- **A Sigma 7 versus 9 choice** for programs from the tapes (CP-V C00 runs on both).
