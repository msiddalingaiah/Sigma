# UTS / CP-V Boot Process

How the Xerox UTS monitor for the Sigma 7, Sigma 9 and Xerox 560 is brought up: the tape that
SYSGEN writes, the cold tape boot that installs the system on the swap disc, the disc boot
that restarts it, and the setup code that every boot runs.

> Source paths are relative to `c00co/`. Line numbers refer to the `.txt` source files.
> Sigma memory is word-addressed: an address like X'4000' is a word address, and "16K" of
> memory means 16K words (64 KB). Tape and disc transfer sizes are given in bytes.

## Modules involved

| Module | Role |
|---|---|
| `UTMBPMBT` (SYSGEN WRITEMON) | Writes the bootable BO/PO system tape: a short tape bootstrap, the monitor root in absolute form, a creation-data record, then XDELTA, the shared processors, the overlays and RECOVER, with the patch deck interleaved. |
| `INITIAL` | Where the monitor starts executing. Sets up traps and interrupts, calls `MONINIT`, loads memory protection, builds the monitor JIT and starts the first ghosts. |
| `BOOTSUBR` | Most of the boot logic. `MONINIT` (CSECT `BOOTSUBR`) runs on every boot. `TBOOT:` (CSECT 0) runs only on a tape boot. Also holds the disc bootstrap `DBOOT`. |
| `RECONFIG` | Boot-time reconfiguration and partitioning. Converts device addresses in the DCT tables and handles the `:` commands. Its 3-entry vector must match what `BOOTSUBR` expects. |
| `XDLT` | XDELTA, the resident debugger. On a tape boot its `PACHSTRT` entry (`XDLT.txt:3238`) applies the patch deck to the root and to each segment as `TBOOT:` copies it (see [`tape.md`](tape.md)). |
| `TABLES` | Holds `BOOTIC`, the channel commands the disc boot uses to read the second and overflow parts of the monitor root. |
| `INITRCVR` | Recovery: entry PSDs (`RCVPSD` → `RECOVER0`, `OPRECPSD` → `OPRECENT`), the disc locations of the recovery code (`RCVDISC`, `RCVRAD`, `SEEK4000`), and the default console/device addresses (`OCNDD`, `CNDD`, `LLNDD`). |
| `RTBOOT`, `RTROOT` | Real-time stubs and data. `RTBOOT` defines `RT:REBOOT`, which just returns; GHOST1 (`GHOST1D.txt:205`) calls it for real-time user initialization. In a real-time system it is replaced by a user-supplied module. |

## Fixed low-memory locations used during boot

| Location | Symbol | Use |
|---|---|---|
| X'25' | — | Address of the device the system was loaded from. The bootstraps do `SIO *37`. |
| X'26' | `SYSTRT` | System start branch (set to `B SYSTRT` from `MPBR`). Also used by multiprocessor slaves. |
| X'27' | `BOOTFLG` | Boot option flags in byte 0 (see below). The default for a disc boot is X'C0' (I,P). |
| X'2A' | — | Boot type code (see below). Both bootstraps are also loaded here. |
| X'2B' | — | `SYSVERS` (system version) after `INITIAL` runs. |
| X'40'–X'5F' | — | Trap and interrupt XPSDs installed by `INITIAL` (`XPSDS` table). |
| X'54' | — | Clock counter. Boot code uses it for timeouts and zeroes it after the date/time prompt. |
| X'5A' | — | Load point of the monitor root. Nothing below X'5A' is loaded from tape or disc. |
| X'5E'–X'5F' | — | `DATA 0,INITIAL`: the monitor start address the disc boot jumps through. |

### Boot type: location X'2A' (`BOOTSUBR.txt:95`)

| Value | Meaning |
|---|---|
| 0 | Indeterminate |
| 1 | Cold tape boot |
| 2 | Boot under files (tape) |
| 3 | Disc (RAD) boot |
| 4 | Recovery |
| 5 | Operator recovery |

