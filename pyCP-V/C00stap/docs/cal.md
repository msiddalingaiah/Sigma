# CAL dispatch: how a program calls the monitor

A program asks the monitor for a service with a **`CAL1,n FPT`** instruction. `n` (the R field,
0–15) picks a family of services. `FPT` is the address of a *function parameter table*, whose first
byte is the function code. The CAL traps to the monitor. The monitor finds the FPT, picks the
routine from a table for that family, and runs it. That routine is either resident or in a monitor
*overlay*. The routine returns through the scheduler's exit path with condition codes in the
user's PSD. This document follows that path from the trap to the routine and back.

> Source paths are relative to `c00co/`.
> - `TCATCH.txt` holds the trap PSDs (`CAL1PSD` at `:133`).
> - `ENTRY.txt` (BPM `M:ENTRY`) is the trap entry and the common trap handler.
> - `CALPROC.txt` (BPM `M:CALPROC`) decodes the CAL. It dispatches CAL1,1 (I/O through a DCB) and
>   CAL1,2.
> - `ALTCP.txt` ("ALTERNATE CAL PROCESSOR", BPM `M:ALTCP`) dispatches CAL1,3 to CAL1,9 and holds the
>   common returns.
> - `T$OV.txt` loads monitor overlays (`T:OVERLAY`).
> - `UCAL.txt` is the MISOV overlay, with many of the routines.
> - `IORT.txt` holds the read/write path.
>
> The routines themselves (open, close, read, M:EXIT, ...) are only located here, not described.

## Overview

```
user: CAL1,n FPT ── trap X'48': XPSD to CAL1PSD (TCATCH.txt:133), n in the CC ──► CAL1P (ENTRY.txt:248)
   │
   ├─ CAL1,1 not under EXU: fast path CAL11N2 (stack, FPT by ANLZ, DCB) ──► CAL11N3 ─┐
   └─ any other: RTRAP → T:CTRAPM (save environment, overhead clock) → CAL1PP        │
            ──► CAL1P11 (CALPROC.txt:93): follow indirect/index/EXU to the FPT       │
                SR1 = code, R6 = word 0 (DCB/parameter), R7 = FPT+1, SR4 = TRAPEXIT  │
                n = 0 ─────────────► CALCK ─► BADCAL (X'AE')                         │
                n = 1 ─────────────► CAL11 ──────────────────────────────────────────┤
                n = 2 ─────────────► CAL12: KEYIN, MERC, PRINT, TYPE, MESSAGE, ENQ   │
                n = 3..9 ──────────► CALCK (ALTCP.txt:173): CAL13 ... CAL18, CAL1,9  │
                n = 10..15 ────────► CALCK ─► BADCAL                                 │
                                                                                     ▼
   CAL11M: check the DCB ──► READ/WRITE (IORT CAL11N7), CHECK, or the C11CDS / DEVCDS tables
                                                                                     │
   a table entry ─┬─ resident routine (B ...) ─────────────────────────────┐         │
                  └─ LI,0 index ─► T:OVERLAY segment (T$OV.txt) ─► routine │◄────────┘
                       (overlay not in core: E:AP, the scheduler swaps it in)
                                                                           ▼
   return: TRAPEXIT (PSD past the CAL), CC0RST/CC1SET... (CCs into the PSD), IOSPRTN (I/O),
           CALBAD (abort with code in R14, or the user's trap routine)  ──► exit path, SCHED.txt
```

## 1. The trap

A `CAL1` is trap X'48' (`CAL2`–`CAL4` are X'49'–X'4B'). `INITIAL` puts an `XPSD` to `CAL1PSD` at
X'48' ([`boot.md`](boot.md)). `CAL1PSD` (`TCATCH.txt:133`) enters `CAL1P` mapped, with interrupts
inhibited. The `XPSD` stores the user's PSD in `CAL1PSD`. That PSD still points at the CAL
instruction, because a trap doesn't advance the instruction address. The CAL's R field arrives as
the condition codes. That's the Sigma definition, which this code relies on: `CAL1P` tests the CC
to tell `CAL1,1` from the others.

**`CAL1P`** (`ENTRY.txt:248`):

- **`CAL1,1` not executed by an `EXU`** takes the **fast path** (`CAL11N2`, `:262`). It opens the
  stack by 19+8 words, stores all 16 registers there (`J:BASE` points at them), and finds the FPT
  address with an `ANLZ` of the CAL. A register address goes to the copy on the stack. Then it
  stores the PSD, enables interrupts, and bumps `J:CALCNT`. It takes the DCB address from FPT word
  0. If that word's bit 0 is set, the address is indirect, through memory or a register, and the
  function code is byte 0 minus X'80'. Then it enters `CALPROC` at `CAL11N3`.
