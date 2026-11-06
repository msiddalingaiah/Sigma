# Project status

Where the documentation and the Python translation stand, what is still open, and what the rest
of the source contains. Last updated 2026-11-05.

## Documented

| Document | Covers |
|---|---|
| [`boot.md`](boot.md) | The boot process: `INITIAL`, `MONINIT`, the tape install `TBOOT:`, the disc boot `DBOOT`, the page pool, RECONFIG's boot-time entries, and the boot types in X'2A' |
| [`tape.md`](tape.md) | The SYSGEN system tape (WRITEMON): record layout, head records, patch segment names, and how XDELTA reads the patch cards |
| [`recovery.md`](recovery.md) | Crash recovery: `SCREECH`, single-user abort and dump, RECOVER (`RCVCTL`), the dump area, the reboot, and X'2A' through a recovery |
| [`keyin.md`](keyin.md) | Operator key-ins: the console interrupt, the control task, device key-ins, the KEYIN ghost and its command table, and the `ZAP` shutdown |
| [`io.md`](io.md) | Monitor I/O: IOQ queueing and scheduling, the handlers (typewriter, line printer), cleanup, completion, timeouts and device messages |
| [`files.md`](files.md) | The file system's structure: directories, the FIT and its VLPs, consecutive, keyed and random files, the keyed master index and its entries, key lookup and insertion, the pyramid rebuilt at close; consecutive files in depth (segments and control words, writing, reading, deleting, FIX1's check); random files (create, read and write by granule, release); OPEN's checks (password, account lists, synonyms, expiration); deleting a file (CLOSE with REL, the directory entry, releasing granules); the CFU; granule allocation (the HGP bit maps, the stacks, ALLOCAT, `STUQFAC`) |
| [`python-programs.md`](python-programs.md) | Python programs as ghost jobs, started with `GJOB`: the design, and a table of every departure from CP-V |
| [`rdwr.md`](rdwr.md) | User read and write: the parameter decode, device writes (the typewriter), `IOQUEUE`, COOP, IOQ's `QUEUE`/`FRONTEND`/`REQCOM` for a DCB, the wait and the completion codes |
| [`cal.md`](cal.md) | CAL dispatch: the trap entry, decoding the FPT, the CAL1,1–CAL1,9 tables, the DCB check, monitor overlays (`T:OVERLAY` and `E:AP`), and the returns |
| [`scheduler.md`](scheduler.md) | `SCHED`: user states and queues, events and the transition tables, priorities, resources, the exit path (quanta, preemption, DO lists), log-on, `T:SE` and the idle loop, and the `T:SS` swap scheduler |
| [`dcb.md`](dcb.md) | The DCB in the user's memory: its words and bits (from the system DCB procedure and how the code tests each field), the VLP list, and how the translation reads and writes it |
| [`coc.md`](coc.md) | COC, the terminal handler: the line tables, input and the immediate characters, BREAK, echo, reads (`COCIO`, `COCRD`) and writes (`COCWR`), lines coming ready and dropping |
| [`online.md`](online.md) | On-line users: from a BREAK through the scheduler's `LOGON`, the LOGON processor and `STEP041` to TEL, and `OFF`; the TCP terminals and the LOGON/TEL stand-ins |
| [`labtape.md`](labtape.md) | Labeled tapes: the sentinels, LBLT's blocks of keyed records, split and unblocked records, sequential keys; checked against two real tape images |
| [`loadmodule.md`](loadmodule.md) | Load modules: `HEAD`, `TREE` and the section records FETCH reads, and how the step starts the program; checked against three real load modules |
| [`devopen.md`](devopen.md) | Opening a device DCB: OPEN's device option, `OPENDEV`'s reading of word 1 (operational label or name), the assignment tables by kind of user and P2OPL's defaults, device allocation and its errors |
| [`jit.md`](jit.md) | The JIT page in user memory: its layout from `JIT.txt`'s template (`M:UC` and `M:XX` inside it, `J:CCBUF`, the kind of user), and what the translation builds there |
| [`trapxcon.md`](trapxcon.md) | Trap and exit control: `M:TRAP`'s flags and masks in `J:USENT` and the PSD, `M:XCON` and `J:EXTENT`, and how the step exit runs the exit-control routine (`XCONSEE`, `XCONSETUP`, the environment pushed on the user's stack) |
| [`pages.md`](pages.md) | Memory: the areas and their limits in the JIT, what FETCH sets (`LINKLIMS`, `OLAYLIM`), and the page calls `M:GP`, `M:GCP`, `M:GVP`, `M:FP`, `M:FCP`, `M:FVP`, `M:GL` (`MMNR`, `T:GVPI`, `T:RVPI`) |
| [`overlays.md`](overlays.md) | Overlays: the tree's entries and links, FETCH's `M:SGLD`, and `M:SEGLD` (`MSEGLD`, `SEGLD`: the flags, the memory set for a segment, the path read to the root) |
| [`interpreter.md`](interpreter.md) | A design for a user-mode instruction interpreter: the user's machine state, decoding and effective addresses, the instruction groups from simh's Sigma simulator, traps and the hand-off to the Python monitor, memory, and what programs to run |