These codes are not values stored in X'2A'. They are indexes into GHOST1's `BOOTYPE` table
(`GHOST1D.txt:74`), which matches halfword 0 of X'2A':

| Halfword 0 | Code | Why it is there |
|---|---|---|
| X'2210' | 1 | `MTBOOT` loads at X'2A', so X'2A' holds its first instruction, `LI,1 n` |
| X'FFFF' | 2 | `MONINIT` stores −1 for the F option |
| X'6C00' | 3 | `DBOOT` loads at X'2A': its first instruction is `RD,0 0` |
| X'0000' | 4 | `RCVCTL` stores 0 before rebooting |
| X'0001' | 5 | `RCVCTL` adds 1 to halfword 0 for an operator recovery |

`MONINIT` reads the word with `INT`. Its condition code (bits 0–3) is zero only for the recovery
values, and those skip all operator prompts. The low halfword then separates the tape boot (*n*
root records, ≥ 4) from the disc boot (0). `BITOTM`, `CCI0` and `SWAPINIT` test for a negative value
(boot under files). Details, and the assumption about `INT` this relies on, are in
[`recovery.md`](recovery.md) §6.

### Boot flags: `BOOTFLG` (byte 0 of X'27')

The reply letters are matched against `CODES TEXTC 'DFTCPI'`, and letter *n* of that string sets
`BT31TO0+2+n`, which is bit value 2^(n+1) in the byte:

| Letter | Byte value | Meaning | How it is tested |
|---|---|---|---|
| I | X'80' | TTY (operator console) I/O | `LC BOOTFLG`, CC1 |
| P | X'40' | Line-printer output | `LC BOOTFLG`, CC2 |
| C | X'20' | Card patches | (CC3) |
| T | X'10' | Tape patches; the default when there is no reply | (CC4) |
| F | X'08' | Boot under files | `CI,5 8` in `MONINIT` |
| D | X'04' | Keep XDELTA | `Y04` (`BOOTSUBR.txt:84`) |

A disc boot starts with X'C0' (I,P), and answering Y to the XDELTA question makes it X'C4'.

## Overall flow

```
          SYSGEN WRITEMON (UTMBPMBT)
                    │ writes BO/PO tape
                    ▼
 ┌──────────── TAPE BOOT ────────────┐        ┌──────────── DISC BOOT ───────────┐
 │ MTBOOT @X'2A' reads root → X'5A'  │        │ DBOOT (sector 0) @X'2A'          │
 │ jumps to INITIAL                  │        │  sense SW → operator recovery?   │
 └───────────────┬───────────────────┘        │  reads 1st 16K, TIC → BOOTIC     │
                 │                            │  jumps via X'5F' to INITIAL      │
                 ▼                            └───────────────┬──────────────────┘
            INITIAL ◄─────────────────────────────────────────┘
                 │ BAL MONINIT
                 ▼
            MONINIT: machine type, console, memory size, prompts
                 │
        tape? ───┼──────────────► TBOOT: verify devices, RECONFIG, XDELTA patches,
                 │                       copy segments/RECOVER/XDELTA to swap disc,
                 │                       write root + DBOOT ──┐
                 ▼                                            │
            GMONEX: read XDELTA + UMOV from swap disc ◄───────┘
            FIXPPUT: build physical page pool
            PUTRT:   reserve real-time (RESDF) pages
                 │ return via MONIRTN
                 ▼
            INITIAL: LMA (write locks, map), monitor JIT, free boot swap space,
                     start ALLOCAT + starter ghost, enable interrupts → T:SE (scheduler)
```

## 1. Making the boot tape — `UTMBPMBT`

WRITEMON is called from SYSGEN PASS1 (which writes a BO tape) and from DEF (which writes a PO tape). It
reads the `M:MON` load module and writes, in order (`UTMBPMBT.txt:47`):

