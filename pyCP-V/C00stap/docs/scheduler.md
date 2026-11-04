# The scheduler: user states, events, execution and swap scheduling

How the monitor decides which user runs and which users are in core. Every user is in exactly one
*state*, and each state has a queue. Something in the system reports an *event* for a user, a
table lookup turns the state and event into a transition, and the user moves to another queue.
`T:SE` then picks the most urgent user who is in core, and `T:SS` picks who to swap in or out.
The exit path that every interrupt, trap and CAL passes through on its way back to a user is also
here, because that is where quanta end, users get preempted, and pending breaks, aborts and
DO-list items are acted on.

> Source paths are relative to `c00co/`. `SCHED.txt` (2,800 lines, "SCHED - EXECUTION AND SWAP
> SCHEDULER") is the scheduler. Its data, including the queue heads and the priority increments, is
> in `SSDAT.txt`. The swaps themselves are done by `SWAPPER.txt` (`SWAPOUT` at `:260`, `SWAPIN` at
> `:587`). The swap I/O package ends at `T:SEXIT` (`TSIO.txt:265` or `DPSIO.txt:334`). The
> multiprocessor hooks `T:MASTER`, `T:SMPFLG` and `T:SES` are in `SCHDSUB.txt`. With `MP` = 0,
> `T:SES` just returns (`SCHDSUB.txt:145`).

## Overview

```
 COC, IOQ, KEYIN, MM, ...          T:RE / T:RUE / T:RCE / T:REG (event for a user)
            │                                   │
            └──────────────► RCE0: S:SET[event] word has the bit for UB:US? ──no──► SCREECH 02
                                                │ yes
                                    SB:SET[same index] = action
                                ┌───────────────┴───────────────┐
                     a state number (≤ 31)           X'20' + offset into S:TRNSVEC
                     RCE4: FIFO move to that          special transition: STSC, STIOC,
                     state's queue                    STKO, T:RES, STBEEA, ...
                                                      (T:CHSE: priority → SRT/SC0–SC10,
                                                       queued by priority)

 interrupt / trap / CAL exit ─► T:SSE (T:SS first) or TRAPEXIT/T:SSEM ─► SSE0/SSE1:
        DO list and ABRT/ERR/YC/BRK flags ─► quantum used? swap quantum satisfied?
        ├── quantum not over, nobody more urgent in core ──► T:PULLE (back to the user)
        ├── more urgent user in core (S:HIR > 0) after SL:QMIN ──► park, T:SEO
        └── quantum over ──► T:ACCTEX, back to base priority, tail of queue ──► T:SE

 T:SE: T:SS (swap schedule), SACT (symbionts), then the first ready (RTR) user in
       SRT, SC0, ..., SC10 ──► SE1: load map and access, state SCU ──► T:PULLE
       nobody ready ──► idle check (GOODNGT, SCREECH X'404'), WAIT, back to T:SE
```

## 1. States

The `STATE` procedure numbers the states from 1 (`SCHED.txt:257`–`:263`). State 0 isn't used, so a
queue head byte at index 0 is always 0. The order of the executable states is "critical", and some
states must be adjacent pairs (`SCHED.txt:268`–`:272`):

| No. | State | Meaning | Mask |
|---|---|---|---|
| 1 | `SRT` | Real-time execute (priority below X'C0') | EXU |
| 2 | `SC0` | Background with priority from X'C0' to X'F5' | EXU |
| 3–12 | `SC1`–`SC10` | Priority X'F6' through X'FF', one state each | EXU |
| | `SEXU` = 12 | The last executable state (`SCHED.txt:289`) | |
| 13 | `SCU` | The current user | EXU |
| 14, 15 | `STOB`, `STOBO` | Terminal output blocked (in core, out of core) | IOWAIT |
| 16 | `SIOW` | I/O wait | IOWAIT |
| 17 | `SIOMF` | "Master function count too high": too much I/O outstanding | BLCKD |
| 18 | `SW` | Wait (asleep) | WAIT |
| 19 | `SQA` | Queued for access | BLCKD |
| 20, 21 | `SQR`, `SQRO` | Queued for a resource (in core, out of core) | BLCKD |
| 22, 23 | `STI`, `STIO` | Terminal inputting (in core, out of core) | IOWAIT |
| 24 | `SQFI` | Queued for interrupt | WAIT |
| 30 | `SNULL` | Empty user slot | |

`SNSTS` = 31 is the number of states (`SCHED.txt:317`–`:318`). The masks `EXU:MASK`, `WAIT:MASK`,
`IOWAIT:MASK` and `BLCKD:MASK` have the bit 2<sup>n</sup> set for each state *n* in the group
(`SCHED.txt:340`–`:344`). `SCU` is in `EXU:MASK` although it isn't below `SEXU`.

Why the layout matters:

- **`SIOW` = 16 is divisible by 4**, so `LH SB:HQ+(SIOW/4)` fetches the heads of `SIOW` and `SIOMF`
  together (`SCHED.txt:1088`). The idle loop uses this to see whether anyone is waiting for I/O.
- **`E:IIP` and `E:QMF` are events 0 and 1**, so `STIIP` forms the new state as
  `SIOW + (event − E:IIP)` (`SCHED.txt:1558`).
- **The in-core/out-of-core pairs** (`STOB`/`STOBO`, `SQR`/`SQRO`, `STI`/`STIO`) let the kick-out
  transition `STKOT` add 1 to get the out-of-core state (`SCHED.txt:1692`–`:1696`).

## 2. The tables

**Per user** (indexed by user number; user 0 is the null link):

| Table | Contents |
|---|---|
| `UB:US` | Current state |
| `UB:FL`, `UB:BL` | Forward and back links in the state queue |
| `UB:PRIO`, `UB:PRIOB` | Current and base execution priority (a lower value is more urgent). In `SQR`, `UB:PRIO` is the back link of the resource sub-queue instead |
| `UH:FLG`, `UH:FLG2` | Flags, see below |
| `UH:DL` | DO-list head (12-bit doubleword address) and, in bits 0–3, the ABRT, ERR, EC (control-Y) and BRK flags |
| `U:MISC` | Depends on the state: the quantum mark while running (`SE4F`), or the resource index and forward link in `SQR` |
| `UB:MF` | "Master function count": I/O requests the user has going |
| `UB:PCT` | Pages the user needs |
| `UB:ACP`, `UB:APR`, `UB:APO`, `UB:ASP`, `UB:DB`, `UB:OV` | Associated command processor, processor root and overlay, special shared processor, debugger, monitor overlay |
| `UX:JIT`, `UH:AJIT`, `UB:SWAPI` | Physical JIT page, JIT disc address, swap device |

`SSDAT.txt:314`–`:381` defines these tables only when `SYSGEN` = 0. `SSDAT.txt` sets `SYSGEN` to 1
(`:12`), so in this build they come from SYSGEN.

**`UH:FLG`**, as the diagram at `SCHED.txt:682`–`:702` shows it. The names are those in `UTS.txt:192`–`:205`:

| Bit | Value | Name | Meaning |
|---|---|---|---|
| 15 | X'1' | `RTR` | Ready to run: in core |
| 14 | X'2' | `INHIBIT` | Interrupt entry (real-time) inhibited |
| 13 | X'4' | `SPECFILE` | `:ACCTLG` or `:USERS` open |
| 12 | X'8' | `OPNCLSUSR` | The open/close user |
| 11 | X'10' | `PPSWP` | Pure procedure must be swapped |
| 10 | X'20' | | Interactive user |
| 9 | X'40' | `DIC` | Delta in control |
| 8 | X'80' | `TIC` | TEL (the command processor) in control |
| 7 | X'100' | `BAT` | Batch job |
| 6 | X'200' | `JIC` | JIT in core |
| 5 | X'400' | `DELA` | Delta associated |
| 4 | X'800' | `INIT` | Initialization must be done |
| 3 | X'1000' | `SJAC` | Special JIT access |
| 2 | X'2000' | `DCBS` | Initial DCBs being swapped in |
| 1 | X'4000' | | Step in progress, or "unblock received before block" |
| 0 | X'8000' | `BYPASS` | Available core temporarily too small for the user |

`UTS.txt` still names X'2' to X'20' `BRK`, `EC`, `ABRT` and `ERR`, and so does the older diagram in
`SSDAT.txt:353`. The scheduler keeps those four flags in `UH:DL` instead (`SCHED.txt:743`–`:753`).

**`UH:FLG2`** is mostly about swapping (`SCHED.txt:711`–`:731`). The bits SCHED uses:
X'1', X'2' and X'4' are the JIT, context and user swap errors. X'8' (`SQUAN`) means the swap
quantum isn't yet satisfied, and X'10' (`SWAPD`) means just swapped in. X'20' (`HANGUP`) is a COC
line hang-up, X'200' (`CALINT`) means interrupted during a CAL, X'800' (`RTHOLD`) is a real-time
lock in core, and X'2000' (`RMAHOLD`) is an RMA lock in core. The swapper sets `SWAPD` and `SQUAN`
together (X'18') when a swap-in finishes (`SWAPPER.txt:1428`–`:1430`).

**Queues.** `SB:HQ` and `SB:TQ` hold one head byte and one tail byte per state, 32 bytes each
(`SSDAT.txt:390`–`:394`). At assembly, the `SNULL` queue (byte 30) runs from user `MING` to user
`SMUIS`. Users below `MING` are the system ghosts (`KEYN.txt:623`, "DONT ZAP KEYN,ALLOCAT,RBBAT").
`MING` and `SMUIS` come from SYSGEN.

**Scheduler cells** (`SSDAT.txt`):

| Cell | Line | Contents |
|---|---|---|
| `S:CUN` | `TCATCH.txt:173` | Current user number |
| `S:CUP` | `:285` | Current user's priority (X'FF' when idle) |
| `S:HIR` | `:45` | Count of in-core users more urgent than the current user |
| `S:EVF` | `:403` | Event counter, bumped on every report and state change |
| `S:SEVF`, `S:FSEVF`, `S:ISUNF` | `:159`, `:160`, `:158` | Swap-set change counter; its value and the in-swap user at the last failed swap schedule |
| `S:CUIS` | `:51` | Users in the system |
| `S:SIP` | `:56` | Swap in progress |
| `S:ISUN` | `:157` | User being swapped in |
| `SB:OSUL`, `SB:OSN` | `:171`, `:170` | Users to swap out (at most `SMAXOUT` = 20, `:92`), and their count in byte 0 |
| `S:PRIODEC` | `:284` | 1: how far `UB:PRIO` decays toward base each time the user is scheduled |
| `S:RTIR` | `:286` | Minimum run time before preemption: `SL:QMIN`, or 0 when a real-time user is waiting (`RTROOT.txt:1221`) |
| `SL:SQNT`, `SL:SQPB` | `:294`, `:293` | 150 (comment: "300 MS"), and 2 |
| `SH:PINC` | `:421`–`:424` | Priority increments 0, 3, 2, 6 (compute, special compute, I/O complete, interactive) |

`SL:QMIN`, `SL:SQUAN`, `SL:OPRIO`, `SL:OIMF`, `SL:BIMF` and `S:OUAIS` aren't set in the source. They
are SYSGEN values that the operator can change through CONMAIN, for example `OPRIO` 192–255,
`QMIN` and `SQUAN` 0–5000, and `OUM` (`S:OUAIS`, the on-line users allowed) (`CONMAIN.txt:1031`–`:1087`).

## 3. Events and the transition tables

`ESTS` and `ESTS1` each build one word in `S:SET` and one byte in `SB:SET`
(`SCHED.txt:398`–`:431`). An event's number is the index of its first word. The `S:SET` word holds
the bit 2<sup>n</sup> for each state *n* the entry applies to, and its bit 0 (X'80000000') means
"continued in the next word" (`ESTS1`). `ALL` sets every state bit. The `SB:SET` byte holds either
a state number, or X'20' plus the word offset of a special routine from `S:TRNSVEC`.

**Lookup** (`RCE0`, `SCHED.txt:1371`–`:1404`): disabled, bump `S:EVF`, take the bit for the user's
state (`X1` indexed by the state: the table at `TABLES.txt:174` has 2<sup>k</sup> at `BT31TO0`+k+1).
Then walk from `S:SET[event]` until a word has that bit. If a word without the continuation bit
doesn't match, the result is **`SCREECH X'02'`**, "USER'S STATE AND EVENT ARE INCONSISTENT"
(`SCHED.txt:1380`). An action of `SNSTS` or less is a plain state change (`RCE4`). A larger one
branches to `S:TRNSVEC − X'20' + action`.

The events, numbered as the procedures lay them out, with the reporter the source comment names:

| No. | Event | From state → action | Reported by |
|---|---|---|---|
| 0 | `E:IIP` | `SCU` → `STIIP` (I/O in progress) | `T:IOREG` (IOQ, IORT) |
| 1 | `E:QMF`, `E:IP` | `SCU` → `STIOMF` | |
| 2 | `E:CRD` | `SCU` → `STCRD` (terminal read) | COC |
| 3–4 | `E:CIC` | `STI`, `STIO` → `STIRC`; `SCU` → `STIRCU` (terminal input complete) | COC |
| 5 | `E:CBL` | `SCU` → `STOB` (terminal output blocked) | COC |
| 6–7 | `E:CUB` | `STOB`, `STOBO` → `STOC`; most others → no-op (output continue) | COC |
| 8–9 | `E:CBK` | break: `STBEEA`/`STBEEAC` | COC |
| 10–11 | `E:CEC` | control-Y: `STBEEA`/`STBEEAC` | COC |
| 12–13 | `E:ERR` | error: `STBEEAC`/`STBEEA` | KEYIN |
| 14–15 | `E:OFF`, `E:ABRT` | abort or off: `STBEEAC`/`STBEEA` | COC, KEYIN |
| 16–17 | `E:WU` | `SW`, `SQFI` → `STSC`; anything else → no-op (wake up) | CLOCK4 |
| 18 | `E:SL` | `SCU` → `SW` (sleep) | UCAL, RBBAT, TYPR |
| 19 | `E:QA` | `SCU` → `STQA` (queue for access) | COOP |
| 20–21 | `E:ART` | `SQFI`, `SW`, executable → `STSCOM`; waiting states → no-op | RTROOT |
| 22–23 | `E:UQA` | `SQA`, `SIOW`, `SCU`, executable → `STUQA`; else no-op | RBBAT |
| 24–25 | `E:KO` | `SW`, `SQFI`, executable, `SQA`, `SIOMF`, `SIOW` → `STKO`; `STOB`, `STI`, `SQR` → `STKOT` (kick out) | the swap scheduler (`PROUT4`) |
| 26 | `E:AP`, `E:NC` | `SCU` → `STASP` (associate shared processor) | MM; STEP, SCHED, UCAL |
| 27 | `E:QE` | `SCU` → `STSCOM` | LBLT (MOVE CAL) |
| 28 | `E:IC` | any state → `STIOC` (I/O complete) | IOQ `REQCOM` (`IOQ.txt:1831`), FIX1, COOP |
| 29 | `E:QFI` | `SCU` → `SQFI` | |
| 30–43 | resources | see §6 | |

For a pair such as 8–9, the first word lists the states for the first action and the second word
the rest. The checks at `SCHED.txt:569` and `:600` make `E:CBK` even, and put `E:CEC`, `E:ERR` and
`E:OFF` at +2, +4 and +6 from it, because `STBEEA` picks its flag by event number (§5).

The report entries (`SCHED.txt:1342`–`:1371`, `:1859`):

| Entry | Registers | Does |
|---|---|---|
| `T:REG` | R6 event, R11 link; all saved | Saves the environment in the JIT, sets the master-only flag, reports for `S:CUN` with return set to `T:SE`. The caller resumes when it is next scheduled, or at once where the transition goes to `T:PULLE` (for example `STIIP` with no I/O left). Must be called mapped |
| `T:IOREG` | R6 DCB | Entered by `XPSD REGIPSD`; reports `E:IIP` with the DCB address in R1 |
| `T:RE` | R6 event, R11 link | Report for the current user and return |
| `T:RUE` | R5 user, R6 event, R11 link | Report for any user and return |
| `T:RCE` | R7 COC line, R6 event | Report for the line's user; on a line with no user, a break means log-on (§8) |
| `T:CHS` | R2 new, R3 old state, R4 user | Plain state change from outside |

## 4. State changes and priority

**A plain change** (`RCE4`, `SCHED.txt:1408`–`:1433`) unlinks the user from the old queue (R3) and
appends them to the tail of the new one (R2). It queues to the head instead when R4 is negative.
`CHS1` stores `UB:US`, bumps `S:EVF`, enables and returns through R11 (`SCHED.txt:1606`–`:1611`).

**An executable change** (`T:CHSE`, `SCHED.txt:1452`–`:1535`) recomputes the priority and picks the
state from it:

1. The new priority is the base `UB:PRIOB`, less 4 (`OPNBOOST`) for the open/close user or one with
   `:ACCTLG`/`:USERS` open, less `SH:PINC[i]`. The index *i* comes from which entry was used:
   `STSCOM` 0, `STSC` 1 (+3), `STIOCC` 2 (+2), `STIRC` 3 (+6, and `INTERACTIVE` also sets X'20').
   It is the return address of the `BAL,1` in `S:TRNSVEC` minus `STSC` (`SCHED.txt:1541`–`:1549`).
   `T:CHSE0` uses index 0 and so gives no increment.
2. `CHSE0` stores it in `UB:PRIO`. If the user is in core (`RTR`) and more urgent than `S:CUP`,
   `S:HIR` is incremented (and forced to at least 1).
3. `CHSE1` maps the priority to a state. X'F6'–X'FF' map to `SC1`–`SC10`, X'C0'–X'F5' to `SC0`, and
   below X'C0' to `SRT`. A real-time user's `UB:PRIO` is reset to the base: "DONT FLOAT RT".
4. In `SRT` and `SC0` the user is unlinked and inserted **by priority**. Normally the scan runs
   back from the tail to the first user whose priority value is not greater, so the new user goes
   behind equal priorities. When queued to the head (R4 bit 0, used by `STASP`), the scan runs
   forward to the first user whose value is *greater* (`CHSEH1`, `BL`). In a sorted queue that
   also lands behind equals, so queuing to the head changes nothing there. `SC1`–`SC10` hold one
   priority each and go through the plain change (`CHSE6` → `RCE4`). There, queuing to the head
   really puts the user first.

**Priority over time:**

- At log-on, `UB:PRIOB` is `SL:OPRIO`. A batch or ghost user's base comes from the caller of `ADD1` in R15.
- Events lower `UB:PRIO` below the base by the increments above.
- Each time `SE1` schedules a user whose `UB:PRIO` is below the base, it adds `S:PRIODEC` (1)
  (`SCHED.txt:1156`–`:1160`). A boost decays one notch per dispatch.
- At quantum end the priority goes back to the base, and the user goes to the tail of their queue
  (§5).

## 5. The exit path

Every way back to a user goes through here (`SCHED.txt:848`–`:1018`):

| Entry | From | Does |
|---|---|---|
| `T:SSE`, `T:SSEC` | Interrupts (`T:SSEC` is clock 3) | `T:SS` first, then `SSE0` |
| `TRAPEXIT` | CALs and traps | Steps the saved PSD past the CAL, then `SSE0` |
| `T:SSEM`, `T:ACCTOV`, `SSE0` | PSD already correct | `T:MASTER`, then `SSE1` |
| `SSE1` | `CLK4` and `SE1` | Go mapped if unmapped, then the checks |

`T:MASTER` (`SCHDSUB.txt:86`) goes straight to `T:PULLE` when the interrupted PSD is master mode
and unmapped, or mapped below `J:JIT` (inside the monitor). Otherwise it points `S:CLOCK4` at
`J:DELTAT`, so the user's execution time is counted, and returns.

**The checks at `SSE11`:**

1. If `J:RNST` (run status) and `UH:DL` are both zero, go to the quantum checks (step 4).
2. Otherwise save the run status in `JB:FRS` for ACCTSUM, take the four flags out of `UH:DL`, and act
   (`T:DOLIST`, `SCHED.txt:905`–`:956`):
   - **ABRT** goes to `T:OFF`. The run status is X'10', or X'08' for a line hang-up. Then the user
     goes to `T:TELDELCCI`, unless it is a "pre CCI abort" (the `TIC`+`BAT` check), which is
     ignored for now.
   - **ERR** goes to `SEERR`: error code X'B4', run status X'20', `SETRNST`.
   - A non-zero run status with TEL not in control goes to `T:TELDELCCI`.
   - **EC** (control-Y) goes to `SE9`. It is ignored when TEL is in control or the user is locked
     in core. Otherwise TEL is told (`J:TELFLGS`) and the user goes to `T:ECCP`.
   - **BRK** goes to `SE7`. With TEL in control it goes to TEL's break entry if TEL has one
     (`J:INTENT`). With Delta associated it goes to Delta at `SPPBASE`+X'D' (`DELTAGO`). Otherwise
     it goes to the user's `M:INT` routine through `ALTENT`, which copies the environment onto the
     user's TCB stack (`T:UTSXTS`). A bad user stack aborts with X'A3'.
3. **DO-list entries** (4-word blocks). The first doubleword holds a priority in byte 0 and a type
   in byte 1. An entry whose priority value is above `UB:PRIOB` waits. An interrupt entry (type 2)
   also waits while `INHIBIT`, `TIC` or `DIC` is set. Otherwise the entry is unlinked and run by
   type (`DOLV`):
   1 stores an ECB, 2 is a real-time interrupt entry, 3–6 are COC slave-line break, read complete,
   break later and write complete, and 7 is a routine whose address is in R7. Each returns to
   `T:DOLISTR`, which frees the block unless X'00800000' is set in its first word, and then takes
   the next entry.
4. **Quantum accounting** (`SCHED.txt:980`–`:1012`). `T:ACCTEX` sets `J:DELTAT` = `J:IDELTAT` =
   −quantum (`SL:QUAN`, or the batch partition's `PLH:QN`), and clears `J:CTIME` and `J:OVHTIM`
   (`ACCT.txt:27`–`:43`). So *used* = `J:DELTAT`+`J:OVHTIM`+`J:CTIME`−`J:IDELTAT` is the time used
   this quantum, and the quantum is over when `J:DELTAT`+`J:OVHTIM`+`J:CTIME` ≥ 0.
   - When *used* ≥ `SL:SQUAN`, the swap quantum is satisfied. `SQUAN` is cleared in `UH:FLG2` and
     `S:SEVF` is bumped. From then on the user can be chosen for swap-out.
   - When `SL:SQNT` ≤ *used* < `SL:SQUAN`, a flag is set in R4 (X'40000000') for step 6.
5. **Quantum over**: `T:ACCTEX` gives a new quantum, `UB:PRIO` returns to `UB:PRIOB`, `S:SEVF` is
   bumped, and `T:CHSE0` moves the user to the tail of their compute queue. Then the code falls into
   `T:SE`.
6. **Quantum not over** (`SSE41`, `SCHED.txt:794`–`:846`). If the user has run less than
   `S:RTIR` since being scheduled (measured from `U:MISC`, set at `SE4F`), or `S:HIR` ≤ 0, the user
   continues (`T:PULLE`). Otherwise `S:RTIR` is reset to `SL:QMIN`, the environment is moved into
   the JIT if it was on the unmapped stack (`SSE12`), and the user is **preempted**. `CHSE0`
   requeues them at their current priority, plus `SL:SQPB` (2) if the R4 flag is set. Then the code
   goes to `T:SEO`, an execution schedule without a swap schedule.

**`CLK4`** (`SCHED.txt:2091`–`:2101`), the clock 4 interrupt. If the interrupted PSD was in slave
mode (X'00800000' in word 0), it saves the environment (`T:PUSHE`) and enters `SSE1`. Otherwise it
returns. `S:CLOCK4` points at the cell the clock counts: `J:DELTAT` for user time, `J:OVHTIM` for
overhead (`SE4F`), or an idle counter.

**`T:PULLE`** (`SCHED.txt:2069`–`:2084`) pops the top environment off `TSTACK` and does `LPSD`. If
the stack is now empty in a user JIT, it resets the stack size. `GRANT` is the same address.

## 6. Resources

`RESOURCE` defines a block event and a release event for each resource (`SCHED.txt:454`–`:466`).
The block is reported from `SCU`, and the release from any state, both to `T:RES`. `SB:RBLK` holds
the special block routine (none are defined, since `T:BLKV` is empty) and `SH:RFLG` the release
routine and flags. The resource index is (event − `E:REL`)/2. An odd difference means release
(`SCHED.txt:1755`–`:1758`).

| Events | Name | Release routine | Flags |
|---|---|---|---|
| 30, 31 `E:NSYMF`, `E:SYMF` | `R:SYMF` | | FLUSH |
| 32, 33 `E:NSYMD`, `E:SYMD` | `R:SYMD` | | FLUSH |
| 34, 35 `E:OCR`, `E:NOCR` | `R:OCR` | `OPNUNBLOCK` | |
| 36, 37 `E:CFB`, `E:CBA` | `R:CBA` | | FLUSH |
| 38, 39 `E:ND`, `E:DPA` | | | FLUSH |
| 40, 41 `E:QFAC`, `E:UQFAC` | | `UQFAC` (ALLOCAT) | FLUSH, NULL |
| 42, 43 `E:NQW`, `E:NQR` | `R:NQW` | | ERR, ABRT, EC, BRK, SPECIFIC |

`SB:RQ` has room for `NRSRC` = 17 resources (`SSDAT.txt:396`), and 7 are defined. `E:ND` is
"no disc page", used by log-on when no JIT granule is free (`GJG4`).

- **Block**: the user goes on the *head* of the resource's sub-queue `SB:RQ`. `U:MISC` gets the
  resource index in byte 0 and the old head in byte 3, `UB:PRIO` (the back link) is set to 0, and
  the state becomes `SQR`.
- **Release** (`T:REL`, `SCHED.txt:1771`–`:1795`): take the head of the sub-queue (or, with
  SPECIFIC, the user the release was reported for, if they are in `SQR`/`SQRO`). Run the release
  routine if there is one. Unqueue the user (`T:UQR`) and make them special compute (`STSC`). With
  FLUSH, repeat until the sub-queue is empty. With NULL, the release routine runs even on an empty
  sub-queue.
- **`OPNUNBLOCK`** lets only one open/close user exist. If `OPNCLSUS` is already set it does nothing;
  otherwise the released user gets `OPNCLSUSR` and becomes `OPNCLSUS`.
- **`STUQFAC`** (`SCHED.txt:1707`–`:1745`) updates ALLOCAT's four buffers (`BUFLAGS`, `BOTTOM`,
  `TEMPBOT`, `WORDCNT`, `ADJSTCNT`). A word count above `BUFMASK` is `SCREECH X'88'`.
- **Abort while blocked**: `SETDL` takes a user out of `SQR`/`SQRO` only when the resource's flags
  include the arriving ERR/ABRT/EC/BRK flag, which only `R:NQW` has. Other blocked users keep the
  flag in `UH:DL` and act on it when they next run.

## 7. The special transitions

| Routine | Line | What it does |
|---|---|---|
| `STIIP`, `STIOMF` | `:1553` | If `UB:MF` = 0 the I/O is already done, so `GRANT` (the user continues). Otherwise the return is changed to `T:SEO` and the user is parked in `SIOW` (or `SIOMF`). For `SIOW` with a DCB other than `M:OC`, the DCB's function-count word gets bit 0 set: "waiting on this one". With a zero function count the user continues |
| `STIOC` | `:1574` | Decrements `UB:MF`. Only matters in `SIOW`/`SIOMF`. In `SIOMF` the user is released when the count drops to `SL:OIMF` (or `SL:BIMF` for batch). In `SIOW` the user is released when the completed DCB was flagged and its count is zero, when there is no DCB or it is `M:OC`, or when `UB:MF` reaches 0. Release goes through `STIOCC` (I/O complete, +2) and bumps `S:SEVF` |
| `STBEEA`, `STBEEAC` | `:1649` | Pick the flag X'1000', X'2000', X'4000' or X'8000' by event number from the bit table, and merge it into `UH:DL` (`SETDL`). `STBEEAC` also moves the user to an interactive compute state (`STIRC`). E:OFF (negative flag) goes through `STABRT` first: for an on-line user it also finds the COC line and marks it off (`COCOFF`) |
| `STCRD`, `STQA` | `:1670` | Go to `STI` or `SQA`, unless X'4000' says the completion already came. Then clear it and continue the user (`T:PULLE`) |
| `STIRCU`, `STUQA` | `:1683` | Completion for the current user before it blocked: set X'4000'. `STUQA` for a user in `SQA` makes them special compute |
| `STASP` | `:1668` | Special compute, queued to the head (first in `SC1`–`SC10`; behind equals in `SC0`, §4) |
| `STKO`, `STKOT` | `:1692` | Clear `RTR` and `JIC`. An executable user is requeued at their current priority. `STOB`, `STI` and `SQR` move to `STOBO`, `STIO` and `SQRO`. Other waiting states stay as they are |

## 8. Log-on and new users

**`T:RCE`** (`SCHED.txt:1859`–`:1868`) reports a COC event for the user on line R7 (`LB:UN`). An
`E:OFF` from COC first sets `HANGUP` in `UH:FLG2`. A line with no user, or user X'FF', goes to
**`LOGON`**, which only acts on a break (`E:CBK`). It takes the head of the `SNULL` queue, then
checks `S:OUIS` < `S:OUAIS` and that a swap device's `M:FREE#GRAN` exceeds `S:OUAIS`. Failing any
of these it does nothing. Otherwise it counts the user in `S:OUIS`, ties them to the line, and
starts them at `SL:OPRIO` through `ADD1`.

**`ADD1`** (`SCHED.txt:1922`–`:1980`) is also called by MBS and `T:GJOBSTRT` for batch and ghost
users:

1. Bumps `S:CUIS` and stores the base priority.
2. **`GETJIT`** picks the swap device with the most free granules (`UB:SWAPI`) and gets a JIT
   granule there (`T:SGAJIT` at `M:JITPAGE`, stepped by `MB:SPACEJIT`).
3. Sets `UH:AJIT`, `TIC`+`PPSWP` in `UH:FLG`, `SQUAN`+`SWAPD` in `UH:FLG2`, a page count of
   1+`:BIG`, and an empty DO list. A resource index from `T:GJOBSTRT` in R10 byte 0 becomes the
   `RAS:DOL` DO-list entry (`RESCNCT`).
4. With a granule, `STIRC` moves the user from `SNULL` to an interactive compute state. They aren't
   `RTR`, so `T:SS` will swap them in. Without one, `UH:AJIT` = −1 and the user blocks on `E:ND`.
   The swapper re-enters at `GETJIT` when it tries again.

## 9. `T:SE`, the execution scheduler

`SCHED.txt:1021`–`:1209`:

1. `UNMAP`, `T:SS` (swap schedule), `SACT` (the symbionts), and `T:SES` (slave CPUs; a no-op
   without MP). `SEO`, used by `T:SEO`, starts at the `T:SES` call.
2. **Find the first non-empty queue.** A doubleword load of `SB:HQ` bytes 0–7, `OR X'7D'` into
   byte 0, a floating normalize (`SFL`), and a shift and invert give the index of the first non-zero
   head among states 1–7 (`SCHED.txt:1040`–`:1047`). If all are empty, the scan starts at state 8.
3. **Find a ready user.** From that state up to `SEXU`, walk each queue for the first user with `RTR`
   set (`SIC1`–`SIC3`). So the order is `SRT`, `SC0`, ..., `SC10`, and queue order (priority)
   within a state.
4. **`SE1`** (`SCHED.txt:1129`–`:1209`): set `S:CUN`, load access protection (`LPC`) and the map
   (`LDMAP`) from the JIT page. If `RTR` went off meanwhile ("SWAPPER DIDN'T STEAL HIM"), go back
   to `T:SE`. Load special JIT access if `SJAC`. Decay the priority, set `S:CUP`, decrement `S:HIR`,
   and move the user to `SCU`. Then:
   - **Swap errors** in `UH:FLG2`: a context error goes to `T:DELUSZAP`, a JIT error to
     `T:SCRATCH%USER`, and a user-area error sets ERR in `UH:DL`.
   - Just swapped in: `T:ACCTEX` accounts the time so far, and `SWAPD` is cleared.
   - Clock 4 is pointed at `J:OVHTIM`, and the quantum mark is saved in `U:MISC`.
   - A DO list goes back to `SSE1`. An expired `STIMER` (`J:TIMENT`, `J:UTIMER` ≤ 0) goes to its
     routine once through `ALTENT`. Otherwise `T:PULLE`.
5. **Nobody ready**: set `S:CUP` = X'FF', release read-ahead pages (`RAPURGE`, if loaded), and do the
   shutdown check. `S:CUIS`+`GOODNGT` ≤ 0 with no symbiont active ends with `SCREECH X'404'`. See
   [`keyin.md`](keyin.md) for `ZAP`.
6. **Idle** (`SCHED.txt:1085`–`:1126`): enabled, choose the idle counter by why the system is idle,
   point `S:CLOCK4` at it, and show the reason in the PSD's floating-mode bits:

   | `S:SIP` | I/O wait (`SIOW`/`SIOMF`) | Counter | FS FZ FN |
   |---|---|---|---|
   | 0 | no | `C:IDLE` | 1 0 0 |
   | 1 | no | `C:IDLES` | 0 0 1 |
   | 0 | yes | `C:IDLEW` | 1 1 0 |
   | 1 | yes | `C:IDLESW` | 0 1 1 |

   If the clock 3 counter `C:TINC` isn't positive, `WD X'1700'` with X'80' triggers it. Then
   `WAIT`. Any interrupt ends the wait ("AT LEAST EVERY 2 MILLISECONDS"), and the code branches to
   `T:SE` again.

## 10. `T:SS`, the swap scheduler

`SCHED.txt:2102`–`:2672`. It isn't re-entrant: `XW` of 1 into `S:SIP` returns at once if a swap is
already in progress. `TSS2` clears the swap-set cells (`S:PCT`, the swapper's page chain `S:FPPH`/`T`/`C`,
`SB:OSN`, `S:OSS`, `S:PRPC`, the `S:FPL` count).

1. **Pick a user to swap in.** The same scan as `T:SE`, but for the first executable user *without*
   `RTR`. If there is none, `S:ISUN` = 0 and the code goes on to step 4.
2. **`SSIN`.** If this is the user that failed last time and the swap set hasn't changed
   (`S:SEVF` = `S:FSEVF`), give up quietly, unless ALLOCAT needs to go out (`ALLOOUT`). For a user
   with `BYPASS` set, a fit check (`GIVEUP7`) either skips them or clears `BYPASS`. Then count the
   pages needed: `UB:PCT`, less the pages already in core if the JIT is (`JIC`), plus each needed
   processor not in core. Those are the monitor overlay, the command processor or the processor root
   and overlay, and the debugger or special processor (`PRCAV` adds them to `SB:PNL`). When the JIT
   isn't in core, the processors' use counts `PB:UC` are incremented here.
3. **Find pages** (`SWIPEPGS`). Move the whole free pool `M:FPPH`/`T`/`C` onto the swapper's chain.
   Enough pages go to `GOTNUF`, exactly enough to `SWAPIN`. Otherwise **`PFA`** scans `PX:HPP` for
   in-core shared processors with `PB:UC` = 0, a doubleword at a time on a Sigma 9 (`:BIG`), and
   lists them with their call frequency (`GETPRCPG`, `S:FPL`, `S:PRPC`). If they still don't cover
   the need, the code goes to step 4.
4. **`USERSOUT`: choose users to swap out.** Walk the queues in the order of `SB:SWP`: `SW`, `STI`,
   `SC10`, `STOB`, `SQR`, `SQFI`, `SQA`, `SC9`, ..., `SC0`, `SRT` (`SCHED.txt:763`), each from the
   tail. A user is taken if they are in core (`JIC` or `RTR`) and none of the following holds:
   - they hold `RTHOLD` or `CALINT`, or have I/O going (`UB:MF`);
   - they are executable, in core, and hold `RMAHOLD` or still have `SQUAN` (haven't had their swap
     quantum);
   - they are a batch job in a held partition (`PLH:FLG`).

   At most `SMAXOUT`−1 are taken. Their pages, and the pages of processors whose use count drops to
   0 because of them (`CHKPRC`, `SB:FPL`), are added up. The walk stops at success, when it reaches
   the user being brought in (`GIVEUP`), or at the end of the list (`GIVEUP`). So only waiting users
   and users less urgent than the in-swap user are candidates. With nobody to bring in, the walk
   stops at the first executable queue (`SC10`). The waiting users found in `SW` and `STI` are
   swapped out anyway.
5. **`PROUT2`/`PROUT3`.** If any event happened during the walk (`S:EVF` changed), undo and walk
   again (`USEROR`). Otherwise take the freed processors' pages, and report **`E:KO`** for each
   chosen user (`T:RUE`). They lose `RTR`/`JIC`, and the waiting ones move to their out-of-core
   states.
6. **`GOTNUF`.** Bump `S:SEVF`. With nobody coming in, go to `SWAPOUT`. Otherwise, if still short,
   sort `S:FPL` by frequency and take the least-called processors' page chains (`KOPROC`, clearing
   their `PX:HPP`). Return any excess to the free pool (`RETXCS`). Then **`DOSWAP`** goes to
   `SWAPOUT` if anyone is to go out, else `SWAPIN`. With sense switch 4 set, `T:PGCHK` first checks
   the free page chain and ends in **`SCREECH X'01'`** "PAGE CHAIN INCONSISTENCY" if it's broken
   (`SCHED.txt:2394`–`:2441`).
