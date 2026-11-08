# UTS / CP-V crash recovery

What happens when the monitor crashes (`SCREECH`), when a single user is aborted (`SUA`), when a
dump is requested (`DUMP`), and when the operator forces recovery with sense switch 3. The path
runs from the entry PSDs in `INITRCVR` to the RECOVER overlay (`RCVCTL`), and ends in a
simulated disc boot. [`boot.md`](boot.md) covers the boot itself, and where `TBOOT:` puts RECOVER on the
swap disc.

> Source paths are relative to `c00co/`. Sigma memory is word-addressed; a sector is 256 words,
> a granule 2 sectors (one page). "16K" means 16K words.

## Modules involved

| Module | Role |
|---|---|
| `UTS` (`UTS.txt:20`) | The `SCREECH`, `SUA` and `DUMP` procs. |
| `INITRCVR` | Resident part, in the root. Holds the entry PSDs (`RCVPSD`, `OPRECPSD`), the crash entry `RECOVER0`, the disc addresses `TBOOT:` fills in (`RCVDISC`, `RCVSIZE`, `RCVSTART`, `RCVRAD`, `SEEK4000`, `MPPSEEK`), and the return path after a single-user abort (`SUARTN`). |
| `RCVCTL` | The RECOVER overlay's controller. It logs the reason, dumps memory, saves system state, and reboots. |
| `CYCUSR` | RECOVER's dump and user-cycling routines (`RCVDMP`, `INCRDA`, `SV1`, `MVEBUF`). |
| `RCVDEF` | RECOVER's own copy of the I/O tables (`RCVRIOTABLE`): `R:DCT1` and the others are those tables relocated, so recovery doesn't depend on the crashed monitor's copies. |
| `RECOVER2`, `RVGHOST` | Restore what recovery saved, after the reboot (GHOST1) or after a single-user abort. Not covered here. |

## 1. The crash call

`SCREECH`, `SUA` and `DUMP` are one proc (`UTS.txt:20`) with `NAME` values 0, 1 and 2. Each call
assembles to two words:

```
XPSD,0  RCVPSD
GEN,16,8,8  code, type, subcode       type: 0 SCREECH, 1 SUA, 2 DUMP
```

(`TCOR(RCVPSD,S:FR)` only controls an extra `DO1` line. The two-word size fits `ROOTSA` being at
X'35' in `DBOOT`; see `boot.md` §5.)

The `XPSD` saves the current PSD in `RCVPSD` and loads the second word of `RCVPSD`. That word is
`:PSD RES,(IA,RECOVER0),INH` (`INITRCVR.txt:68`), so control goes to `RECOVER0` with the map
off and interrupts inhibited. The saved PSD's instruction address points at the `GEN` word.

`DBOOT` uses the same mechanism: with sense switch 3 set it executes `SCREECH -1` (`BOOTSUBR.txt:1757`).
It does so **before** reading anything from disc, so it relies on the hung monitor still being in memory,
with its `RCVPSD`, `INITRCVR` and disc addresses. Operator recovery is a way to recover a hung
system, not a way to start a cold machine.

`OPRECPSD` (`:PSD RES,(IA,OPRECENT),INH`) is a second entry. `OPRECENT` (`INITRCVR.txt:120`)
saves the registers and swaps the saved `RCVPSD` and `OPRECPSD`. That way the operator-recovery PSD
is what gets analysed, and if recovery itself hangs the previous `RCVPSD` is kept. It sets the code
to −1 and subcode 1, then joins the common path at `RCV41`.

## 2. `RECOVER0` — decoding the call (`INITRCVR.txt:134`)

1. Saves register block 1 in `SAVEREGS1` and block 0 in `SAVEREGS`. Sets the `CSED%PATH` recovery flag
   for the fault handlers.
2. **Multiprocessor:** if there are slave CPUs (`NSCPU`), it puts `B SYSTRT` in `SYSTRT`, sets
   `SB:RCVR`, and waits until every slave has acknowledged (`SB:RCVA`) or is stopped (`SB:STATE`).
3. **Finds the code word.** The address is the saved PSD's instruction address (the `XPSD` address + 1):
   - 15 or less: the call was executed from a register, so the word is in `SAVEREGS`.
   - Mapped and at or above X'8000': the address is translated through the current user's
     `JX:CMAP`. A bad user number, JIT or map gives code 03 with subcode 1, 2 or 3 (`RCV41`, `RCV42`, `RCV43`).