1. **The bootstrap record `MTBOOT`**, which loads at X'2A' (`UTMBPMBT.txt:798`). WRITEMON fills in
   the number of root records to read (`MTBOOT`) and the monitor entry address from the `M:MON` head
   (`STMONMTB`).
2. **The monitor root**, as 2048-byte records. The first record is written from X'5A', so it overlaps
   the start of the second.
3. **The creation-data record** (`GENINFO`): the `C P - V` banner, the generation time and date, the
   version number, and the list of patch segment names. That list is the shared processors
   (ALLOCAT, GHOST1, FIX) first, then the overlays in name order, and RECOVER last. WRITEMON also prints
   this record on the listing.
4. **XDELTA**, followed by **each shared processor, each overlay and RECOVER**. Each one has a head
   record, followed by data, DCB and procedure records of one page (2048 bytes) each.
   - The symbol table WRITEMON builds (`SYMGEN`, kept in the temporary file `M:TEMP`) is appended to
     XDELTA's pages, so that patches can use symbols. If it doesn't fit below X'10000', WRITEMON
     aborts with `XDELTA TOO BIG - REDUCE ITS BIAS`.
   - Overlays (bias X'4000') must fit in the six-page overlay area. One of 7 pages or more is taken to be
     `UMOV`: it loses 7 pages from its size and gets bias X'4700'. Any other name aborts with
     `OVERLAY EXCEEDS 6 PAGES`.
5. **The patch deck**, interleaved with the segments. WRITEMON copies the `PATCH` file (`M:PATCH`)
   onto the tape after each piece (data, DCBs or procedure), so each piece's patches follow it. Patches
   out of segment order abort with `OUT OF ORDER PATCH`.

The tape bootstrap reads N records from the device whose address is at X'25', retrying each
read up to 10 times, and branches to `INITIAL`. It hangs if a read can't be recovered.

Record formats, head-record words, the patch segment names, and how the patch cards are placed
on the tape and read back by XDELTA are in [`tape.md`](tape.md).

## 2. `INITIAL` — monitor entry (`INITIAL.txt:49`)

1. `LPSD INITPSD` → `INIT2`.
2. Checks for a big-memory (`:BIG`) system on a Sigma 7. If found, prints
   `SYSTEM REQUIRES SIG9 OR X560` and loops.
3. Fills interrupt locations from X'60' up to `MONORG` with `MTW,0 0` no-ops, then installs the
   trap and interrupt XPSDs at X'40'–X'5F' from the `XPSDS` table.
4. If assembled with `DEBUG`, enters the card-reader patcher `PACHER` through `XPSD TRP51`. This
   source sets `DEBUG` to 0 and then to 1, so it is assembled. The patcher asks
   `IF YOU WANT TO PATCH, ANSW. YES` and uses fixed addresses for the TTY (X'01'), LP (X'02') and
   CR (X'03'). Patch cards have a 5-hex-digit location in column 1 and an 8-hex-digit value in
   column 9, and end with `!EOD`. Each card is printed on the LP.
5. Arms I/O and clock 3, then calls **`MONINIT`**.
6. Calls **`LMA`**: `LOADWL` (write locks: monitor data 01, JIT 01, pure procedure 11, UMOV 11,
   I/O buffers 00 on the 560), then `LOADMAP` (memory map and access codes).
7. Builds the monitor JIT stack. Sets up `BOOTSBAND` from `PSA%END` and releases the boot-time
   swap granules (`SL:CORE` worth) with `T:SGRNU` ("REL SWAP SPACE FOR GH-1").
8. Stores `SYSVERS` at X'2B', installs the I/O XPSD at X'5C' for GHOST1, and clears `CSED%PATH`
   so the trap handlers know `INITIAL` has finished.