- **Everything else**, including a `CAL1,1` under `EXU`, goes through the common trap receiver.
  `RTRAP` (`:72`) saves the trap CCs and the last-branch register (`RD X'31D'`), then does `XPSD`
  to `CTRAPSD` (`TCATCH.txt:160`). **`T:CTRAPM`** (`:175`):
  - finds the trap's PSD and saves it in `TRAPPSD`, for recovery;
  - checks that `TSTACK` has room for an environment (19 words), or else `SUA X'79'`;
  - saves the standard environment (`T:SAVE`);
  - points `S:CLOCK4` at `J:OVHTIM`, so the time counts as overhead
    ([`scheduler.md`](scheduler.md) §5);
  - keeps the last-branch value in `J:ALB`. On a slave CPU it parks the user (`T:SPARK`).
  - It goes on through `TRPTV`: CAL1 to `CAL1PP`, then `CAL1P11`. CAL2–CAL4 go to `CAL234`, which
    is `CALBAD` with code X'B2'. Arithmetic and other traps go to `40TRAP` (`ALTCP.txt:862`).

## 2. Decoding the CAL (`CAL1P11`, `CALPROC.txt:93`)

1. Bump `C:CAL` (the performance monitor's counter, if loaded) and `J:CALCNT`, and point `J:BASE`
   at the saved registers (`TSTACK`−15).
2. **Find the FPT** (`ANLZSB`, `:103`). Starting from the saved PSD's address, fetch the
   instruction. Follow indirect addressing, add an index register (from the saved copy), and if the
   instruction is an `EXU`, decode its target the same way, repeatedly. A register address (below
   X'10') means the register's copy on the stack (`CVREG`, `:367`).
3. **Read the FPT.** `SR1` (R8) = byte 0, the function code, and `R6` = word 0, normally a DCB
   address. If word 0's bit 0 is set, the DCB address is indirect too, and X'80' comes off the
   code. Then `R7` = FPT+1 (the presence bits for optional parameters) and `SR4` = `TRAPEXIT`, the
   default return.
4. **Dispatch on n**, from the CC byte (`SLS,R3 -4`): 0 goes to `CALCK`, 1 to `CAL11`, and 2 to
   `CAL12`. 3 and up decrement `J:CALCNT` again and go to `CALCK`.

`CALCK` (`ALTCP.txt:173`) masks `R6` to 24 bits and dispatches the rest. 0 goes to `BADCAL`.
1 and 2 go to `SUA X'7C'`, since they can't arrive there. 3–8 go to `CAL13`–`CAL18`, and 9 falls
into the CAL1,9 code. 10–15 go to `BADCAL`.

## 3. The service families

### CAL1,1: I/O through a DCB (`CAL11M`, `CALPROC.txt:156`)

**Checking the DCB.**
- `M:XX` is always accepted.
- `M:UC` (the terminal) is accepted for an on-line user or ghost, but not in batch.
- Any other address must be one of the user's DCBs. Those are found by walking the DCB name list at
  `J:DCBLINK` (1-, 2- or longer names), and `M:OC` is the last chance.
- An address that is none of these is `CALBAD` X'AF' ("ILLEGAL-DCB"), except code X'2C'
  (`M:PC`, set prompt), which goes to `T:STPMT` without a DCB.
- For a user's DCB, the CAL count goes into DCB word 9 (`AGER`), so the oldest blocking buffers
  are reused first. If the DCB is open on a file or labeled tape, its buffer pages are mapped into
  the `BUFF1`/`BUFF2` windows (`:191`–`:220`).

**Dispatch** (`CAL11N9`, `:221`, with the return set to `IOSPRTN`):

| Code | Service | Goes to |
|---|---|---|
| X'10', X'11' | READ, WRITE | `CAL11N7`, IORT's "fast CAL path" (`IORT.txt:209`) |
| X'2D', X'2E' | Read and write for the A–M devices | `CAL11N7` |
| X'29' | CHECK | `IOCHEK` (`IORT.txt:1094`) |
| X'14' | OPEN | overlay OPEN (`EPOPN`) |
| X'15' | CLOSE | overlay CLOSE, entry 2 (`EPCLS`) |
| X'D' | DELETE | overlay CLOSE, entry 4 (`EPDEL`) |
| X'3' | CVOL | overlay LTAPE, entry 2 (`EPCVOL`) |
| X'E' | MOVE | overlay LTAPE, entry 6 (`EPMOVE`) |
| X'1C', X'1D', X'1', X'2', X'F', X'2F' | PFIL, PRECORD, REW, WEOF, TFILE, job entry | MISOV routines (`PFIL#`, `PRECORD#`, `REW#`, `WEOF#`, `MSRTFILE#`, `T:JOBENT#`) |
| X'12' | TRUNC | resident `TRNC` |
| X'C' | | nothing: `TRAPEXIT` |
| `DEVCDS` (`:283`): X'24' COUNT, X'23' DATA, X'21' FORM, X'26' HEADER, X'20' LINES, X'22' MODE, X'4' PAGE, X'27' SEQ, X'25' SPACE, X'28' TAB, X'5' VFC, X'B' DIR, X'6' SETDCB, X'2A' NLINES, X'2B' CORRES | `M:DEVICE` | `IOSDEV` (`IOD.txt:99`) |

The table at `C11CDS` (`:266`) is searched from the end. Its entries 1 and 2 are X'29', which the
CHECK test catches first. `M:UC` is refused anything but read, write and the device calls
(`BADCAL`). An unknown code is `BADCAL` X'AE'.

When a table entry runs, `C11TV` (`:243`) checks where the CAL came from. A CAL from monitor code
(PSD address not above `J:JIT`) first `REMEMBER`s the current overlay, so it is restored afterwards.

### CAL1,2 (`CAL12`, `CALPROC.txt:307`)

| Code | Service | Goes to |
|---|---|---|
| 4 | KEYIN | MISOV `MSRKEY#` |
| X'10' | MERC | `MERC` (`IORT.txt:1557`), return through `IOSPRTN` |
| 1, 2 | PRINT, TYPE | `MSRTYPR` |
| 0 | M:MESSAGE | `MSROCTY` |
| 8, 9 | ENQ, DEQ | `ENQ`, or `BADCAL` if the system has no ENQ tables (`QT` = 0) |

### CAL1,3 to CAL1,8 (`ALTCP.txt:354`–`:640`)

| n | Family | Codes and where they go |
|---|---|---|
| 3 | Debugger | Code below 6 goes to overlay DEBUG with R0 = the code |
| 4 | Checkpoint, association (`CHKPT`) | 2, 3 `T:SAVEGET`; 4 associate, 5 disassociate a library or the debugger; 6 `T:CLRERR` (TEL only: clears the run status, abort code and break bit). All but 6 are in MISOV |
| 5 | Privileged | X'28' **M:EXU**: run one `SIO`, `TIO`, `TDV`, `HIO`, `RD` or `WD` for the user, with privilege X'C0' (abort X'B9' subcodes 1, 4, 5). **M:MASTER / M:SLAVE**: change the saved PSD's mode bits. Others go to the real-time `RTALTCP` if real-time, else `BADCAL` |
| 6 | Reliability | Needs privilege X'A0' or TEL in control. Read or write the error log, M:MAP, M:SIO/BLIST, M:LOCK, diagnostic open and close, `T:INITJOB` (start a ghost job), `T:SYS`, M:DMOD/DPART/DRET. Most are in overlay RMAOV |
| 7 | Transaction processing | M:GETLINE, M:RLSLINE, M:BUFSTAT, M:PURGE, M:MDFLST, M:ECBCHECK, M:QUEUE (unlock, define list, put, get, stats, purge, lock), M:GETID. In overlays TQOV1 and TQOV2 |
| 8 | Memory and miscellaneous | X'1' M:SEGLD, X'2' M:LINK, X'3' M:LDTRC, X'4'–X'D' page calls (M:GVP, M:FVP, M:CVM, M:GP, M:FP, M:SMPRT, M:GL, M:GCP, M:FCP; overlay STEPOVR, `MMOVRTV`), X'6' M:CT, X'E' M:INT, X'F' **M:WAIT**, X'10' M:TIME, X'11' M:STIMER, X'12' M:TTIMER, X'13' M:DISPLAY, X'14' M:TRAP, X'15'–X'18' release resources, X'19' M:XCON, X'1A' M:LDEV, X'1B' M:GDDL |

### CAL1,9: exits (`ALTCP.txt:178`–`:334`)

CAL1,9 has no FPT. The CAL's address field is the exit type, so `CAL1,9 1` is M:EXIT. Bit 15 of
the CAL (the presence bit) means step condition codes, or a real-time interrupt code, are given in
bits 16–23. `CAL1P11` treated the address as an FPT. Types 1–11 are register addresses, so `R7`
became `J:BASE`+type+1 = `TSTACK`−14+type. CAL1,9 undoes that (`SW,R7 TSTACK`, `AI,R7 15`, then an
`INT`) to get type+1, and indexes `C19TV` with it.

| Type | Exit | Goes to |
|---|---|---|
| 1 | M:EXIT | `T:EXIT` (`STEP.txt:59` → `STPNR.txt:506`) |
| 2 | M:ERR | `T:ERROR` |
| 3 | M:XXX | `T:ABORT` |
| 4 | M:STRAP | MISOV `MSTRAP#` |
| 5 | M:TRTN | `MTRTN`: return from a trap routine, `T:SSEM` |
| 6 | COOP super close | overlay MULOV (`CCLOSE#`) |
| 7, 8 | M:CLEAT, M:TERM | `BADCAL` |
| 9 | M:EXEC | `USERGO`: only from a shared processor. New quantum (`T:ACCTEX`), the run status says "user", and SR1 becomes the new TCB address |
| X'A' | M:INTRTN | Real-time only (`RTINTRTN`), and only with the presence bit |
| X'B' | M:STRUNC | `M:TRUNC` every DCB and `M:XX`, then free the spare buffers |

With the presence bit, the step CC goes into `JB:STEPCC` (and `J:EXTENT`) for M:EXIT, M:ERR and M:XXX.

GHOST1 ends with `CAL1,9 1` (M:EXIT) and the name FILL in its registers, so the step code runs FILL
next ([`keyin.md`](keyin.md) §4).

## 4. Overlays (`T:OVERLAY`, `T$OV.txt:105`)

Most services aren't resident. A table entry like `LI0 T:WAIT#` puts the routine's index within an
overlay in R0. Then the code branches to `T:OVERLAY` with R2 = the segment number. MISOV is the
default (`MONOVLY`, `ALTCP.txt:251`; `MISOVLY`, `CALPROC.txt:327`).

| Segment | Name (`SEGNAME`, `T$OV.txt:475`) | Holds |
|---|---|---|
| 0 | OPEN | open |
| 1 | CLOSE | close, delete |
| 2 | LTAPE | CVOL, MOVE |
| 3 | DEBUG | CAL1,3 |
| 4 | MULOV | M:LDEV, COOP close |
| 5 | LDLNK | load and link |
| 6 | MISOV | UCAL: wait, time, timers, M:INT, SAVEGET, associate, file positioning, KEYIN, ... (`DRIVE`, `UCAL.txt:151`) |
| 7 | OPENTP | the I/O-device and TP opens |
| 8 | STEPOVR | the page calls |
| 9 | ENQOV | ENQ/DEQ |
| 10 | RTOV | real-time |
| 11 | RMAOV | CAL1,6 |
| 12, 13 | TQOV1, TQOV2 | the TP queue manager |

**`T:OVERLAY`:**

1. Looks the segment's name up in `P:NAME` (`SUA X'1D'` if it isn't there) and takes its start
   address `P:SA`.
