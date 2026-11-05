# uts: a runnable Python translation of the UTS monitor

A hand translation of parts of the monitor in `../c00co` into Python: the system tape
(WRITEMON) and its install (`TBOOT:`), the disc boot, crash recovery, and operator
key-ins up to a `ZAP` shutdown. It runs on a small machine model with stubbed devices.
What the original code does is in `../docs/`: `boot.md`, `tape.md`, `recovery.md`,
`keyin.md`, `io.md` and `scheduler.md`.

## Running

Setup (Anaconda environment `p3.13`), commands, options and examples are in the
[top-level README](../README.md#running-the-python-translation). In short, from this
directory:

```
python -m uts -i            # answer the prompts yourself
python -m pytest
```

## What's translated

| Source | Python | Status |
|---|---|---|
| WRITEMON (UTMBPMBT.txt:47) | `writemon.writemon` | Builds the tape: `MTBOOT`, root pages, creation-data record, XDELTA, segment heads and pieces, and patch cards placed as `RPATCH` places them. The module contents are invented (`config.default_modules`) and zero. |
| `MTBOOT` (UTMBPMBT.txt:802) | `bootsubr.mtboot` | Reads the root records into memory and branches to `INITIAL`. |
| `DBOOT` (BOOTSUBR.txt:1751) | `bootsubr.dboot` | Sense-switch check, then reads the root back from `ROOTSA` in sector 0, following `BOOTIC`'s patched counts. |
| `INITIAL` (INITIAL.txt:49) | `initial.initial` | Traps, `LMA` write locks, `BOOTSBAND`, `SYSVERS`, interrupt enables, then `T:SE`. It builds the scheduler (`ghosts.boot_scheduler`) and starts ALLOCAT and GHOST1 with `T:GJOBSTRT`. |
| `MONINIT` (BOOTSUBR.txt:107) | `bootsubr.moninit` | Machine type, memory probe, option/RESDF/date/time/XDELTA dialog. |
| `TBOOT:` (BOOTSUBR.txt:462) | `tboot.tboot` | Device assignment dialog, RAD swapper check, creation record (`SYSVERS`, `MAXSEG`), XDELTA load, `SWAPINIT` segment copy into the overlay tables, `RECOV`, `WRTROOT`, `DBOOT` to sector 0. |
| `PACHSTRT` (XDLT.txt:3238) | `xdelta.BootPatcher` | The card protocol only. Evaluating and storing a patch, or a `#` card, raises `NotTranslated`. |
| RECONFIG `INITL`, `:ENDFALT`; `RECNFG`, `CL2PA` | `reconfig` | DCT address conversion and the default `:END`. Any `:` command raises `NotTranslated` (even a lone `:END` takes the untranslated `RECNF` path). |
| `GMONEX`, `FIXPPUT`, `PUTRT` | `bootsubr.gmonex` … | Page pool built from `MX:PPUT` chains. `PUTRT`'s recovery-time read isn't done yet. |
| `RECOVER0`, `RCV1` (INITRCVR.txt:134, :321) | `recovery.screech` | Decodes the `SCREECH` word, saves X'4000'–X'7FFF' at `SEEK4000`, reads RECOVER over it. SUA and DUMP raise `NotTranslated`. |
| `RCVCTL` (RCVCTL.txt:93), `RCVDMP`, `INCRDA` | `recovery.rcvctl` … | Reason message, X'2A' flag, core dump into the `RCVRAD` area (`COMMRAD` layout), recovery buffer, reboot through `BOOTENT`. The system-specific saves (users, symbionts, error log, TP, COC) are skipped. |
| `OCINT`, `CTRIG`, `CTIOP`, `TP20`, `TP30`–`TP33`, `TP50`, `OCQUEUE` (IOQ.txt) | `keyin.OperatorConsole` | Console interrupt, the control-task stack, the `!` prompt and read (a real console read with `TP30` as its end action), device key-ins (`YYNDD,C/R/E`) answering devices that are really key-in pending, and the canned messages, all through IOQ. `TP50` starts KEYIN as a ghost with `T:GJOBSTRT` (`LATER` if it can't). After the control task, `T:SE` runs it. |
| KEYIN (KEYN.txt) | `keyin.OperatorConsole.keyin`, `keyin.Fields` | The field parser, `KITBL` dispatch, `KEYERR`, and `DATE`/`D`, `TIME`/`T`, `ON`, `ONB`, `OFF`, `PREF`, `OBON`, `OBOF`, `SYST`, `SEND` (`EH?` without COC), and `ZAP`. After each key-in the scheduler's idle check (`SCHED.txt:1065`) runs: after `ZAP` it executes `SCREECH X'404'`, a shutdown through recovery. Other commands are logged as not translated. |
| IOQ (IOQ.txt): `NEWQ`, `DRIVEIO`/`IOSCHED`, `STARTIO`/`IOSTRT`/`IOREJECT`, `IOINT`, `CLEANUP1`/`IOSCU`, `REQCOM`, `CLOCKIO`, `MSGOUT` | `io.IOSystem` | Monitor requests on single-access devices, one channel per device. Retries, follow-ons, key-in pending, timeouts, and the device messages. |
| Typewriter and line-printer handlers (HANDLERS.txt): `KBTIO`/`KBTCU`, `PRTOUT`/`PRTCU`, `IOSERCK`, `PRE%CU` | `io.ConsoleHandler`, `io.PrinterHandler` | The DOT tables, command lists, and the post-processors' verdicts. The hardware is `io.ConsoleUnit` and `io.PrinterUnit`, which can be made to fail. |
| SCHED (SCHED.txt), with SSDAT's tables | `sched.Scheduler` | States, queues and the transition tables built from the `ESTS`/`RESOURCE` declarations (`SCREECH 02` for a bad state and event). Event reporting with the priority increments and insertion, the special transitions, resources (`T:RES`, `T:REL`, `T:UQR`, `OPNUNBLOCK`, `STUQFAC`), the exit path (DO list, ABRT/ERR/YC/BRK, the swap quantum, quantum end, preemption), log-on and `ADD1`, `T:SE` with the idle check and idle counters, and `T:SS` on page counts. On its own tables, with stand-in programs as users (below). `python -m uts --sched` runs the demo. |
| `T:GJOBSTRT` (T$OV.txt:386) | `sched.Scheduler.t_gjobstrt` | Name lookup in `S:GJOBTBL`, wake (`E:WU`) or "running", no new names while `BOOTFLG` is set, reserved slots below `MING`, `ADDGJOB`, `ADD1`, and the condition codes. |
| System ghosts | `ghosts` | Stand-ins: ALLOCAT and RBBAT sleep; GHOST1 follows the end of its start-up (`BOOTFLG` = 0, RBBAT, ANLZ after a recovery, ERR:FIL, MOOSE, becomes FILL) and ends. They run when the system is operated (`OperatorConsole.start`, the key-in session). |
| CAL dispatch: `CAL1P`, `T:CTRAPM` (ENTRY.txt), `CAL1P11`, `CAL11M`, the CAL1,1/1,2 tables, `IOSPRTN` (CALPROC.txt), `CALCK`, `CAL13`–`CAL18`, CAL1,9, `OUT`, `CALBAD` (ALTCP.txt), `T:OVERLAY`, `T:REMEMBER` (T$OV.txt) | `cal.CalProcessor` | The FPT and CAL1 go into the user's word memory and are decoded with indirect, index and `EXU` chains. The tables are data. An overlay not in core waits on `E:AP` and comes in through `T:SS`. Translated routines: M:WAIT (`T:WAIT`), M:TIME (TIM.txt), M:PC (`T:STPMT`), `T:CLRERR`, and M:EXIT/M:ERR/M:XXX to hooks. GHOST1 ends with a real `CAL1,9 1`, and a `T:EXIT` stand-in starts FILL. |
| User read/write (IORT.txt, WRTD.txt, IOQ.txt `QUEUE`/`FRONTEND`/`REQCOM`) | `cal.CalProcessor` (`msrrdwt1` …), `io.IOSystem.queue` | M:TYPE, M:MESSAGE, M:PRINT, and M:WRITE and M:CHECK on a device. The parameter decode, `MSRWRT`, `MSRTYPE` (NL, the user's ID, the record), `IOQUEUE` (the earlier-error check, `FCN`), `FRONTEND` (the ding, `UB:MF`, `E:IP`), `REQCOM`'s DCB branch with `E:IC`, `IOSPIN` on `E:IIP`, the `CODE` table, `MSR012`/`MERC`, `IOSPRTN`. A ghost's message comes out on the real console IOQ. |
| Keyed files (WRTF.txt `INST`/`COMPLEN`/`INSTN`/`MULCHK`/`ENTKEYUB`, RDF.txt `SETUPUB`/`LOCCODEUB`/`MLCHK`, MUL.txt, CLS.txt `CLSFILD`, FIX1.txt `VALBUF`/`FNDKEY`/`FITCHK`) | `files.KeyedFile`, `files.Disc` | Byte-exact 2048-byte index blocks and entries, and the FIT at word X'1B0'. The room check with the spare bytes, insertion with block overflow (last entry to the next block, or a new block) and the pyramid restriction, slides, packed/split/unblocked records, the search down the pyramid (binary search per level, `KEYVERIF` fallback), level-0 congestion, the pyramid build at close (at most 3 blocks on top, the middle one as top), and FIX1's checks. Also the account and file directories (`files.Directory`), OPEN/CLOSE with CFUs and the FIT (`files.FileSystem`, which can `mount` a disc again from the account directory alone), and EBCDIC keys. |
| File CALs: `M:OPEN`, `M:CLOSE`, `M:DELREC`, `M:READ`/`M:WRITE` on a file DCB (`ISEQUB`, `IOSFILE`, the default OPEN `MSRRDWTA`) | `cal.CalProcessor` (`file_open` …) | Through the overlays OPEN and CLOSE (swapped in by the scheduler), keyed and next-record reads into the user's buffer, KBUF, NEWKEY/ONEWKEY, and the error codes through the error/abnormal routines. A booted system has a file system with the `:SYS` account. |
| `M:KEYIN` (`MSRKEYIN`, UCAL.txt:1157) | `cal.CalProcessor.msrkey` | The message through `MSROCTY`/`MSRTYPR`, a copy of `M:OC` per caller, the console read through `FRONTEND`/`QUEUE` and `IOSPIN`, and the reply as a TEXTC (length in byte 0). With the console script at its end, the reply is empty, as after a timeout. For an on-line user, the message and the reply go through the terminal (`COCIO`). Not with an ECB |
| `GJOB` key-in (`KIGJOB`, KEYN.txt:715) | `keyin.kigjob` | `GJOB NAME[.ACCOUNT]`, the 7-character limit, "DONT START OURSELF", and the three replies. A resource name answers `EH?` |
| Consecutive files (WRTF.txt `SEQ0`, RDF.txt `SEQ0`/`SEQPOS`/`SEQFRD`, DLT.txt `SEQ0`/`SEQ2`–`SEQ9`, FIX1.txt `CHKCON`) | `files.ConsecutiveFile`, `files.Position` | Byte-exact granules: the FIT segment at word 3, blocked/unblocked/continued segments, backspace control words, NAV with its back pointer, the full flag. Forward reads (end of file X'06', lost data X'07'), writes at the end, the cut ("delete forward") when a write comes before the end, `M:DELREC`, and FIX1's `CHKCON` as read. `FileSystem.open` tells keyed from consecutive by the first granule. Through `cal.py` (`seq_read`, `seq_write`) and `cpv.open(..., org="consec")` |
| Deleting files and records (CLS.txt `CLSFIL` with REL, DLT.txt `DELF`/`DEL1`/`DEL`/`REL`/`SEQ3`, MUL.txt `MOVEAKEY`) | `FileSystem.close(release=True)`, `KeyedFile.release`/`delete`, `ConsecutiveFile.release`, `Directory.remove` | `M:CLOSE` with REL deletes a file: its directory entry slid out (unless the file was never entered), then every granule. No release while another user has the file open. A keyed record delete keeps control keys (displacement 0) null, releases full granules at once (with `MTB,3`'s double-release guard) and slides other entries out. The pyramid build keeps null first keys as `MOVEAKEY` does, and the search backs up from a continuation key (`MLSET00`). `cpv`: `close(release=True)` |
| Granule allocation (GRAN.txt `GBG`/`RBG`/`CHKTHRSH`/`GNBG`/`RNBG`, GRANSUB.txt `GETBIT`/`CMNGNG`/`CMNRG`, ALLYCAT.txt `ADJBUFS`, HGPSTK.txt, SCHED.txt `STUQFAC`) | `files.Hgp`, `files.Stack`, `files.Disc`, `ghosts.allocat` | One device's bit map (the last get remembered, runs from the end, dual allocations logged) and the pack stack (128 slots, levels 40/80, thresholds 16/100). Gets pop it and releases push it; a threshold wakes the ALLOCAT ghost, whose fill or emptying stays pending until `E:UQFAC` and `STUQFAC`. The scheduler's buffer 1 is the stack |
| Random files (GRAND.txt, WRTF.txt `RWRAND`, CLS.txt `RELRAND`) | `files.RandomFile`, `cal.rwrand` | The FIT's own granule, a contiguous run from the end of the map, reads and writes by granule number (the key word moves on; X'42' past the end, X'44' cut short), release of the run. `cpv`: `open(..., org="random", size=n)`, `read(gran, size)`, `write(data, gran)` |
| OPEN's checks (OBSE.txt `CHKFLACN`/`SECCHK`, OPNF.txt `OP1`/`OP71`, CLS.txt FIT build and `CLSFIL2M`) | `files.secchk`, `files.protection`, `files.Opener`, `FileSystem.open(who=...)` | The FIT's password (X'03') and account lists (write X'06', read X'05', execute X'14' with the vehicle X'15'), written in CLOSE's order and cut to its room; `SECCHK`'s rules, X'14' on refusal; creating only in one's own account below X'C0'; no release of another's file opened IN below X'C0'. A ghost's account is its `GJOB` account, its privilege 0. Host-side tools (`--file`) aren't checked |
| A user-mode CPU (simh's `sigma_cpu.c`, X11-style license) | `cpu` | Slave-mode instructions: loads/stores, arithmetic with CC and `TR_FIX`, logical, compare, shifts, `CVA`/`CVS`, the stack, `EXU`/branches/`BAL`, `INT`, `ANLZ`, `LAS`, byte strings. Traps as on the machine (privileged X'40', unimplemented X'41', the CALs X'48'–X'4B'). No floating point, decimal or `SF` yet. See `docs/interpreter.md` |
| DCBs in user memory (UTS.txt's DCB definitions and system DCB procedure) | `cal.MemDcb` | A file DCB in an interpreted program's memory, its fields read and written in place, its name, account and protection from its VLPs. See `docs/dcb.md` |
| Interpreted programs (**not a translation**) | `interp`, `asm` | An absolute image in a keyed file, run as a ghost a slice at a time; its CAL1s go to `cal.py` (`CalAt`), other traps end it with a message. `asm` is a small assembler for test programs; `--file host.s=NAME` stores one |
| Python programs as ghost jobs (**not a translation**) | `pyprog` | Programs stored as EDIT-style keyed files, a loader stand-in for the ghost's first step, a thread per program bridged so that each service call is a yield, and the `cpv` library (`type`, `message`, `keyin`, `time`, `wait`, `compute`, `readline`, `prompt`, keyed files with text or binary keys, `line_key`). `--file` imports them. Every departure from CP-V is listed in `docs/python-programs.md` |
| Disc images (**not a translation**) | `image` | `--disc PATH` saves the swap disc (sectors and the attached root variables) and the public disc (granules, the HGP bit map and the stack, account directory address) as gzipped JSON when a run ends, and loads them when the next starts. See `docs/python-programs.md`, "Disc images" |
| COC (COC.txt `COCIP`, `COCIYC`, `COCIXC`, `COCIPBRK`, `COCECHO`, `COCIO`/`COCRD`/`COCWR`, `T:COCHC`, `COCMINT`) | `coc.Coc`, `cal.CalProcessor.cocio` | Per-line input with backspace, rubout, Ctrl-X, Ctrl-Y, ESC and BREAK; echo while a read is pending, type-ahead echoed when it starts; `M:READ`/`M:WRITE`/`M:TYPE` on `M:UC` (one per user) through `COCIO` with `E:CRD`/`E:CIC`, the prompt (`M:PC`), and `M:KEYIN` at the terminal; a ready line logs on (`E:CBK`), a dropped one reports `E:OFF`. No tabs, escape sequences, pacing or time-outs. See `docs/coc.md` |
| The step's end for on-line users (STPNR.txt `STEP041`, `STEP10`) | `online.Online` | LOGON switching to TEL, TEL again after a program, `T:DELUS` when the processor is still LOGON; a BREAK hands the terminal to the command processor (`Scheduler.breaks`, the `BREAK` hook) |
| LOGON and TEL (**not a translation**) | `online` | Stand-ins: LOGON's greeting, `LOGON PLEASE:`, `ID?`/`ACCOUNT?`, three tries; TEL's `!`, `RUN`/`START`/a name, `L`/`LIST`, `COPY fid [TO ME]` (PCL's part), `OFF`, `EH?`. Any account. See `docs/online.md` |
| Terminals over TCP (**not a translation**) | `terminals` | `--terminals N`: a telnet server in character mode on localhost (`--port`, `--bind`), and the real-time loop that drives the scheduler from the wall clock, with operator key-ins from the host console |
| Pack swappers, `SWAPPER` | — | Not translated: swaps are stand-ins that complete at once. |

`crash()` and `operator_recovery()` in `__main__` act on a system that is up: they run the
recovery on the same machine and return the monitor from the reboot. A cold disc boot with
sense switch 3 stops, because `SCREECH -1` needs the hung monitor's `RCVPSD` in memory.

`boot()` disc-boots. Without a `disc` argument it first runs `install()` (a tape boot with
default answers) to produce one, so every disc boot reads a disc that `TBOOT:` wrote.
Both take a `public_disc` (`files.Disc`) for the file system. It stays on the `Machine`, so
the files outlive a recovery or reboot, and `--disc` keeps it between runs.

## Conventions

- **Names:** source symbols keep their spelling, with `:` and `%` turned into `_`
  (`M:FPPH` → `M_FPPH`, `CSED%MACHINE` → `CSED_MACHINE`). Each function's docstring
  gives the label and line it comes from.
- **What lives in memory:** only state whose location matters goes into `Machine.mem`,
  which is word-addressed: X'25', X'26', `BOOTFLG` at X'27', X'2A' and X'2B', plus the
  root, XDELTA and UMOV images the tape and disc carry. Other monitor variables are
  fields on `Monitor`, and page chains are Python lists indexed by page number.
- **Root variables on disc:** the root fields `TBOOT:` sets (`monitor.ROOT_FIELDS`: DCT,
  overlay tables, disc addresses, `SYSVERS`, …) live on `Monitor`, not in memory. `WRTROOT`
  therefore attaches a snapshot of them to the root's first disc sector (`Disc.attached`),
  and `DBOOT` restores it along with the memory words.
- **Self-modifying code** becomes ordinary variables. For example, `BPCH`'s patched
  branch would be a computed call.
- **Configuration:** `config.Sysgen` holds the SYSGEN'd values. The ones taken from
  source are marked. The rest are **invented** but consistent with the layout the code
  assumes, because we don't have a linked `M:MON`.

## Known simplifications

- `MX:PPUT` is assumed to start as sequential links (page *n* → *n*+1). The source only
  zeroes the tail.
- X'2A' holds what the source puts there: the bootstraps' first instructions (`LI,1 n`,
  `RD,0 0`), −1 for the F option, and `RCVCTL`'s recovery flags. `MONINIT` decides with
  `machine.interpret`, which follows the Sigma `INT` definition in `docs/recovery.md` §6
  (confirmed by simh's simulator, `docs/interpreter.md` §1). `F` follows its comment (see the open questions in `docs/boot.md`).
- Disc addresses are relative sector numbers: `DSCCVT`/`SEEKCVT` are identities and the
  cylinder fields (`PB:C#`, `PB:DC#`) stay 0. Only a RAD swapper is handled (`S:DP` = 0),
  with one swapper.
- `WDISC` writes whole granules and compares the read-back as its check-write. `ERROREC`'s
  retries and operator messages aren't modeled, except that `Tape.read_record` skips
  80-byte card records the way `TPREC` does.
- `MTBOOT`'s record holds the record count in word 0 instead of an encoded `LI,1 n`.
- The JIT's `JX:CMAP`, its swap command list and `S:MAPCW`/`S:ACCW` aren't modeled.
- Ghost segment names carry a CSECT digit (0 data, 2 DCBs, 1 procedure). This is traced
  from WRITEMON's `LOOP` for GHOST1 and assumed for ALLOCAT and FIX.
- The patch file XDELTA keeps on the swapper (`MPRFILE`) isn't written.
- The user limits (`SMUIS`, `S:GUAIS`, `S:BUAIS`, `S:OUAIS`) are invented SYSGEN values, and
  `COC` is 0, so the system has no terminals: `ON` and `SEND` answer `EH?`, as the source does.
- The ghost table and `MING` are invented SYSGEN values (`config.Sysgen`): slots 1–3 KEYIN,
  ALLOCAT, RBBAT, and slot `MING` = 4 GHOST1. After the start-up, `S:CUIS` is 2 (ALLOCAT and
  RBBAT) because the stand-ins for FILL, ANLZ, ERR:FIL and MOOSE log off. No on-line or batch
  users exist unless a test starts them, so `ZAP` usually has no one to abort. The scheduler
  counts pages from `M:FPPC` but doesn't touch the monitor's page chains.
- I/O: user DCB requests, ECBs, dual access, the control-task deferral, and the disc, tape and
  card handlers aren't translated. Only the console and line printer are attached to IOQ. Device
  faults are injected through the units (`--lp-fault`).
- Granules: one public device, granule-allocated, PFA only; no PER, cylinders, private packs or
  other devices. A user who would wait on `E:QFAC` for an empty stack gets ALLOCAT's fill at once,
  and `COMBUF` messages (`GNBG`, `RNBG`, a full stack's release) are answered at once. ALLOCAT
  reports its own `E:UQFAC` as it sleeps, in place of the swapper. Disc addresses are granule
  numbers, not sectors with a DCT index.
- Random files: no disc limit (`TMDCRM`), scratch files, private packs or cylinders; transfers
  aren't split by track.
- Deleting: no synonyms or free-sector pool.
- OPEN's checks: no synonyms, special (X'01') names, `*` files, test files or fetch (`J:STAR`);
  a replacing OUT open doesn't check the organization (an existing file is opened as it is).
  `SECCHK` also runs when the file's CFU is already open. An emptied file directory is never removed, as in the source
  (`DELFD` is assembled out).
- Consecutive files: no backward reads, positioning CALs (`M:PFIL`, `M:PRECORD`), read-ahead
  or private-pack volume switching. A DCB's position is a `files.Position` (`DCBCDAM`, `HACMD`'s
  word, `W14`) rather than DCB words, and an existing file's organization sets the DCB's `ORG`.
- Time: `IOCLOCK` counts 5-second units. Nothing advances it by itself; the key-in session moves it
  on by 2 units (10 seconds) before each key-in, which is when timeouts and reminders fire.
- Scheduler (`sched.py`): users are Python generators that yield `Compute`, `Sleep`, `Io`,
  `Report` or `Release`, and run only when the scheduler does a `T:PULLE` for them. Time is in
  clock units (2 ms). Wake-ups and I/O completions come from a timer list, not from translated
  clock or IOQ code. `SWAPIN`/`SWAPOUT` are stand-ins that complete at once, and `T:SS` moves page
  counts, not `MX:PPUT` chains. The DO list is a Python list. Code outside SCHED (`T:TELDELCCI`,
  `SETRNST`, `T:DELUSZAP`, `T:ECCP`, …) goes to hooks; by default the user ends through a
  `T:DELUS` stand-in, which also bumps `S:SEVF` (assumed). The limits (`SL:QUAN`, `SL:QMIN`,
  `SL:SQUAN`, `SL:OPRIO`, …) are invented, with `SL:QUAN` above `SL:SQUAN`, because otherwise no
  executable user could ever be swapped out. The `GIVEUP8` return is translated as intended rather
  than as read, and `XFDFF` clears `RMAHOLD` as the source says (see `docs/scheduler.md`).
- CALs (`cal.py`): stand-ins yield `sched.Cal1`, and the monitor's processing runs as a generator
  on the user's stack until it returns. Not modeled: access protection (`T:IACU`); DCB contents
  (open state, blocking buffers, `AGER`); user trap control (`J:USENT`), so `CALBAD` always aborts;
  and the overlays' mapping. Overlay sizes and processor numbers, and the M:WAIT unit of 1/50
  minute (from TIM's `1MIN` and BACKUP's `MINUTE EQU 50`), are assumptions. A timer stands in for
  CLOCK4's wake-up.
- Read/write: devices only, and only the typewriter (`M:OC`). Not modeled: the buffer access
  check (X'4A'), monitor buffer pools, ECBs, FORTRAN conversion, long records in pieces. The ID
  that `MSRTYPE` types is the user number, and the WAIT flag's position (word 1, X'10') is derived
  from shift counts. Both are assumptions (see `docs/rdwr.md`).
- File CALs: a file DCB's name, account, function (IN/OUT/INOUT/UPDATE) and key length are
  DCB fields (`add_dcb`), as an `!ASSIGN` or the program's DCB would set them; the M:OPEN FPT
  carries only the error and abnormal addresses. The NEWKEY/ONEWKEY flag positions in FPT word 1
  are assumed. No passwords, access accounts, synonyms, expiration, scratch or OPEN NEXT. A new
  file is entered in its directory at close. Directory dual copies aren't kept (their words are
  reserved). On reopen, the next free byte of the records granule isn't known, so the next record
  starts a new data granule.
- Keyed files (`files.py`): a rewrite deletes the old entries and inserts again (no in-place
  `REWRITEUB`). The search doesn't start from the buffered block. Upper levels use level 0's room
  check (MUL's `COMP` not read), and the old pyramid's granules are released, not reused. There
  are no dual copies. The FIT holds only the X'09', X'0C' and X'0D' VLPs.
- Recovery assumes `RCVRDSZ` (set by SYSMAK) is `HIGH`+3 granules. The recovery buffer holds
  only the words `RCVDMP` saves, and the dump to tape (`TAPDMP`) isn't translated.
- After a recovery, the date and time in the rebooted monitor are empty. The source asks
  for neither, and where it gets them from hasn't been traced.
