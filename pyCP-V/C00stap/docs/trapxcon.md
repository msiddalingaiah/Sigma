# Trap control and exit control

Two CAL1,8 services a program uses to keep control when things go wrong: **`M:TRAP`** (X'14')
chooses which machine traps go to the program's own trap entry and sets the PSD's arithmetic
masks; **`M:XCON`** (X'19') names an *exit-control* routine, which the monitor runs when the
program ends, normally or not. Both keep their state in the JIT.

> Source: `ALTCP.txt` (`MTRAP`, `:1170`–`:1245`; `CALBAD`, `:1015`–`:1023`; the CAL1,8 table,
> `:600`–`:630`), `TRAPC.txt` (`MXCON`, `:98`–`:136`), `STPNR.txt` (`J:EXTENT`'s bits,
> `:330`–`:348`; the step exit `T:EXIT`…`SETRNST`, `:506`–`:552`; `XCONSEE`…`XCONENT`,
> `:583`–`:719`; the reset at a step's end, `:992`–`:998`), `SCHED.txt` (`T:UTSXTS`,
> `:1984`–`:2043`; `CHKPROT`, `:2048`–`:2066`), `TABLES.txt` (the trap masks, `:788`–`:801`),
> `BPM.txt` (the `M:TRAP` and `M:XCON` procedures, `:156`–`:201`), `JIT.txt` (`J:USENT`,
> `:437`–`:439`; `J:EXTENT`, `:487`).

## 1. The JIT words

| Word | Name | Holds |
|---|---|---|
| 38 | `J:USENT` (`USRENT` and `TRPFLAGS`, one word) | Bits 15–31: the trap entry address. Bits 7–14: the trap flags (`TRAPFLGB` = 17, the field `Y01FE`) |
| 72 | `J:EXTENT` | Bits 15–31: the exit-control address. Flags, bit by bit, below |