2. If it's already the user's overlay (`UB:OV`), it just jumps in.
3. Otherwise it drops the old overlay's use count and takes the new one's (`PB:UC`, and `PB:REP`
   for monitor overlays), keeping `PB:LCT`/`S:RTCORE` right for a user locked in core. Then it sets
   `UB:OV`.
4. **In core** (`PX:HPP`): it maps the overlay's pages into the user's map (`SPMAP`, `LDMAP`) and
   jumps to the start address.
5. **Not in core** (`NOTINCORE`, `:239`): it clears the user's `RTR` and reports **`E:AP`** through
   `T:REG`. The scheduler moves the user to special compute at the head of the queue (`STASP`).
   Since the user isn't `RTR`, `T:SS` picks them for swap-in, and counts the overlay among the
   processors to bring in (`PRCAV` on `UB:OV`). When the user runs again, `T:REG` returns and the
   overlay starts. See [`scheduler.md`](scheduler.md) §§7, 10.
6. The overlay's own transfer vector dispatches on R0. MISOV's is `AI,0 DRIVE` / `B *0`.

`T:REMEMBER` saves the current overlay number on the stack before switching, and switches back
when the routine returns. Monitor code uses it to call overlaid services, and so does `C11TV` for a
CAL from the monitor.

## 5. Returns

