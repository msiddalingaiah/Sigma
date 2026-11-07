# User read and write: from M:READ/M:WRITE to IOQ

How a program's `M:READ`, `M:WRITE`, `M:TYPE`, `M:PRINT` or `M:MESSAGE` becomes an I/O request,
and how it completes. It continues [`cal.md`](cal.md), where a CAL1,1 READ or WRITE reaches
`CAL11N7`, and joins [`io.md`](io.md) at IOQ's DCB entry `QUEUE`. Files, labeled tapes and
symbiont streams branch off on the way, and they are only located here. The path followed is the
one for a **device**, for example the operator's console.

> Source paths are relative to `c00co/`. `IORT.txt` holds the parameter decode and the
> device-independent part (`MSRRDWT`), device reads (`MSRRED`), `IOQUEUE`, the wait (`IOSPIN`,
> `IOCHEK`) and the exits. `WRTD.txt` holds device writes (`MSRWRT`, `MSRTYPE`, `MSRLP`) and
> `M:TYPE`/`M:PRINT`/`M:MESSAGE` (`MSRTYPR`, `MSROCTY`). `COOP.txt` routes a request to IOQ or to
> the symbionts. `IOQ.txt` has `QUEUE`, `FRONTEND` and `REQCOM`.

## Overview

```
CAL1,1 X'10'/X'11' ─► CAL11N7 (IORT.txt:209)          CAL1,2 0/1/2 ─► MSROCTY / MSRTYPR (WRTD)
   DCB not open: default OPEN (overlay)                   M:OC, M:UC or M:LL, TEXTC message,
   │                                                      a 3-word parameter list, write X'11'
   ▼                                                                     │
MSRRDWT1: decode the FPT (error/abnormal addresses, buffer, size, BTD, ECB, flags) ◄──┘
   check the buffer (X'4A'), then by ASN:
   1/2 file: ISEQUB/IOSFILE   2 labeled tape: LTAPE overlay   4 common journal
   3 device: read ─► MSRRED / MSROTHR        write ─► MSRWRT (WRTD.txt:140)
                                                  └─ by device attributes: MSRTAPE, MSRLP,
                                                     MSRTYPE (typewriter), MSROTHR
   ▼
IOQUEUE / IOQUEUE1 (IORT.txt:1407, :1514): monitor-buffer flag, tape waits, earlier error,
   DCB function count + 1 ─► COOP: a device DCB without a stream ─► QUEUE (IOQ.txt:604)
   ▼
QUEUE: DCB ─► FRONTEND (UB:MF, E:IP) ─► IOQ entry (buffer, count, tries, handler function) ─► Q13 ...
   ▼  ... handler, interrupt, cleanup (io.md) ...
REQCOM DCB branch (IOQ.txt:1649): TYC, tries, ARS, function count − 1, monitor buffer back,
   ECB, then E:IC for the user
   ▼
the CAL: no wait ─► MSRWRTX ─► PULLALLEXIT ─► IOSPRTN (cal.md §5)
         wait     ─► IOCHEK1 / IOSPIN: T:IOREG E:IIP until the count is 0 ─► TYC ─► CODE
                     ─► normal, or an error/abnormal code to the user's routine, or MERC
```

## 1. Entries

**CAL1,1 READ (X'10') and WRITE (X'11')** arrive at **`CAL11N7`** (`IORT.txt:209`), "THE FAST CAL
PATH", with the stack opened 8 words for a `PUSHALL`. The comment says every 60 µs added there costs
1% of the machine.

- If the DCB isn't open and the call isn't assign/merge (X'2D'/X'2E'), the DCB is **opened by
  default**: the OPEN overlay, entry 0 (`MSRRDWTA`, `:251`). If that fails, the CAL ends with code
  X'46' (read) or X'47' (write), and OPEN's error code as the subcode (`:271`–`:276`).