9. Starts the **ALLOCAT** ghost and the **starter ghost** with `T:GJOBSTRT`.
10. Enables interrupts according to the machine type (Sigma 7: MPI, Sigma 9: MFI, 560: MFI+PFI), fires
    clock 3 and branches to the scheduler **`T:SE`**. From here on the system is up. How the
    operator talks to it through console key-ins, including the `ZAP` shutdown, is in
    [`keyin.md`](keyin.md).

## 3. `MONINIT` — runs on every boot (`BOOTSUBR.txt:107`)

### Machine and console
- Waits about 60 ms for the 560.
- **Machine type:** executes an instruction that traps through X'4D' on anything other than a Sigma 7.
  The trap handler (`NSIG7TRP`) then tries to set the FR floating-control bit. If it sticks the
  machine is a Xerox 560, otherwise a Sigma 9. The result goes into `CSED%MACHINE`
  (X'80' = Sigma 7, X'40' = Sigma 9, X'20' = 560).
- **Operator console (OC):** reads the SYSGEN address from `DCT1`. If `HIO` doesn't respond, the boot
  `WAIT`s for the operator to put a new address in R0, and validates the channel letter (A–H on
  a Sigma, or the `X560CUCL` cluster/unit table on a 560). `OCNDDFLG` tells RECONFIG to update `DCT16`.

### Memory size
Probes downward from `CORE+X'FFF'` in steps of X'1000' words, with trap X'40' redirected to `CORC`.
Sets `CORED` (the memory size) and `HIGH` and `M:FPPT` (the last page number).

### Operator dialog (skipped for recovery)
1. Stores the `SYSTRT` branch.
2. **Tape boot only:**
   ```
   ENTER ANY OF:
   I=TTY I/O  P=LP OUTPUT  F=TAPE FILES  T=TAPE PATCHES  C=CARD PATCHES  D=XDELTA
   ```
   The letters are stored in `BOOTFLG` (see the table above). With no reply the default is `T`.
   Every console read times out after about 10 seconds (`MESSG`).
3. **Real-time systems** (`RTICBHDR` ≥ 0): `RESET RESDF YYY,XXXXX ?` sets the number of resident
   dedicated-foreground pages (decimal, at most 999) and the first page address (hex, 0 or
   ≥ X'10000'; the pages must exist). Builds a `PPTABLE` entry.
4. **`DATE(MM/DD/YY)=`** and **`TIME(HH:MM)=`**. Each field is range-checked against `MIND`/`MAXD`,
   invalid day/month pairs are rejected (`BADATES`), and Feb 29 gets a leap-year check.
5. Zeroes the clock (X'54'). A **tape boot** now branches to `TBOOT:`. A **disc boot** asks
   `DO YOU WANT DELTA (Y/N)` and, on Y, sets the D flag.

### `GMONEX` / `FIXPPUT` / `PUTRT` — common finish
- Reads **XDELTA and the monitor root extension (UMOV)** from the swap disc (`DLTCLST`), retrying on
  error.
- **`FIXPPUT`** builds the physical page pool:
  - Sets the free page chain (`M:FPPH`/`M:FPPT`/`MX:PPUT`) after `TOPROOT`, leaving out a free
    symbiont buffer if there is one (`SPOOL`).
  - Moves the monitor JIT and UMOV pages to the `MP:UPP*` chain.
  - Removes XDELTA's pages if XDELTA is being kept (D flag).
  - Works out the maximum user swap size (default X'B8' pages) from `S:CYLSZ`/`S:UCYL` when pack
    swapping is used (`S:DP`).
  - Sets `SL:CORE`, `S:ACORE` and `S:PCORE` (`S:ACORE` less 7 pages: the AJIT plus 6 for an overlay).
- **`PUTRT`** (real-time only): on a recovery boot, first reads `PPTABLE` back from disc
  (`RDPPTAB`). Then moves each `PPTABLE` page range from the free chain to the `PP:UPP*` chain and
  adjusts `S:ACORE`/`S:PCORE`. Returns to `INITIAL` through `MONIRTN`.