| Exit | Where | Does |
|---|---|---|
| `TRAPEXIT` | `SCHED.txt:883` | Steps the saved PSD past the CAL, then the exit path (DO list, quantum, preemption) |
| `CC0RST`, `CC1RST`, `OKOUT` | `ALTCP.txt:728` | CC1–CC3 clear, then `OUT` |
| `CC1SET`, `CC2SET`, `CC3SET` | `:732`–`:737` | Set CC1, CC2 or CC3, then `OUT` |
| `OUT` | `:741` | Store R12's CC1–CC3 into the saved PSD (mask `YE`; CC4 is kept), then `TRAPEXIT` |
| `IOSPRTN` | `CALPROC.txt:389` | After I/O. With `SR1` = 0, or the run status set (`EXITBITS`), it is `TRAPEXIT`. Otherwise SR1 is the user's error or abnormal routine: the user's R8 gets the return address (PSD+1), R10 gets SR3, and the PSD goes to the routine (`T:ACCTOV`, no step past the CAL) |
| `BADCAL`, `CALBAD` | `ALTCP.txt:1015` | `BADCAL` sets abort code X'AE'. `CALBAD` aborts with the code in R14 (`T:ABORTM`), unless the user has trap control (`J:USENT`), in which case the user's trap routine gets it (`STKTOTMP`) |