- Assign/merge with an open DCB is code X'2E' (`CL11NW`).
- A CAL from monitor code first `REMEMBER`s the overlay (`CL11`).

**M:PRINT, M:TYPE and M:MESSAGE** (CAL1,2 codes 1, 2 and 0) go to **`MSRTYPR`** and **`MSROCTY`**
(`WRTD.txt`):

| CAL | DCB |
|---|---|
| M:MESSAGE | always `M:OC`, the operator's console |
| M:TYPE | `M:OC` for a batch job or ghost; `M:UC`, the user's terminal, for an on-line user (`J:JIT` negative) |
| M:PRINT | the user's `M:LL`, found in the DCB name list; none means the CAL does nothing |

The FPT's parameter is a TEXTC message, a count byte and then the text. `MSRTYPR` checks it
(`CKLIMIT`, abort X'4A'). Then it pushes a parameter list of three words: presence bits `Y3`,
meaning buffer and size; the message address; and the size. It sets the DCB's byte displacement
(BTD) to 1 to skip the count byte, and calls `MSRRDWT` as a WRITE (`SR1` = X'11'). The BTD is put
back afterwards.

## 2. Decoding the parameters (`MSRRDWT1`, `IORT.txt:305`)

The FPT's word 1 holds presence bits, one per optional parameter, followed by flags. `JHKBIT`
(`:393`) shifts the next presence bit out. If it's set, it takes the next parameter word, which
may be indirect, through memory or a register. In order:

| Bit | Parameter | Goes to |
|---|---|---|
| 0 | Error address | `ERO` in the JIT |
| 1 | Abnormal address | `ABO` in the JIT |
| 2 | Buffer address | `BUF` in the DCB |
| 3 | Buffer size (bytes) | `RWS`, and `BLK`. Without it, the DCB's record size `RSZ` |
| 4 | Key address (files only; skipped for a device) | `KAD` |
| 5 | Byte displacement | `BTD` |
| 6 | ECB | `J:RWECB`, through a 4-word block (`ECBINIT`) |
| 7 | Block number (random files only) | the DCB's key buffer |

The flags that follow go into the DCB's `WAT` field. One of them is the WAIT option, which
`CHKWAT` tests later. For a read, `DIR` (direction) is also set, and for a write, `ONWK` (new
key). Before this, a shared keyed file is truncated if other users have written (`:308`–`:339`).

**The buffer check** (`JOSZE2`, `:523`). Every page from `BUF` to the end of the transfer must be
in the user's area, with the right access (`J:JAC`). A read may not land in the monitor root,
unless the user has special JIT access or `J:ASSIGN`. Otherwise the CAL ends with code X'4A'
("ILLEGAL BUFFER ADDRESS").

**Dispatch by assignment** (`ASN`, the low 3 bits; `:368`, `:500`, `:604`):

| ASN | Kind | READ | WRITE |
|---|---|---|---|
| 1 | File | `ISEQUB` | `IOSFILE` |
| 2 | Labeled tape | LTAPE overlay, entry 0 (`RLBT`) | entry 1 (`WLBT`) |
| 3 | Device | `MSRRED` | `MSRWRT` |
| 4 | Common journal | — | `COMJRNL` |

A write with no ASN is code X'44', and a read is X'40'.

## 3. Device write (`MSRWRT`, `WRTD.txt:140`)

1. The function becomes a write (`SR1` = DCB | X'04000000'), and the end-of-operation field is set.
   A zero record size (`BLK`) is a no-op.
2. With FORTRAN conversion (`FCON`), the buffer is converted EBCDIC to BCD first.
3. A DCB with a **stream** (`CLK` byte) belongs to a symbiont, and its attributes come from the
   stream context (`J:USCDX`). A **direct** DCB gets its device with `GETDEV`. 'NO' is a no-op,
   and type X'10' ("ME", the terminal, whose COC handler does its own service) goes to `MSROTHR`.
   Otherwise the attributes come from `TB:FLGS`.