4. **Code and subcode** (`RCV60`): `AND` with X'FFFF00FF' keeps the code halfword and the subcode
   byte. The mask is `LI` of X'F00FF', and the 20-bit immediate sign-extends.
   `DBOOT`'s `SCREECH -1` therefore arrives as code X'FFFF' (−1), subcode 0. If they are zero, the code is taken from R15 instead (`SAVEREGS+15`): R15 holds code and
   subcode if its left half is non-zero, and otherwise just the code. The result goes in `RCVCODE`.
5. **Type** (X'300' bits of the word, stored into `RCVCODE` for ANLZ): SCREECH goes to §3, DUMP to
   §4, and SUA is checked first (§4).

## 3. Crash path (`RCV1`, `INITRCVR.txt:321`)

1. `BAL,11 RT:RCVR`: a real-time system can supply its own recovery routine (`RTBOOT`'s stub just
   returns).
2. Turns off the PDF flag. Halts every SYSGEN'd device that isn't partitioned out (`DCT3`), then
   acknowledges all pending interrupts (`AIO`).
3. **Saves X'4000'–X'7FFF'** (`KRD2`). `DUMPCOM` seeks to `SEEK4000` and writes the 16K words at X'4000' to the
   swapper (`M:SWAPD`). On a pack, `UNEND` restarts the write on the next cylinder when it crosses a
   cylinder boundary.
4. **Reads RECOVER over that area** (`REDDWD`): seek `RCVDISC`, read `RCVSIZE` bytes to X'4000'.
5. `B *RCVSTART+1,R6` with R6 = 0. Sigma indexing is applied after indirection, so this branches to
   the start address `TBOOT:` stored in `RCVSTART+1`, which is `RCVCTL`.

## 4. Single-user abort and dump (`INITRCVR.txt:197`–`:320`)

A SUA aborts the current user instead of the system, if it is safe to. It turns into a full crash
(`RCV1`) if any of these hold:

- COC interrupts are disabled (`CO:INTFL`).
- The PSD used is inhibited (`Y07`) or not mapped (`Y004`). For the codes in `SCODES` (0, X'61',
  X'79', X'7E') the trap PSD `TRAPPSD` is checked, and for the others `RCVPSD`.
- The user has had a SUA before (`J:TELFLGS`).
- The user is a system ghost (`S:CUN` ≤ `MING`).
- The dump file is busy (`DUMPFILE`).

`DUMP` skips those checks, but if the dump file is busy it just returns to the caller (`DUMPRTN`).

Otherwise, `STOPIO` stops I/O on the swapper and on the dump-file device. A rotating device is
halted; for a tape it waits for the transfer to end. The PSD then goes unmapped, the SUA's time and user
number are recorded (`SUACNT`, `SUATIME`, `SUACUN`, a 4-entry circular buffer), and the code
joins `KRD2` with **R6 = −1**. So:

- The save of X'4000'–X'7FFF' goes to the word before `SEEK4000` ("SEEK OF X'4000' FOR SUA FILE"),
  on the dump-file device (`SUABTFLE`). GHOST1 sets that seek address when it opens the dump file:
  the file's X'40'th sector (X'40' sectors = X'4000' words, `GHOST1D.txt:287`).
- `B *RCVSTART+1,R6` lands one word before `RCVCTL`, on `B SUABORT` (`RCVCTL.txt:92`).

On return (`SUARTN`), `INITRCVR` reads the monitor's X'4000'–X'7FFF' back from the *root image* on
disc. It temporarily points `RCVDISC` at `MPPSEEK`, which is root part 2 (`boot.md` §4). This works
because that area is monitor procedure and so matches its disc copy. It then restarts the halted
I/O and starts the `RVGHOST` ghost. A DUMP returns to the instruction after the call (`LPSD` of
`RCVPSD` + 1). A SUA aborts the user through `T:ABORTM` with code X'7F', with the crash code as subcode.

## 5. `RCVCTL` — the RECOVER overlay (`RCVCTL.txt:93`)

1. **Quiet the machine:** clears up to 238 pending interrupts. Swaps in its own trap XPSDs: X'40' goes to
   `NORCVR`, so a trap in recovery is a recovery failure, and X'46' (watchdog) is ignored. The old ones
   are saved in `TRAPSAVE`. Disarms the override, I/O and clock groups.
2. **X'2A' = 0**, "INDICATE RECOVERY TO GHOST1" (see §6).
3. Converts the channel letters in RECOVER's own `R:DCT1` into channel numbers, using the
   `X560CUCL` table on a 560, as `INITL` does at install.