7. **`GIVEUP`** (no swap set): count `C:NSP`, return the swapper's pages to the free pool, undo the
   processor counts, and remember the failure (`S:ISUNF`, `S:FSEVF`). Then check whether the user
   can ever fit (`T:TOTESZ`, plus 6 pages for a monitor overlay, against `S:PCORE`). If not, the
   result is **`SCREECH X'62'`** "IMPOSSIBLE SWAP CONDITION". If they fit, `GIVEUP8` works out the
   deficit against the fluid pages (`S:ACORE`−`S:RTCORE`). When the stealable pages
   (`S:STL#`−`SL:RSVP`) could cover it, it records the deficit in `S:STLC` for the page stealer.
   (See the open questions on how this path returns.)
8. **`SSEXIT`**: clear the flags and `S:SIP`, then `T:SEXIT`.

`T:TOTESZ` (`SCHED.txt:2686`–`:2714`) sums a user's size. R2 is the gross size: the data pages plus
each associated processor. R0 is the same without processors locked in core (`PB:LCT`).

## What a first translation needs

| Piece | Source | Notes |
|---|---|---|
| States, queues, links | `STATE`, `SB:HQ`/`SB:TQ`, `UB:FL`/`UB:BL` | Plain lists per state; keep the numbers, they are used arithmetically |
| Transition tables | `ESTS`/`ESTS1`, `RESOURCE` | Build `S:SET`/`SB:SET` from the same declarations, so `SCREECH 02` happens where it would |
| Event reporting | `RCE0`, `RCE4`, `T:CHSE`, `CHS1` | With the priority insertion and `S:HIR` |
| Special transitions | `S:TRNSVEC` … `STKO`, `T:RES`/`T:REL`/`T:UQR` | `STUQFAC` on the four buffers; buffer 1 is the file system's pack stack ([`files.md`](files.md) §8) |
| Exit path | `SSE0`–`SSE6`, `T:DOLIST` | DO-list types 1 and 7 at first; ABRT/ERR to stubs for `T:TELDELCCI`/`SETRNST` |
| Execution scheduler | `T:SE`, `SE1`, idle | Ghosts as Python stand-ins for "running a user"; the idle check already exists for `ZAP` |
| Log-on and new users | `T:RCE`, `LOGON`, `ADD1`, `GETJIT` | Granules from a stub swap device |
| Swap scheduler | `T:SS` up to `DOSWAP` | Page counts only; `SWAPIN`/`SWAPOUT` just flip `RTR`/`JIC` at first |