4. By attributes:
   - **output not allowed**: a no-op;
   - **binary to a device that can't take it**: code X'1F';
   - **tape-like**: `MSRTAPE`;
   - **disc-like**: `MSROTHR`;
   - **listing**: `MSRLP` for a printer, `MSRTYPE` for a typewriter (input and output).

**`MSRTYPE`**, the typewriter (`WRTD.txt:713`), takes a monitor buffer (`IOGETBF`, `GMB`) and
builds the line in it:
- **NL** (X'15') first;
- then the user's **ID** from `J:JIT` (low 16 bits), as hex digits with leading zeros dropped, a
  colon and a blank;
- **two tabs** (X'05') if a program is running: neither LOGON nor TEL in control;
- then the user's record, up to 136 bytes in all (`RECTRAN`).

The buffer goes into `QBUF`, and `IOCONT` (`WRTD.txt:694`) queues it (`IOQUEUE`). For `M:OC`, it
goes unmapped around the call. Long records continue in further pieces (`BAPKTC`, two at most).
Then **`BUFX`** clears the DCB's wait bit, so a typewriter write never waits for completion.

**`MSRLP`**, the printer, interprets the carriage-control character (`INTCHAR`, VFC). It either
copies the line into a monitor buffer (`MSRLP34`, `FRMIM`) or, for a symbiont stream, goes through
`IOQUEUE1` to COOP.

## 4. Device read (`MSRRED`, `IORT.txt:675`)