The abort codes the dispatch itself uses:
- X'AE': bad CAL or code.
- X'AF': illegal DCB.
- X'B2': CAL2–CAL4.
- X'B8': restricted service after M:HOLD.
- X'B9': M:EXU (subcode 1 privilege, 4 protection, 5 opcode).

`SUA X'79'` means no stack room for the environment, and `SUA X'7C'` a CAL1,1 or 1,2 reaching `CALCK`.

**An example, M:WAIT** (`CAL1,8` with code X'F'): `CAL18` runs `LI0 T:WAIT#` (7), then `MONOVLY`,
then `T:OVERLAY` MISOV, whose `DRIVE` goes to `T:WAIT` (`UCAL.txt:425`). That stores the wake-up
limit ((FPT word 0 + 1) & X'1FFFF') in `U:MISC`, reports **`E:SL`** with `T:REG`, and sets the return to
`CC1RST`. The user sleeps (`SW`). When CLOCK4 reports `E:WU`, the user is scheduled again, `T:REG`
returns to `CC1RST`, and the CAL ends with CC1–CC3 clear.

## What a first translation needs

| Piece | Source | Notes |
|---|---|---|
| Trap entry and decode | `CAL1P`, `T:CTRAPM`, `CAL1P11` | A CAL as (n, FPT) from a stand-in, with the FPT as a Python object; the EXU/indirect/index walk on a small memory |
| Family dispatch | `C1TV` in CALPROC and ALTCP | Tables as data, so a bad code reaches `BADCAL` as in the source |
| CAL1,1 DCB check | `CAL11M`–`CAL11X2` | DCBs and the `J:DCBLINK` list as Python objects |
| Overlays | `T:OVERLAY`, `PB:UC`/`UB:OV` | Through the scheduler: `E:AP` when the overlay isn't in core |
| Returns | `TRAPEXIT`, `OUT`, `CALBAD` | `CALBAD` to the scheduler's hooks |
| First services | M:WAIT, M:TIME, M:EXIT | `T:WAIT` is short and exercises `E:SL`; M:EXIT ends the step (stand-in for `T:EXIT`) |

The Python translation is `python/uts/cal.py`. A stand-in yields `Cal1(n, Fpt(...))`, and the CAL
runs as a generator on the user's stack, so it can wait for an overlay. M:WAIT, M:TIME, M:PC,
`T:CLRERR` and the CAL1,9 exits are translated. Every other routine raises `NotTranslated` with its
name and overlay.

## Open questions

- **Architecture this relies on:**
  - the CAL's R field arriving as the trap PSD's CC;
  - `XPSD` storing the old PSD, unadvanced, in the trap PSD;
  - `ANLZ` giving the effective address on the fast path;
  - `INT` in the CAL1,9 decode, as in [`recovery.md`](recovery.md) §6;
  - `CLM` for the DCB-name length tests.
- **`J:CALCNT` is decremented again for CAL1,3 and up** (`CALPROC.txt:132`), so those CALs don't
  count. Why isn't known.
- **The fast path versus `CAL1P11`.** A `CAL1,1` under `EXU` goes the long way, through `CAL11`,
  which opens the stack by 8 words itself (`:148`). Both paths end at `CAL11M`, but the fast path
  takes the function code from `LB,8 6` (`CAL11N3`), not from `SR1`.
- **Code X'C' in CAL1,1** just returns. What it was isn't recorded.
- **Not read:** the services themselves:
  - IORT's read/write (`MSRRDWT`) and `IOCHEK`, which queue through IOQ ([`io.md`](io.md));
  - OPEN, CLOSE, `T:EXIT` (STPNR) and the rest of UCAL;
  - `40TRAP` and the user trap routines (`STKTOTMP`, M:TRAP, M:TRTN);
  - the real-time and TP CALs;
  - `T:OVB`/`T:OVBAL`, the overlay-to-overlay branches (`T$OV.txt:276`).