## 4. `TBOOT:` — tape boot / system install (`BOOTSUBR.txt:462`)

This is the cold-start path that installs the system on the swap disc.

1. **`RECNFG:0`**: RECONFIG converts every `DCT1`/`DCT1A`/`DCT1P` device address for Sigma or 560 addressing.
   Each address starts as a channel letter plus two hex digits, and `CL2PA` (`BOOTSUBR.txt:1441`) turns the
   letter into a processor address: A–H give 0–7 on a Sigma, and on a 560 the letter's position in
   `X560CUCL` is used.
2. **`C/LL/DC ASSIGN OK (YES/NO)`** (`BOOTSUBR.txt:466`): confirms the card reader (`CNDD`), the listing printer (`LLNDD`,
   with a flag for a low-speed printer) and each swap device (`M:SWAPD`). With no OC (I flag clear), or no reply,
   the answer is YES. The whole reply word is compared, so only exactly `YES` or `NO` is accepted;
   anything else gets ` ??` and is read again. On NO, each device is prompted with its current name
   from `DCT16` (`DCINP`, `:778`; e.g. `CRA03 => `). The reply is `SA` to keep the current device, or a
   channel letter plus hex digits (`CL2PA`, `FLD`). It updates `DCT1`/`DCT1A`/`DCT1P` and the name in `DCT16`.
   A bad reply gets ` ??`. `VALINP` finds the DCT index by type code, and stops (`B %`) if there isn't one.
3. **Swap device check**, for each swapper (`GETDC1`, `:488`):
   - *Disk pack*: reads the sector headers of every cylinder in the PSA (reserved swap area) and checks
     the addresses. Reports `NO RESPONSE FOR SWAPPER`, `DISC PACK BAD`, `PSA TRACK FLAW` or
     `SWAPPER WRITE PROTECTED`.
   - *RAD* (`GETDC2`, `:527`): reads the sense data and checks the controller model, X'80' (7212) when
     `MB:SWAPS` is 0 and X'56' (7232) otherwise. On a mismatch, or if the SIO fails, it reports
     `SWAPPER NOT  7212` or `7232` (`BADISC`). Then it checks the write-protect bit (`SWAPPER WRITE PROTECTED  YYNDD`).
   - After an error it asks for the swap device address again (`BADCMN` → `DCINP`) and repeats the check.
     During the later copy to disc (`SPECFLG` set), a write-protect error stops the machine instead.