- **The 'C' device** (the job's control-command input) is read into the JIT's `J:CCBUF`, waiting
  for completion (`IOQUEUE`, `IOCHEK1`). A record starting `!` in EBCDIC, or X'482' in binary,
  ends the data: TYC 7, with the buffer kept as full (`CCBEF`) for the next control command. Then
  it moves to the user's buffer (`USRMOV`, `RECTRAN`), and the actual record size is set.
- **Any other device** goes to `MSROTHR` (`REDX`, `:794`), which queues directly into the user's
  buffer (`IOQUEUE1`) and, with FORTRAN conversion, converts after completion.

## 5. Queuing (`IOQUEUE`, `IOQUEUE1`, `IORT.txt:1407`–`:1528`)

1. `IOQUEUE` sets the DCB's **monitor-buffer flag** (`MBG`, `SETMBG`), and `CLRMBG` clears it for
   a read into the user's buffer. Either way the code goes on to `IOQUEUE1`.
2. **Tapes**: wait for a rewind to finish (`CHKREW`, which sleeps on `E:NQW` and is woken by `E:NQR`
   from the tape end action `TAPEA`). Spacing operations (FSF, BSF, REW, WEOF) go out as no-wait
   requests (`NEWQNW`) with that end action.
3. **An earlier error**: if no I/O is outstanding on the DCB and its completion type (TYC) hasn't
   been checked (`EGV`), a TYC of 8, or anything above 8 except X'B', ends the job. A non-ghost
   gets run status X'02', and everyone gets the `CODE` table's abort code (`IOQUEUE4`).
4. **Count the function** (`MTB,1 *R6,R1` at `BAFCN`, the DCB's `FCN` byte), then go to **COOP**.

**COOP** (`COOP.txt:156`) sends a DCB that isn't a device assignment, or a device DCB without a
stream, straight to IOQ's **`QUEUE`**. A stream DCB is spooled through the symbiont files instead.
That's the "cooperative" for batch card readers and printers, which isn't covered here.

## 6. IOQ for a DCB (`QUEUE`, `IOQ.txt:604`; `FRONTEND`, `:183`)

**`QUEUE`** (no end action; `QUEUE1` takes one in R9):

1. A function count of 0 means nothing to do.
2. **Find the device.** A file DCB takes its DCT index from the file's disc address. A COC
   terminal DCB (`DSI` X'90xx') goes to `COCIO`. A device DCB takes the DCT index from `DSI`, and
   an unresolved operational label there is `SUA X'32'`. A DCB above the monitor is translated to
   its physical address through the user's map (`JX:CMAP`).
3. **`FRONTEND`**. For a mapped user (one with a system ID), it adds the I/O "ding" `SL:IOTA` to
   the user's `J:CTIME`. Then it checks the user's outstanding I/O (`UB:MF`) against `SL:BXMF`
   (batch) or `SL:OXMF` (on-line); ghosts have no limit. At the limit, it reports **`E:IP`**
   through `T:REG`. The scheduler parks the user in `SIOMF` until the count drops (`STIOC`,
   [`scheduler.md`](scheduler.md) §7), and `QUEUE` starts again. Otherwise `UB:MF` + 1. For the
   monitor (no system ID) this is skipped. Then **`GETQ`** takes an entry with the user's priority
   (`UB:PRIO`).
4. **Build the entry**:
   - an ECB, if any, adds one to its I/O count;
   - the buffer is `QBUF` as a byte address, plus the BTD;
   - the count is the record size `BLK` (0 means 32K);
   - the tries are the DCB's `NRA`;
   - the monitor-buffer flag comes from `MBG`;
   - the handler function comes from the DCB's code through **`TYPCOR`**, by device type. A
     typewriter (`TYCOR`) is 0 for reads and 1 for writes, a printer 1 or 3, tapes have their own
     table, and so on.

   Then the code merges with `NEWQ` at `Q13` ([`io.md`](io.md) §2).

**`REQCOM`** for a DCB request (`:1649`–`:1690`):
1. Error TYC 8 becomes 9 for a write.
2. For a device: copy the tries left into the DCB, and set or clear its BIN bit from `DCT5`.
3. Keep the **highest TYC** so far in the DCB, and decrement its function count `FCN`.
4. With an ECB, update the 4-word block's TYC.
5. Clear `EGV` (the TYC is now unchecked).
6. Store the **actual record size** `ARS` (count − residual, summing the commands for data
   chaining).
7. For a write that used a **monitor buffer**, return it to `MPOOL` (`SCREECH X'19'` if it's
   outside the pool).
8. For a diagnostic DCB, store the device status in it.

Then it frees the entry, runs the end action, posts a completed ECB, and reports **`E:IC`** for the
request's user with R1 = the DCB (`RC29`, `:1829`). Waiting users are woken by `STIOC`, which
compares that DCB with the one they are waiting on ([`scheduler.md`](scheduler.md) §7). User X'FF'
(a no-wait request, `NEWQNW`) gets no report.

## 7. Waiting and the result (`IORT.txt:831`–`:1065`, `:1094`–`:1213`)

**`MSREXIT`**, the exit most CALs take. **`CHKWAT`** asks for a wait if the user has an error or
abnormal address, or set the WAIT flag (`WAT`). Without one, the CAL exits at once (`MSRWRTX`), and
the I/O completes later. With one:

1. **`IOSPIN`** (`:1201`). While the DCB has functions outstanding (`FCN` & X'7F'), it does
   `XPSD` to `REGIPSD`, which is **`T:IOREG`** with `E:IIP` ([`scheduler.md`](scheduler.md) §§3, 7).
   The user sleeps in `SIOW`, with this DCB flagged as the one waited on, until `E:IC` for it.
   Then it loops.
2. **`CKEGV`**: if the TYC hasn't been checked, mark it checked (`EGV`) and turn it into a code
   with the **`CODE`** table (`:1168`):

   | TYC | Meaning | Code |
   |---|---|---|
   | 0, 1 | normal | 0 |
   | 2 | lost data | X'07' |
   | 3 | beginning of tape | X'1D' |
   | 4 | beginning of file | X'04' |
   | 5 | end of reel | X'1C' |
   | 6 | end of data | X'05' |
   | 7 | end of file | X'06' |
   | 8 | read error | X'41' |
   | 9 | write error | X'45' |
   | X'A' | public device/private set saturated | X'57' |
   | X'D' | ended by PURGE | X'33' |
   | X'E' | line hung up, read pending | X'5B' |
   | X'F' | line hung up, write incomplete | X'5C' |
   | X'13' | write error after end of tape | X'4F' |

3. **A non-zero code** (`MSR012`, `:896`). Codes with X'C0' set are **errors**, and the rest are
   abnormal. The code goes into byte 0 of `SR3` with the DCB address. The address comes from
   `*D2,R4`. From `IOCHEK3` (`:893`), R4 is the JIT, so this is `ERO` or `ABO`. From `MSR01EXIT`
   (`:598`), R4 is the DCB, so this is its `ERA` or `ABA` (see [`devopen.md`](devopen.md) §4).
   If the user gave an error (or abnormal) address, `SR1` gets it, and `IOSPRTN` sends the user there with SR3 in R10
   ([`cal.md`](cal.md) §5). If not, **`MERC`** (`:1557`) handles it. An abnormal code is
   ignored, and the CAL ends normally (`BCR,KC MERC1`). An error records the abort code and `ERO`,
   and sets run status X'02' (X'01' if the code's top bit is set). The job then ends at the exit
   path ([`scheduler.md`](scheduler.md) §5).

**`PULLALLEXIT`** (`:971`), every CAL's last step:
1. Post the ECB if all its I/O is done, or mark "CAL complete" so IOQ posts it.
2. Unwind the stack, through the shared-update markers if any.
3. Clear `ERO`/`ABO`, unless they hold a code.
4. If this user was the open/close user (`OPNCLSUS`), release it and wake the next waiter on
   `R:OCR` (`E:NOCR`).

## 8. Operator input: `M:KEYIN` (`MSRKEYIN`, `UCAL.txt:1157`)

CAL1,2 code 4 goes to the MISOV overlay's `MSRKEY` ([`cal.md`](cal.md) §3), which "TYPES A
MESSAGE ON OC DEVICE AND READS A RESPONSE FROM THE OPERATOR". This is how a ghost asks the
operator something.

**The FPT.** Word 1 (`R7` in the CAL) holds presence bits for four parameters, and a flag X'10',
"OC ONLY" (`CI,6 X'10'`). The parameters are read with `CHKBIT1`/`CHKBIT`:

| Bit | Parameter |
|---|---|
| 0 | The message, a TEXTC (always taken) |
| 1 | The reply buffer (word address) |
| 2 | The reply size in bytes; 60 if absent |
| 3 | An ECB |

Both addresses must be in the user's area (`CKLIMIT`), or the user is aborted with code X'4A'.

1. **Type the message**: with OC ONLY through `MSROCTY`, always to the console. Otherwise through
   `MSRTYPR`, to the console for a batch job or ghost and to the terminal (`M:UC`) for an on-line
   user (§1).
2. **The DCB for the reply**: for an on-line user `M:UC`. Otherwise a copy of the `M:OC` DCB,
   pushed onto the user's stack (`LM,SR4 M:OC` / `PSM,SR4 TSTACK`), so that each ghost reads
   through a DCB of its own.
3. **Set it up**: BTD 1, so the reply goes from byte 1 of the buffer; `QBUF` = the reply buffer;
   the size into `BLK`; the function count to 1; and a read (clears X'00800000' in word 0).
4. **Read**: `QUEUE` (§6), with `FRONTEND`'s count against the user, then `IOSPIN`. The ghost
   sleeps in I/O wait until the read completes.
5. **Return**: the actual record size (`ARS`) goes into **byte 0** of the reply buffer. So the
   reply is a TEXTC: length, then the text. An ECB is reset, and the CAL exits through `MSRWRTX`
   (no error codes).

**Several ghosts asking at once.** Each `M:KEYIN` is an ordinary IOQ read on the console
([`io.md`](io.md) §2), so they queue:
- the requests are served one at a time, by priority, and among equal priorities in arrival order;
- a second ghost's question is only typed after the first one's read has completed;
- each ghost waits on its own DCB, while the rest of the system runs.

The operator can't pick which question to answer: the next line typed goes to the read at the
head of the queue.

**No answer.** The console read with editing has a 60-second timeout ([`io.md`](io.md) §4). At
the deadline, `CLOCKIO` halts it, and `KBTCU` puts an NL in the buffer ([`io.md`](io.md) §§6, 8). So the ghost gets an
empty reply and the queue moves on.

## What a first translation needs

| Piece | Source | Notes |
|---|---|---|
| M:TYPE, M:MESSAGE | `MSRTYPR`, `MSROCTY` | The TEXTC message; `M:OC` for a ghost |
| Parameter decode | `MSRRDWT1`, `JHKBIT` | Error and abnormal addresses, buffer, size, BTD, WAIT; no keys, ECBs or files |
| Device write | `MSRWRT`, `MSRTYPE`, `IOCONT`, `BUFX` | The typewriter. Printer and tape as `NotTranslated` |
| Queuing | `IOQUEUE`, `IOQUEUE1`, COOP's direct branch | The earlier-error check, `FCN` + 1 |
| IOQ | `QUEUE`, `FRONTEND`, `REQCOM` DCB branch | On `io.IOSystem`, which already has `Q13` onward for the console; `E:IC` to the scheduler |
| Wait and result | `CHKWAT`, `IOSPIN`, `CODE`, `MSR012`, `MERC` | `E:IIP`/`E:IC` through the scheduler, a printer fault as a write error |

The Python translation is in `python/uts/cal.py`, with `QUEUE` and `REQCOM`'s DCB branch in
`python/uts/io.py`. It covers M:TYPE, M:MESSAGE, M:PRINT (no `M:LL` only), and M:WRITE and
M:CHECK on `M:OC`, through the real console IOQ. Reads, files, streams, terminals, printers and
ECBs raise `NotTranslated`. `M:KEYIN` (§8) is translated for ghosts and batch: the message, the
ghost's own copy of `M:OC`, the read through `FRONTEND`/`QUEUE` and `IOSPIN`, and the TEXTC reply.

## Open questions

- **Where WAIT is in the FPT** (resolved): `JHKBIT` and `SKIPBLK` shift word 1 left 16 places
  in all before storing it into `WAT` under the mask X'00100400', which makes WAIT word 1's bit
  27 (X'10'). The `M:READ` and `M:WRITE` procedures are in `BPM.txt` (:591-:604) and agree: their
  keys from bit 0 are ERR, ABN, BUF, SIZE, KEY, BTD, ECB, BLOCK, INT, WFPT; then `M:READ`'s AUTO
  (24), REV (26), WAIT (27), ULBL (28), and `M:WRITE`'s ONEWKEY (25), NEWKEY (26), WAIT (27).
  The translation had assumed NEWKEY X'08' and ONEWKEY X'04', so EDIT's new lines were refused
  (X'13').
- **A DCB's TYC is only ever raised.** `REQCOM` keeps the highest TYC (`:1679`), and the only
  store that resets it found so far is `SETTYC`, on the read paths. So after a write error, every
  later check of that DCB would report it again, unless something not read yet resets it.
- **Typewriter writes never wait**, because `BUFX` clears the wait bit. So an error on an `M:OC`
  write is only seen by the next request on the DCB (`IOQUEUE`'s earlier-error check).
- **`ID` digits**: the ID is `J:JIT` & X'FFFF'. Whether that is the user's system ID (`UH:ID`), and
  what a ghost's is, hasn't been traced.
- **Not read:** the file paths (`ISEQUB`, `IOSFILE`), labeled tape, the symbiont side of COOP,
  `COCIO` (terminals), `FRMIM`/`INTCHAR` (printer images), ECBs (`ECBINIT`, `ECBPOST`), and
  `MSRTAPE`.