## Open questions

- **The return from `GIVEUP8` after a failed swap.** From `GIVEUP1`, R6 still holds `S:FPPT` (loaded
  at `GIVEUP`, `SCHED.txt:2583`). Yet `GIVEUP8` returns through `0,R6` or `1,R6`. The
  `LI,R6 GIVEUPA` that would make those land on `GIVEUPA` and `GIVEUPA`+1 = `SSEXIT` comes after the
  `SCREECH X'62'` (`:2625`), where it can't be reached by falling through. `GIVEUPB` sets `BYPASS` and
  then falls into `GIVEUPA`, which is `B GIVEUPB` (`:2664`–`:2668`). As read, that loops. Either an
  instruction is misread here or this copy isn't what ran. `GIVEUP7`'s other caller, `SSIN12`, sets
  R6 with its `BAL` and is fine.
- **`XFDFF` isn't X'FDFF'.** `XFDFF EQU NB31TO0+14` (`SCHED.txt:241`) is ¬2<sup>13</sup> = ¬X'2000' by
  `TABLES.txt:178`. So `SE1`'s "RESET CAL INTERRUPT BIT" actually clears `RMAHOLD` (X'2000'), not
  `CALINT` (X'200'). The neighbouring `XFFEF` (`NB31TO0+5`) and `XFFF7` (`NB31TO0+4`) do match their
  names.