4. Sets the JIT disc address (`DAJ`, sector 6, or sector 2 for a pack; sectors 2–5 are for ALLOCAT's AJIT and JIT),
   the `JX:CMAP` entries and the JIT swap command list, and the map control words for the swapper
   (`S:MAPCW`, `S:ACCW`).
5. Reads the **creation-data record** from tape (`:601`). Builds `SYSVERS` from the low nibbles of
   version characters 2 and 4 and the machine bits: X'4170' for a Sigma 7, plus X'4000' for a Sigma 9 or
   X'8000' for a 560, rotated right 8 bits. Adds the record's line count to `MAXSEG` to get the number of
   patch segments. Prints the record on the LP (P flag) and OC (I flag). Details are in [`tape.md`](tape.md) §1.2.
6. Reads the **XDELTA** head and code into memory at its bias (`DLTBIAS`, `DLTSZ`). If there is an
   OC, prints the sense-switch reminder. The message's command chain includes a 1-byte read, so it waits
   for the operator to press NL:

   | Switch | Effect |
   |---|---|
   | SSW1 | Check-write disc writes |
   | SSW2 | No automatic logon/logoff |
   | SSW3 | Operator recovery on disc boot |
   | SSW4 | System security checking |

7. **Patching:** `SEGPATCH` (`:675`) bumps `SEGNO` and branches into XDELTA (`PACHSTRT`, offset by
   `DLTBIAS`), which applies the tape and card patches. The first entry (`SEGNO` = 0) is for the
   root. After that there is one entry for each piece copied in step 8, so a segment number names a
   piece (data, DCBs or procedure), not a module. XDELTA hands any `:` card to `RECNFG` (BOOTSUBR), which lists it and passes it to
   `RECNFG:1` in RECONFIG (see §6). After the root, `:` cards are rejected once with
   `** ':' COMMAND NOT IN PATCH DECK PROPERLY`. The card protocol is described in [`tape.md`](tape.md) §2.
8. **`SWAPINIT`** (first return from XDELTA):
   - If no `:END` was seen, calls `RECNFG:2` to assume one by default.
   - Writes the JIT to disc at the `DAJ` address. On a RAD that leaves `DISCLOC` at sector 8. On a pack
     it is set to sector 8 explicitly ("ACAT'S DATA BEGINS AT SEC 8").
   - Copies the segments, reading each head record (`GETHEAD`, `PARSHEAD` at `:1064`) and filling in `P:SA`, `P:TCB`,
     `PB:DSZ/DCBSZ/PSZ/PVA/HVA`, `PB:C#`/`PB:DC#` and `PH:DDA`/`PH:PDA`. The shared processors go in
     table slots `MAXOVLY+4` (ALLOCAT), `+3` (GHOST1) and `+2` (FIX), and the overlays in slots
     `MAXOVLY−1` down to 1. So the tape must hold exactly `MAXOVLY`−1 overlays.
   - Each data, DCB and procedure piece goes through `RWDSK` (`:1201`). It reads the piece into the buffer,
     calls `SEGPATCH` so XDELTA can apply that piece's patches, and then writes it to disc. On a pack
     swapper, `SIZCHK` keeps each piece within one cylinder. `PH:DDA` and `PH:PDA` are the disc
     addresses at which the data and procedure pieces start.
   - *Boot under files*: the test is `X'2A'` + `SEGNO` ≤ 0 (`:1091`), which is true only when X'2A' is −1 and
     the piece is ALLOCAT's data (`SEGNO` is still 0 at that point). That data is read back from disc
     (the write command is changed to a read) and patched, and then written back. This keeps the
     existing file-system state instead of overwriting it.
   - Records UMOV's disc address and size (`UMOVSA`, `UMOVSZ`, `UMOV#`). UMOV is recognized by
     `PB:PVA` = `JJITVP+1`.
9. **`RECOV`**: copies the RECOVER overlay and sets `RCVSTART`, `RCVDISC` and `RCVSIZE`. Copies XDELTA to
   disc (`DLTDSC`). Computes the root checksum **`MONCHK`** (sum of `GETHGP`..`TOPROOT`). If
   `PPTABLE` exists, writes an empty one and saves its disc address (`PPTABDSK`, `PPTABDSK2`).
10. **`WRTROOT`**: writes the monitor root to disc in up to three parts: words 0–X'3FFF' (32 pages),
    X'4000'–X'7FFF', and an overflow part from X'8000' up to `MONIRTN`.
    - The first part is written first with clock 3 turned off, so that check-write works while the
      low-memory clock words are changing.
    - The number of parts comes from (`MONIRTN`+X'1FF'−X'4000')/512 − 32. If that is 0 or less, there
      are two parts, the second of 32 pages plus that (non-positive) amount. Otherwise there are three
      parts, and the third holds the rest.
    - Then the second and third parts are written. Their disc addresses go in `DABOOT`/`ROOTSA`.
      `MPPSEEK` is set to the second part's address. The comment says "ALSO WHERE RECOVER OVERLAY
      STARTS": RECOVER is read over X'4000', and after a single-user abort `INITRCVR` reads that part
      back from `MPPSEEK`. `RCVRAD` is set to the relative sector after the last part (`SEEKCVT`), which
      is the start of the dump area. `SEEK4000` is set to the disc address of `RCVRAD`+X'44' sectors
      (`:1320`), which is where X'4000' falls in the dump (`recovery.md` §5).
    - `BOOTIC` is patched so the disc boot stops reading at `MONIRTN` (`:1326`). `STS` under the mask X'2000FFFF'
      sets the third read's byte count to `BA(MONIRTN)` & X'FFFF', which is the bytes from X'8000' to `MONIRTN`.
      It also copies bit 2 of `BA(MONIRTN)`, which is 0, into the flag byte, clearing command chaining (X'20').
      If the root ends at or below X'8000', the same store goes into the second read (`3+BOOTIC`), so the chain
      stops after the second part, which then counts from X'4000'.
    - The first part is written again, from X'5A', so the disc copy includes the patched `BOOTIC`
      and disc addresses.
    - Finally the disc bootstrap **`DBOOT`** is written to sector 0, and the code branches to `GMONEX` (§3).

### Disc I/O and error handling in TBOOT
- **`WDISC`** builds a command list of seeks and writes, rounded to granule boundaries, followed by
  a sense. It then repeats the list as check-write commands (code 5) and retries when they fail.
- **`ERROREC`** is a shared SIO/TIO/TDV driver with per-device recovery (`XITTBL`: tape, card
  reader, disc, printer, check-write). It retries up to 11 times. Messages to the operator:
  `!! INOPERATIVE`, `!! MANUAL MODE`, `!! ERROR. TIO ... TDV ...` and `!! CHECK-WRITE ERROR`. After a
  message it waits for the operator, detecting this by the clock having stopped.

## 5. Disc boot — `DBOOT` (`BOOTSUBR.txt:1751`)

`DBOOT` sits in sector 0 of the swap disc and is assembled to load at X'2A':

1. `RD,0 0` reads the sense switches. If they call for operator recovery, it executes
   **`SCREECH -1`** (the system crash call) to enter recovery.
2. `BOOTENT`: `SIO` on the load device (X'25') with `DCDW`, which seeks to `ROOTSA` and reads the
   first part of the root (16K words) into memory from X'5A'. It then TICs to **`BOOTIC`** in `TABLES`
   (`TABLES.txt:657`), which must be in that first part. `BOOTIC` seeks to `ROOTSA+1` and reads
   X'4000'–X'7FFF', then seeks to `ROOTSA+2` and reads the overflow part at X'8000' (its comment says
   "2K MAX"). `WRTROOT` patched the last read's byte count and cleared its command chain, so the
   reading stops just before `MONIRTN` (§4 step 10).
   - `ROOTSA` (= `DABOOT`, three words: one disc address per part) is at X'35' (`BOOTSUBR.txt:1767`).
     `TABLES.txt:655` says "DEFED IN BOOTSUBR,X'35'", which fits a 2-word `SCREECH` (`XPSD` plus
     `GEN`, `UTS.txt:20`) at X'2C'–X'2D'.
3. Waits for the I/O to finish, then `B *X'5F'`, which is `INITIAL` (`INITIAL.txt:268`).

On a disc boot `MONINIT` asks only for date, time and XDELTA, then reads XDELTA and UMOV
from the swap disc at `GMONEX`.

## 6. `RECONFIG` — boot-time reconfiguration (`RECONFIG.txt`)

Entry vector (`RECONFIG.txt:86`), which *must match `BOOTSUBR`*:

| Entry | Routine | Called |
|---|---|---|
| `RECNFG:0` | `INITL` | From `TBOOT:`. Applies the OC address change and converts DCT addresses. |
| `RECNFG:1` | `PROC:` | For each `:` command read by XDELTA. If assembled with `AUTO=1`, the first one runs the auto-configurator (`AUTOCNFG`). This source sets `AUTO` to 0. |
| `RECNFG:2` | `:ENDFALT` | From `SWAPINIT` when no `:END` was seen. |

Commands (`RECONFIG.txt:269`):

| Command | Effect |
|---|---|
| `:GO` | Accept the hardware addresses on the PO tape as they are. Only `:PART` and `:END` are accepted after it, and `:TYPE` commands are ignored. |
| `:SAVE` | Like `:GO`, but `:TYPE` commands are honored. No device is marked permanently down. |
| `:TYPE type,addr[,addr…]` / `:TYPE type,(prim,alt)…` | Defines a device's type mnemonic, model number and address. `type` is 6 characters: a 2-letter mnemonic (e.g. `CR`) and a 4-hex-digit model number. A pair of addresses means dual-access (primary and alternate path). |
| `:PART [CONT,]addr` | Partitions a device, or with `CONT` a controller. |
| `:REMOVE [CONT,]addr` | Removes a device or controller. |
| `:END` | Ends the reconfiguration and applies it (`DORECNFG`). |

Device addresses are `NDD` (N = channel letter, DD = device number). On a 560 they can also be
`NDD` with N as the cluster/unit, or a 4-hex-digit value.

## 7. Recovery entry

A crash (`SCREECH`), a single-user abort (`SUA`), a `DUMP`, or operator recovery (sense switch 3 at
`DBOOT`) enters `INITRCVR` through `RCVPSD`. For a crash, `INITRCVR` saves X'4000'–X'7FFF' at `SEEK4000`,
reads the RECOVER overlay over it from `RCVDISC`, and branches to `RCVCTL`. `RCVCTL` logs the reason,
dumps memory into the area at `RCVRAD`, saves the system state, and reboots by reading `DBOOT` from
sector 0 and branching to `BOOTENT` with X'2A' set to 0 (or X'00010000' for operator recovery).
`MONINIT` then skips the dialog. The full path is in [`recovery.md`](recovery.md).

## Open questions and oddities

- **UTS/CP-V transition:** modules say `SYSTEM UTS`, but comments call it the "CP-V monitor",
  WRITEMON's banner says `C P - V`, and WRITEMON is catalogued under BPM SYSGEN.
- **"SIGMA 6" message:** `CANTRUN`'s wrong-machine text uses "SIGMA 6" where you'd expect Sigma 7
  (`BOOTSUBR.txt:1692`).
- **Code at location 0 in `DBOOT`:** a small clock/console loop (`START`, `CLOCK`, `INTR` over
  `COCBUF`) is assembled at `LOC 0` after the bootstrap. Its purpose isn't clear yet.
- **Contents of X'2A' during boot:** mostly resolved by GHOST1's `BOOTYPE` table (see the boot-type
  table above). What remains is confirming the `INT` instruction's definition, which is taken from the
  Sigma architecture rather than this source (`recovery.md` §6).
- **The `F` test:** in `MONINIT`, `CI,5 8` / `BANZ %+3` skips the store of −1 when the AND with
  X'08' is non-zero. That reads as if −1 is stored when F is *not* chosen, which contradicts the comment.
  The CC2 meaning of `CI` needs confirming.
- **Overflow part size:** `BOOTIC`'s comment says the overflow part of the root is "2K MAX", but
  `WRTROOT` writes it in whole pages up to `MONIRTN`, with no limit check.
- **`SEEK4000`** (resolved): `RCVRAD`+X'44' is where X'4000' falls in the dump area. `RCVCTL` first
  takes 4 sectors at `RCVRAD` for its recovery buffer, and the core image follows, so X'4000' is at
  4 + X'40' sectors. `INITRCVR` saves X'4000'–X'7FFF' there at the moment of the crash, before
  RECOVER is read over it (`recovery.md` §5).
- `Changes.txt` lists `BLDCB`, `CCIR`, `DSCIO`, `FILLA`, `GETARG`, `LNKTRC`, `PMD`, `RCVTAB` and `TPQ2` as
  having had missing lines restored. None of them are on the main boot path.