4. **Logs the reason on the OC** (`TYOUT`), using the code in `RCVCODE`:

   | Code | Message |
   |---|---|
   | −1 (operator) | `OPERATOR RECOVERY`; X'2A' halfword 0 is incremented, giving X'00010000' |
   | 0 – X'FF' | `SOFTWARE CHECK  cc-ss`: the code's low byte and the subcode, in hex (`HEXCVT`) |
   | other | `RECOVERY FOR UNKNOWN REASON` |

   Code X'89' (from ALLYCAT) also records an HGP reconstruction request in the recovery buffer. Code
   X'404' ("ZAP CODE, FROM SSS") sets X'2A' to X'40404', which marks a shutdown. The scheduler's idle
   check executes `SCREECH X'404'` after a `!ZAP` (`SCHED.txt:1084`, see [`keyin.md`](keyin.md)). Then `TYOUT`, `COCOUT` and
   `RBOUT` stop typing (`INT` / `BDR` on X'2A'), and no dump is taken.
5. Moves `RCVRAD` on by two granules (`INCRDA` twice, `CYCUSR.txt:1335`) to leave room for the
   recovery buffer, and makes `RECOVER0` branch to `NORCVR` from now on (`STW NRCVRX`).
6. Tells the terminals `RECOVERY SAYS-STAND BY-` (`RELOGM`, `RCVCTL.txt:1181`, through `COCOUT`, `:363`)
   and the remote work stations to re-dial. COCOUT writes to every line of every COC directly, a
   character at a time through RECOVER's own ASCII table. The message starts with eight rubouts
   (`TC`, timing characters for the carriage) and two bells. NORCVR, when recovery itself fails, sends
   `STAND BY - FOR EXTENDED RECOVERY` (`FAILMS`, `:1141`), as RECOVER2 does for bad granule maps
   (`HGPERRUM`, `RECOVER2.txt:444`).
   Checks TP, and types the date and time.
7. Dumps memory (`RCVDMP`, unless shutting down) and saves system state. This is system-specific:
   ALLOCAT stacks, queued I/O, real-time pages, TP queue buffers and journals, symbiont tables, the
   batch and terminal users (`CYCUSRS`), the error-log granules (checked with `R:CHKDA`), down
   devices, system limits, COC messages and released granules. The saved words go into the recovery
   buffer (`SV1`), which `MVEBUF` writes out at the end.
8. **Reboots** by simulating a disc boot (`RCVCTL.txt:299`):
   - Halts every device that isn't partitioned out.
   - Reads the first 88 bytes of sector 0 (the `DBOOT` bootstrap) into X'2A', and then puts back
     the saved X'2A' flag.
   - Stores `M:SWAPD` in X'25' and disarms all external interrupts.
   - Branches to `BOOTENT`, skipping `DBOOT`'s sense-switch test. The fresh root from disc replaces the
     crashed one, and `INITIAL` and `MONINIT` run as on a disc boot.

If anything goes wrong, **`NORCVR`** (`RCVCTL.txt:1163`) runs once:

- It saves the registers and tells users `STAND BY - FOR EXTENDED RECOVERY`.
- It types `RECOVERY ERROR -` on the OC, writes the error log to tape (`TAPDMP`), and types
  `RE-BOOT SYSTEM - SAVE DUMP TAPE FOR ANLZ`.
- Then it loops (`B %`): the operator has to reboot. A second entry loops at once.

### The dump area at `RCVRAD`

`TBOOT:` sets `RCVRAD` to the sector just after the root on the swap disc, and `SEEK4000` to
`RCVRAD` + X'44' (`boot.md` §4). The two fit together:

- `RCVCTL` takes the first 4 sectors (two `INCRDA` granules) for the recovery buffer.
- `RCVDMP` (`CYCUSR.txt:1308`) then writes a full memory image starting at the new `RCVRAD`, 256
  pages per command list, if `RCVRDSZ` has room and the address passes `R:CHKDA`. Otherwise it dumps
  to tape. The command list `COMMRAD` (`CYCUSR.txt:1596`) writes X'0'–X'3FFF', then *reads with skip*
  over X'4000'–X'7FFF' ("SKIP WRITTING X'4000'-X'7FFF'"), then writes from X'8000' on.
- The skipped 64 sectors are exactly where `INITRCVR` already saved the crash-time X'4000'–X'7FFF'
  before RECOVER overwrote it: 4 + X'40' = X'44' sectors after the original `RCVRAD`.

So after recovery the dump area holds one consistent image of memory at the time of the crash.

## 6. X'2A' through a recovery

| Value | Set by | Meaning |
|---|---|---|
| 0 | `RCVCTL` | Crash recovery |
| X'00010000' | `RCVCTL` (`MTH,1 X'2A'`) | Operator recovery |
| X'00040404' | `RCVCTL` (code X'404') | Shutdown: no typing, no dump |