- **Back links in resource sub-queues.** Blocking puts the user on the head with back link 0, but
  doesn't set the old head's back link (`UB:PRIO`) to the new user (`SCHED.txt:1761`–`:1768`).
  `T:UQR` of an entry that isn't the head, such as an `R:NQW` user aborted while blocked, would then
  treat that entry as the head. It would also make release LIFO rather than FIFO.
- **`SL:SQPB` is called a boost**, "PRIO BOOST IF INTERRUPT AFTER SQNT", but it is *added* to the
  priority value (`SCHED.txt:843`), and a larger value is less urgent. That moves a user preempted
  between `SL:SQNT` and `SL:SQUAN` back two notches.
- **The log-on capacity check** compares `S:OUAIS` (on-line users allowed) with each swap device's
  free granule count (`SCHED.txt:1885`–`:1890`). The intent isn't clear.
- **User X'FF' in `LB:UN`** is treated like an empty line by `T:RCE` (`:1867`). What sets it isn't
  known yet.
- **Sigma instruction details this relies on:** `SFL` normalizing in the queue scan (as with `INT` in
  [`recovery.md`](recovery.md) §6), the compare instructions setting CC2 for a non-zero AND (all the
  `CH`/`BANZ` flag tests), and the mask register of `CS` in `T:OFF`'s "pre CCI abort" check
  (`SCHED.txt:1225`–`:1226`, mask in R14, which isn't set on that path).
- **`USERSOUT` sets its in-progress flag** with `STS` into `S:ISUNF` under a mask in R8, while the
  comment says "BIT 0 OF S:SIP" (`SCHED.txt:2452`–`:2453`).
- **Not read yet:** `SWAPPER` (`SWAPIN`, `SWAPOUT`, the page stealer behind `S:STLC`), `SACT`,
  the COC DO-list routines, `RT:INTENTRY`, `T:ECCP`, `T:TELDELCCI`, `T:GJOBSTRT`, and what the
  resources `R:SYMF`, `R:SYMD`, `R:OCR`, `R:CBA` and `R:NQW` are. Apart from `E:ND` (no disc page)
  and `R:OCR` (open/close), their purpose isn't known.