The trap flags, as a byte (bits 7–14 of `J:USENT`, bit 0 first): X'80' CAL (`BCALMSK`), X'40'
watchdog, X'20' NAO (trap X'40', `NAOMASK`), X'10' UI (X'41'), X'08' PS (push-down, X'42',
`PSMASK`), X'04' FP (X'44', `FLTMASK`), X'02' DEC (X'45', `DECMASK`), X'01' FX (fixed-point
overflow, X'43', `FXMASK`). Bits 2–7 are named in `MTRAP`'s comment (`ALTCP.txt:1177`) and the
masks in `TABLES.txt`; `BPM.txt`'s keys list them in the same order (`ATF`: `WDOG,NAO,UI,PS,FP,
DEC,FX,CAL`).

`J:EXTENT`'s byte 0 (`STPNR.txt:335`–`:348`), and bit 8:

| Bit | Mask | Meaning |
|---|---|---|
| 0 | X'80000000' | Abort or hang-up already signalled |
| 1 | X'40000000' | Limits exceeded already |
| 2 | X'20000000' | Exit control in progress |
| 3 | X'10000000' | Exit control set by a command processor |
| 4 | X'08000000' | An `M:LINK` / `M:LDTRC` exit |
| 6 | X'02000000' | Exit control established at a control-Y and quit |
| 7 | X'01000000' | The step CC was set |
| 8 | X'00800000' | `LAST`: no later `M:XCON` may replace it |

At the end of a job step both are cleared, except bits 0–1 of `J:EXTENT` (`XIT85`,
`STPNR.txt:992`–`:998`).

## 2. `M:TRAP`

The FPT (`BPM.txt:156`): word 0 is the code X'14' and the trap entry's address; word 1 is

| Bits | Field | Effect |
|---|---|---|
| 0 | RESTORE | Restore the conditions saved earlier (below) |
| 1–8 | ABORT | Trap flags to **reset**: these traps abort the program |
| 9–16 | TRAP | Trap flags to **set**: these traps go to the trap entry |
| 17–23 | PERMIT | Bits 22, 23 (DEC, FX): **set** the PSD's decimal and arithmetic masks |
| 24–31 | IGNORE | Bits 30, 31 (DEC, FX): **clear** them |

`MTRAP` (`ALTCP.txt:1180`), with R6 = word 0 and R7 = the FPT + 1:
1. The PSD saved in the temporary stack (`TSTACK`, 17 words down) goes to D3/D4.
2. The new entry address goes into `J:USENT`'s bits 15–31 (`STS,R6 USRENT,R5`).
3. **The old conditions go to the user's SR1 and SR2:** SR1 = `J:USENT`'s left half (the trap
   flags) beside the PSD's left half (CC, floating controls, masks); SR2 = the old `J:USENT`
   word, entry and flags (`:1185`–`:1194`). A program keeps the pair to restore later.
4. The ABORT field's flags are cleared and then the TRAP field's set. Each field's last bit
   (bit 8, bit 16) stands for the CAL flag X'80', the other seven for the flags of the same value
   (`MTRAP2`, `MTRAP4`). A foreground user's copy in `FPDTTF` is also written (`:1214`–`:1218`).
5. PERMIT's DEC/FX set the PSD's DM/AM, IGNORE's clear them (`MTRAP6`); the PSD goes back to the
   stack, so the program resumes with the new masks.
6. If `J:TCB` is 0, the user's R0 becomes the TCB, as in `M:INT` (`MTRAPX`).

**RESTORE** (`RSTRTRAP`, `:1236`): word 0 addresses a saved SR1/SR2 pair. The entry address
comes from the second word, the trap flags from the first word's bits 7–14, and DM/AM from the
first word's right half (its copy of the PSD).

**Where the flags are used.** A machine trap whose flag is set goes to the trap entry. So does a
bad CAL when the CAL flag is set: `CALBAD` tests X'80' << 17 in `J:USENT` and goes to `STKTOTMP`
instead of aborting (`ALTCP.txt:1018`–`:1023`). The delivery itself (`STKTOTMP`, `MSTRAP`, the
trap handler `40TRAP`) wasn't read.

## 3. `M:XCON`

The FPT (`BPM.txt:188`): one word, the code X'19', `LAST` in bit 8, the address in bits 15–31.
No address means 0, a reset. `MXCON` (`TRAPC.txt:106`):
1. The old address (`J:EXTENT`'s bits 15–31) goes to the user's SR1.
2. If exit control isn't in progress (bit 2) and the last one was given with `LAST` (bit 8), it
   is refused: CC1 is set (`CC1SET`).
3. Otherwise (`REPLACE`) bit 8 and the address are replaced from the FPT, and bit 3 is set if TEL
   is in control (`TIC` in `UH:FLG`: a command processor's own exit control), cleared if not.
   CC is cleared (`CC0RST`).

## 4. Exit control at the exit

Every way a program ends comes through `SETRNST` (`STPNR.txt:552`) with a run status in
`J:RNST`: 0 for `M:EXIT` (`T:EXIT`), X'80' for `M:ERR`, X'40' for `M:XXX`, 1 for the monitor's
abort (`T:ABORTM`, after `CALBAD`), X'08'/X'10' for an X key-in or a hang-up (`T:DOLIST`), X'04'
for limits exceeded. Then `XCONSEE` (`:583`):
- **No address** in `J:EXTENT`: the step ends as usual (`NOXCON`).
- **Exit control already in progress** (bit 2) and the run status is `M:EXIT`, `M:ERR` or `M:XXX`
  (`J:RNST` & X'3F' = 0): the step ends. So the exit routine ends the program with any of these.
- **Bit 3 must match `TIC`**: a command processor's exit control is taken only with the
  processor in control, a program's only without (`NOTINPRO`, `NOTCP`).
- **An X key-in or hang-up** (`J:RNST` & X'18'): the first time, bit 0 is set and exit control is
  taken (with more time and limits, `TIMELMT`); the second time, the user is kicked off.
- **Limits exceeded** (X'04'): `XCONCLS2` sets bit 1 and extends the limits, once.

**`XCONSETUP`** (`:669`) then prepares the program to go on at the exit-control address:
1. The temporary stack is cut down to one environment, and **`T:UTSXTS`** copies it to the
   user's own stack, the one whose stack pointer doubleword `J:TCB` addresses. The pointer, the
   stack's bottom and its top must be outside the monitor's pages (`CHKPROT`: at or above
   `JOVVPA`, page X'40', and storable by the access codes `J:JAC`), and `MSP` must find room. The
   push is 20 words if the stack's top is even and 21 if odd, so that the PSD lands on a
   doubleword: a 0 (or -1) word, the PSD, R0–R15, and on top whatever R0 held (`STM,8` with a
   count of 9 wraps to R0). After it, the user's R0 = `J:TCB` and R1 = the PSD's address in the
   stack.
2. If the stack is bad (`TCBMESS`), R2/R3 get the PSD instead, and R12 bit 0 is set.
3. The PSD is replaced by `SMPSD` (X'00C00000': slave, mapped, no masks, CC 0) with the exit
   address.
4. R8 = the run status, R9's bits 23–31 = the limit bits (`J:ASSIGN`), R10 = the abort code
   (`J:ABC`), R11 = its subcode (`ERO`'s low byte). The run status, abort code and subcode are
   cleared.
5. Bit 2 (in progress) is set. An `M:LINK` exit (bit 4) clears bit 4 and sets R12 bit 1.
6. `J:INTENT` and `J:TIMENT` are cleared (`XCONENT`), and the program goes on (`SSEMDEST`).

## 5. `M:STIMER` and `M:TTIMER`

`MSTIMER` (TRAPC.txt:173–:186) sets **J:UTIMER** (JIT word 37) to the FPT's count (word 1) times
its unit's multiplier (`MPLRS`: 500 a second, 30000 a minute, 1 a clock tick). The unit is in
word 0's bits 12–14. **J:TIMENT** gets the exit address with X'08000000'. `MTTIMER` (:188–:202)
returns the time left, in the unit of word 0's bits 30–31, in SR1. With X'100' (CANCEL) it
clears J:TIMENT. The model sets the words, but **the clock doesn't count the timer down** and
the exit is never taken (a departure). LOADER sets one when it starts.

## In the translation

`python/uts/cal.py`: `mtrap`, `mxcon`, `exit_control` and `_push_environment`, on the user's
JIT words (`jword`). The interpreter (`interp.py`) gives the monitor the PSD at each CAL (the
masks and the address after the CAL; `cal.upsd`) and takes back the masks after it, so `M:TRAP`'s
PERMIT turns on fixed-point overflow traps (`cpu.AM`). `T:EXIT`, `T:ERROR`, `T:ABORT` and the
monitor's abort after a bad CAL go through `exit_control`; when it is taken, the program goes on
at the address with CC 0 and no masks.

**TEL is no longer in control while a program runs.** TEL's step to a program resets `TIC`
(`STEP04C`, `DRTEL1`, `STPNR.txt:1777`–`:1781`), and starting a command processor sets it again
(`ISTEL`). Before this the translation left `TIC` set, so a user program was treated as TEL
(for `M:XCON`'s bit 3, CAL1,6's privilege check, `T:CLRERR`).

Not translated:
- **Delivering a trap** to the trap entry: a trap whose flag is set, or a bad CAL with the CAL
  flag, stops with NOT TRANSLATED instead of aborting the program.
- **The foreground copy** of the flags (`FPDTTF`): there are no foreground users.
- **Limits** (`J:RNST` X'04', `TIMELMT`, `XCONCLS2`) and the kick-off after an earlier abort or
  limit signal (`XCONKICK`, from `NOXCON`).
- **`CHKPROT`'s access codes**: only the page check is made.

## Open questions

- **The word on top of the pushed environment**: `T:UTSXTS` stores the monitor's R0 there. What
  `XCONSETUP`'s R0 holds at that point wasn't traced; the translation stores the user's R0.
- **The DEC flag and decimal instructions**: the interpreter has no decimal instructions, so DM
  is kept in the PSD only.