The flag survives the reboot: `RCVCTL` saves it in D4, reads `DBOOT` over X'2A', and stores it back.
When `MONINIT` then does `INT,11 X'2A'` / `BCR,15 REQDELT` ("NO RT OR DATE/TIME MSG IF RECOVERY",
`BOOTSUBR.txt:175`), the `INT` sets the condition code from bits 0–3 of the word. Those bits are 0
for all three recovery values. On a normal disc or tape boot, X'2A' holds the bootstrap's first instruction
(`RD,0 0` or `LI,1 n`), which has a non-zero opcode nibble. So only a recovery skips the dialog.

**By the Sigma `INT` definition** (CC ← bits 0–3, R ← bits 4–15, Ru1 ← bits 16–31; for an odd R
such as R11 or R15, R ends up with bits 16–31; confirmed by simh's Sigma simulator, `sigma_cpu.c:870`–`:878` ([`interpreter.md`](interpreter.md) §1)), the low
halfword then tells the boots apart:

| X'2A' holds | Low halfword | `MONINIT` |
|---|---|---|
| `RD,0 0` (`DBOOT`) | 0 | − 4 < 0: no `ENTER ANY OF`; `BDR,11 TBOOT:` falls through, so a disc boot |
| `LI,1 n` (`MTBOOT`) | *n* (root records) | ≥ 4: asks `ENTER ANY OF`; `BDR,11` branches to `TBOOT:` |
| −1 (F option) | X'FFFF' | `TBOOT:`, and `SWAPINIT`'s `X'2A'` + `SEGNO` ≤ 0 test |

**The boot-type codes.** The table in the `BOOTSUBR.txt:95` comment (0 indeterminate … 5
operator recovery) is not a set of values stored in X'2A'. It is the index into GHOST1's
`BOOTYPE` table (`GHOST1D.txt:74`), which GHOST1 matches against X'2A''s halfword 0 for the
start-up error-log message (`GHOST1D.txt:299`). GHOST1's own comment repeats the same list:

| Index | Halfword 0 of X'2A' | Boot | What put it there |
|---|---|---|---|
| 0 | anything else (`'NO'`) | indeterminate | |
| 1 | X'2210' | cold tape boot | `MTBOOT`'s `LI,1 n` |
| 2 | X'FFFF' | boot under files | `MONINIT`'s −1 for the F option |
| 3 | X'6C00' | RAD boot | `DBOOT`'s `RD,0 0` |
| 4 | X'0000' | recovery | `RCVCTL` |
| 5 | X'0001' | operator recovery | `RCVCTL`'s `MTH,1` |

FIX1 tests byte 0 for X'22' in the same way ("IS IT COLD TAPE BOOT", `FIX1.txt:5253`), to decide
whether to initialise ALLYCAT's data or to read the recovery buffer back from `RCVRAD`.

**In the translation** (`recovery.py`, `cocout`): the message goes to the lines the scheduler's COC
has, to those with a terminal connected, as ASCII. `TC` is sent as DEL, `BELL` as BEL, and `CR`/`LF`
as themselves. RELOGM's first character, `XO`, isn't sent: the listing's text lost the control
characters of `CR`, `LF`, `TC`, `BELL` and `XO` (`RCVCTL.txt:1122`–`:1129`), and `XO`'s use
(X-OFF, probably) isn't certain. The lines' own buffers aren't touched, as RECOVER bypasses COC.

## Open questions

- **The `INT` definition** in §6 (resolved): simh's Sigma simulator, `sigma_cpu.c:870`–`:878` ([`interpreter.md`](interpreter.md) §1) does exactly this. It makes the
  disc, tape, F and recovery cases all consistent.
- **The shutdown code and `TBOOT:`.** After code X'404', X'2A' is X'00040404'. Under the `INT`
  assumption, `MONINIT` goes straight to `REQDELT` with R11 = X'0404', and `BDR,11 TBOOT:` would then
  branch to the tape install. Whether a shutdown really ends in a tape boot, or whether the `INT`
  reading is wrong here, hasn't been settled.
- **`RCVRDSZ`**, the dump area's size in granules, is set by `SYSMAK0` (`SYSMAK0.txt:594`): from
  `RCVRAD` to where SYSMAK finished writing, extended towards `BOOTSBAND` up to `HIGH`+3 granules.
  When and from where SYSMAK runs hasn't been traced.
- **`STOPIO` for tapes** waits up to X'2000' × 1000 delay loops for a pending interrupt, and then returns
  whether or not the tape has stopped.