Every claim and line reference in them was checked against the `.txt` sources. Anything not
settled is listed under each document's **Open questions**.

## Translated (`python/uts`)

A hand translation on a small machine model with stubbed devices, not an instruction emulator.
368 tests, all passing (`python -m pytest`). `python/README.md` lists each module and every
simplification; the top-level `README.md` has the commands.

| Area | Module | Status |
|---|---|---|
| System tape | `writemon.py` | Writes a tape from an invented `M:MON` (modules and sizes in `config.py`, contents zero) |
| Tape install | `tboot.py`, `xdelta.py`, `reconfig.py` | Runs end to end. Patch cards are placed and read, but storing a patch (XDELTA's evaluator) and RECONFIG `:` commands stop with `NotTranslated` |
| Disc boot | `bootsubr.py`, `initial.py` | Reads back what the install wrote and comes up to `T:SE` |
| Recovery | `recovery.py` | Crash and operator recovery, the dump, the silent shutdown path, the reboot. SUA and DUMP stop |
| Key-ins | `keyin.py` | `DATE`, `TIME`, `ON`, `ONB`, `OFF`, `ZAP` (with its abort loop), `PREF`, `OBON`, `OBOF`, `SYST`, `SEND`, errors and device key-ins. KEYIN runs as a ghost through `T:GJOBSTRT`. Other commands are logged as not translated |
| I/O | `io.py` | IOQ for monitor requests, the console and printer handlers, injectable printer faults |
| Scheduler | `sched.py` | States, events and transition tables, priorities, resources, the exit path, log-on, `T:SE` and idle, and `T:SS` on page counts. Users are generator stand-ins; swaps complete at once. `INITIAL` builds it and starts ALLOCAT and GHOST1, and the key-ins run through it (`ghosts.py`) |
| Keyed files | `files.py`, `cal.py` | Index blocks and entries byte-exact, insertion with block splits, records in data granules, the pyramid (search, build at close), FIX1's checks; account and file directories, OPEN/CLOSE with CFUs; M:OPEN/M:CLOSE/M:DELREC and keyed M:READ/M:WRITE from stand-in programs, through the OPEN and CLOSE overlays |
| Granule allocation | `files.py`, `ghosts.py`, `sched.py` | The HGP bit map, the pack stack, GRAN's get/release and thresholds, ALLOCAT as a ghost that fills and empties the stack, committed by `STUQFAC` |
| Random files | `files.py`, `cal.py` | Create (FIT granule and a run), read/write by granule number, release |
| OPEN's checks | `files.py`, `cal.py`, `pyprog.py` | `SECCHK`'s password and account lists, creating only in one's own account, no deleting of another's file opened IN; a ghost's account is its `GJOB` account. Not synonyms |
| Deleting files | `files.py`, `cal.py` | `M:CLOSE` with REL: the directory entry, then the granules. Keyed record deletes as `DEL` does them, the pyramid's null first keys, and the continuation-key backup in the search (a bug found by random testing) |
| Consecutive files | `files.py`, `cal.py` | Byte-exact granules and segments, forward reads, writes, the cut at a mid-file write, `M:DELREC`, FIX1's `CHKCON`; `cpv.open(..., org="consec")`. No backward reads or positioning CALs |
| Disc images | `image.py` | `--disc PATH` keeps the swap and public discs in a host file, so files and the installed monitor survive between runs. Not a translation: see `python-programs.md` |
| Python ghost jobs | `keyin.py` (`GJOB`), `pyprog.py` | `GJOB NAME` runs a Python program from the file system as a ghost; its `cpv` calls are real CALs, including `M:KEYIN` to ask the operator. Not a translation: see `python-programs.md` |
| On-line users | `coc.py`, `online.py`, `terminals.py` | `--terminals N`: telnet to localhost, a BREAK or connection logs on, LOGON and TEL stand-ins, `STEP041`/`STEP10`; COC's input, echo, reads and writes on `M:UC`, BREAK and hang-up. LOGON, TEL and the TCP server aren't translations: see `online.md` |
| Load modules: FETCH (STPNR.txt) | `fetch.py`, `pyprog.py`, `online.py` | A load module's `HEAD` and `TREE` checked (A6 codes), the root's sections into memory, `J:START`, the TCB in R0, the DCB table; started from TEL or `GJOB` on the interpreter. SLIP from the UTIL tape loads and runs to its first CAL, an `M:OPEN` of the device DCB `M:SI`. No overlays. See `loadmodule.md` |
| Device DCBs: OPEN (OPN.txt `MSROPN`, OPND.txt `OPENDEV`, P2OPL.txt's defaults) | `devopen.py`, `cal.py` | A device DCB in memory opened by label or name for batch, ghost and on-line users: the terminal (COC), the console, or the null device; the default OPEN on a read or write. SLIP's `M:SI` on `CR` fails (X'49') and its error routine runs. No symbiont streams or device allocation. See `devopen.md` |
| OPEN's merge of the FPT (OPN.txt `CHKASN`, `MSROPN09`, `MSROPN10`–`98B`; IOD.txt `SETDCB`) | `cal.py` | The FPT's assignment over the DCB's, its parameters and VLPs merged into a DCB in memory, `M:SETDCB`. UPDATE of a missing file is X'03' (OPNF). See `devopen.md` §4 |
| Card reader and punch (**not a translation**) | `cards.py` | `--reader DECK.txt`, `--punch FILE.txt`: card devices whose media are host files; allocated to one job at a time. Departure: `JB:MAX` isn't modeled, so on-line users may have them. SLIP reads its control card from the reader and runs into its own deck checks. See `devopen.md` |
| The JIT page (JIT.txt) | `jit.py`, `pyprog.py` | Built in the user's memory at X'8C00' when a load module starts: the template plus the user's fields, the command line in `J:CCBUF`; `M:UC` at its real address X'8C2C'. Not kept in step afterwards. See `jit.md` |
| Trap and exit control (ALTCP.txt `MTRAP`, TRAPC.txt `MXCON`, STPNR.txt `XCONSEE`/`XCONSETUP`, SCHED.txt `T:UTSXTS`) | `cal.py`, `interp.py`, `online.py` | `M:TRAP`'s flags in `J:USENT` and its masks in the PSD (PERMIT FX turns on overflow traps); `M:XCON`; every exit runs the exit-control routine, with the environment on the user's stack. TEL's `TIC` is reset while a program runs. Delivering a trap to the trap entry stops as not translated. BACKUP, RESTORE and GAC now end through their exit routines; LEMUR, STATS, JOURNAL and SYMCON prompt and read. See `trapxcon.md` |
| The page calls (MMNR.txt; MM.txt `T:GVPI`/`T:RVPI` reduced; STPNR.txt `LINKLIMS`/`OLAYLIM`) | `cal.py`, `fetch.py`, `jit.py` | FETCH sets the memory limits in the JIT; `M:GP`, `M:GCP`, `M:GVP`, `M:FP`, `M:FCP`, `M:FVP`, `M:GL` with their checks, pointers, SR1/SR2 and CC1. Memory isn't paged: a page got is only recorded. No size limits or waits for core. `M:CVM` and `M:SMPRT` not translated. BATCH, LINK, LYNX, SPLIST, SPOOL and UNSPOOL now answer; PCL gets its pages and then ends without reading. See `pages.md` |
| Overlays (STPNR.txt FETCH's `M:SGLD`; ALTCP.txt `MSEGLD`; SEGLD.txt) | `fetch.py`, `cal.py`, `jit.py` | Overlaid load modules are fetched (the root) and `M:SEGLD` reads segments and their path to the root, with MEMSET's pages. Also `M:ASSOC`/`M:DISASSOC` (no shared processors: CC1), `M:TS`, a terminal record's NL and `M:UC`'s ARS in memory, empty protection VLPs not taken as lists, and the account written to a DCB's VLP at OPEN. EDIT, SORT, AP, FORT start; EDIT reads and understands commands. See `overlays.md` |
| CP-V's JIT layout | `jit.py` | The tape's processors address a JIT with 4 more words before `TSTACK` than JIT.txt's: `J:CCBUF` at 204, `M:UC` at 44, `M:XX` at 234 (`jit.md` §1). With it, SHOW reports the user's limits and privileges, PCL reaches its `<` prompt, and EDIT's `BUILD` takes a file's lines |
| Labeled tapes (**not a translation**: the restore) | `labtape.py` | `--restore TAPE.tap`: a CP-V labeled tape image's files into the file system, in the tape's account; consecutive files for sequential keys, keyed otherwise. See `labtape.md` |
| Read/write | `cal.py`, `io.py` | M:TYPE/M:MESSAGE/M:PRINT, M:WRITE and M:CHECK to `M:OC` through the console IOQ, with `FRONTEND`, `REQCOM`'s DCB branch, `E:IC`, the wait and the error codes |
| CAL dispatch | `cal.py` | The trap, FPT decode, the CAL1,1–CAL1,9 tables, overlays through the scheduler (`E:AP`), and the returns. Translated: M:WAIT, M:TIME, M:PC, `T:CLRERR`, and the exits. GHOST1 leaves with M:EXIT to FILL |

What runs today:

```
python -m uts --tape --reboot ...            install from tape, then boot from the disc it wrote
python -m uts -i --console --replies 06/15/76 13:45 N
                                             boot, then type key-ins at the ! prompt
python -m uts ... --crash 2E-03 | --oprec    crash or operator recovery of the running system
python -m uts ... --print TEXT --lp-fault notop --keyins "LPA02,R"
                                             a failing printer answered by the operator
python -m uts --sched                        the scheduler demo: ghosts, swapping, I/O, shutdown
python -m uts --disc sys.json.gz ...         keep the discs (monitor and files) between runs
```

## The biggest open points

- **The `INT` instruction** (resolved 2026-11-04): simh's Sigma simulator confirms the definition
  used in `recovery.md` §6 ([`interpreter.md`](interpreter.md) §1). Every boot type is consistent
  with GHOST1's `BOOTYPE` table. What remains open is its prediction that a shutdown (`ZAP`) ends
  by branching to the tape install (`recovery.md`, open questions).
- **No linked `M:MON`.** Without the real load module, the module list, sizes, table addresses and
  SYSGEN values in `python/uts/config.py` are invented, though consistent with what the code assumes.
- **Assumed values:** the ghost table and `MING` (slots 1-3 KEYIN, ALLOCAT, RBBAT; `MING` = 4
  GHOST1), and that FILL, ANLZ, ERR:FIL and MOOSE log off, so `S:CUIS` comes out as 2 after the
  start-up, which decides when `ZAP` shuts down. Also the dump-area size `RCVRDSZ`, which GHOST1's
  `SYSMAK` really sets.
- **Scheduler puzzles** (`scheduler.md`, Open questions): as read, the `GIVEUP8` return after a
  failed swap loops, `XFDFF` clears `RMAHOLD` rather than `CALINT`, and the back links of resource
  sub-queues are never set.
- **Not yet read:** the `F` test in `MONINIT`, XDELTA's patch-expression evaluator, RECONFIG's `:`
  commands, dual-access I/O, and the smaller items listed in each document.

## The rest of the source

The large subsystems not yet documented, by size (`c00co`, approximate line counts):

| Subsystem | Main modules | Lines | What it is |
|---|---|---|---|
| Swapper, memory, CAL services | `SWAPPER`, `MM`, `IORT`, `UCAL`, `STPNR` | ~10k | The rest of the engine behind `T:SE`: swapping, pages, and the CAL services themselves (`SCHED`/`SSDAT` are in `scheduler.md`; the CAL dispatch through `ENTRY`, `CALPROC`, `ALTCP` and `T$OV` is in `cal.md`) |
| File system | `OPNF`, `CLS`, `RDF`, `WRTF`, `RDWRT`, `GRAN`/`GRANSUB`, `ALLYCAT`/`ALLYHD`, `FIX1`, `PURGE`, `FRES` | ~25k | Directories, granule allocation (the ALLOCAT ghost), open/close/read/write, start-up repair |
| Terminals and commands | `COC`, `TEL`, `LOGON`, `CCI0`/`CCIR`, `ASSGR`, `STEP`/`STPNR` | ~20k | On-line users and their command language; batch control cards and job steps |
| Symbionts and batch | `RBBATM`, `INSYM`/`OUTSYM`, `BATCH1`/`2`, `SDEVICE`, `HASPIO`, `2780IO` | ~15k | Spooling, remote batch |
| Loading and linking | `LINK`, `LOADR`/`LDR`, `SEGLD`, `EVL`, `FIN` | ~12k | Building and loading programs |
| SYSGEN | `PS1`, `P2CCI`, `UBCHAN`, `PASS3`, `DEF`, `SYSMAK0/1` | ~15k | Generating a system (WRITEMON is done) |
| Debugging and crash analysis | `DELTA`, `XDLT`, `ANALZ` + `ANALZO1`–`3`, `DEVDMP` | ~25k | User and monitor debuggers; ANALZ reads the recovery dump |
| Transaction processing | `TPQ1`/`2`, `TPG`, `TPC`/`TPCSIM`, `TP$…` | ~15k | The TP subsystem |
| System management | `SUPER1`–`3`, `CONMAIN`/`CONSUB`, `STATS`, `PART`/`SYSCN`, `ACCTSUM`, `ELLA…` | ~25k | Authorization, system control, performance, partitioning, accounting |
| Processors | `EDIT`, `FSAVE`/`BACKUP`, `PCL`, `TIC` | ~30k | User-level programs. `TIC` (10.8k lines) hasn't been identified yet |

`c00si` holds 22 smaller files: utilities, other copies of `COC` and `FILL`, and a word-guessing
game.

**The GHOST1 start-up** was surveyed but not written up. It is the starter ghost `INITIAL` starts:
it opens its output, sets up memory for read-ahead, then by boot type runs `RECOVER2` (restore
after recovery or a disc boot) or `PASS0` (process the patch file after a tape boot), calls `SYSMAK`
(which also sets `RCVRDSZ`), starts terminals and batch, writes the start-up error-log entry,
sets `BOOTFLG` to 0, starts the system ghosts (RBBAT, ANLZ after a recovery, RVGHOST, ERR:FIL,
FREPORT, MOOSE), and turns itself into FILL (`GHOST1D.txt:97`–`:376`). The end of it, from
`BOOTFLG` on, is in `keyin.md` §4 and runs as a stand-in (`python/uts/ghosts.py`).

## Where to go next

Everything translated so far is the monitor's own control flow. Past `T:SE` the system mostly runs
*programs* (ghosts, TEL, processors). Hand-translating each program has no end, so there are two
ways on:

1. **More monitor mechanisms, with ghosts as small Python stand-ins.** This would cover the scheduler's
   states and queues, starting and ending users (`T:GJOBSTRT`, `T:DELUS`), CAL dispatch, and
   swapping through the I/O system. It would let KEYIN run as a real ghost and GHOST1's start-up run
   in order. Done (2026-11-03): `docs/scheduler.md`, its translation `python/uts/sched.py`, and
   its connection to the boot. `INITIAL` starts ALLOCAT and GHOST1 through `T:GJOBSTRT`, GHOST1's
   stand-in finishes the start-up, KEYIN runs as a ghost, and `ZAP` aborts users and shuts down
   through `Scheduler.idle`. CAL dispatch (`docs/cal.md`, `python/uts/cal.py`) is done too.
   **Next options:**
   - **more of the file system**: synonyms (CLOSE's part), `PURGE`, and FIX1's HGP
     reconstruction. Consecutive and random files, deleting files, granule allocation and OPEN's
     checks are done (2026-11-03/04);
   - more of read/write: device reads (`MSRRED`/`MSROTHR`), the printer (`MSRLP`);
   - `docs/swapper.md` (put off by choice);
   - `docs/ghost1.md` for the whole start-up.
2. **A Sigma instruction emulator** for the whole system, which would also need the monitor
   assembled. **Decided against (2026-11-02): too much work.** In its place (2026-11-04): a
   **user-mode interpreter** ([`interpreter.md`](interpreter.md)). It runs real user programs, with
   every trap and CAL going to the Python monitor. The instruction semantics come from simh's Sigma
   simulator, test programs from the Python port of AP, and real load modules from Sigma tapes.
   Phase 1 runs (2026-11-04): the integer core (`python/uts/cpu.py`), a small assembler for
   test programs, and assembled programs as `GJOB` ghosts whose CALs go to `cal.py`. Their own
   DCBs in memory work for file I/O ([`dcb.md`](dcb.md)). Next: CP-V's user trap handling,
   floating point, and real load modules.

For documentation alone, GHOST1 (`docs/ghost1.md`), the file system, and ANALZ are the other
self-contained pieces worth writing up.
