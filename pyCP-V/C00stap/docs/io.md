# Monitor I/O: IOQ and the device handlers

How the running monitor does I/O: a request is queued, scheduled on its channel, started by the
device's handler, finished by an I/O interrupt, checked by the handler, and completed with an end
action. The device-error and operator-response side of it is also covered here; the key-ins
themselves (`YYNDD,C/R/E`) are in [`keyin.md`](keyin.md) §3.

> Source paths are relative to `c00co/`. `IOQ.txt` is the queue manager and scheduler, BPM
> `M:IOQS` (catalog 704879). `HANDLERS.txt` holds the typewriter (operator console), card reader,
> line printer and disc handlers. The boot path doesn't use any of this: `TBOOT:` and `DBOOT` drive
> the hardware directly (`ERROREC`, see [`boot.md`](boot.md)).

## Overview

```
caller ── NEWQ (registers) or QUEUE (DCB) ──► FRONTEND / GETQ: take a free IOQ entry
                                                   │
                         link into the channel queue (CIT1/CIT2), by priority
                                                   │
                                   DRIVEIO / FORCEIO (DSERV, IOSCHED)
                                                   │ device free, request startable
                                                   ▼
                     STARTIO ─► handler pre-processor (DCT8) ─► COMLIST builds the
                                command list from the handler's DOT ─► IOSST ─► IOSTRT: SIO
                                                   │
                                     ... device runs, I/O interrupt ...
                                                   ▼
                     IOINT: AIO, find the device, save AIO/TIO/TDV status, cleanup pending
                                                   │
                     CLEANUP ─► handler post-processor (DCT9): flags, TYC, message
                                                   │
                     IOSCU ─┬─ done ──────────► REQCOM: end action / DCB / user, free entry
                            ├─ retry, follow-on ─► next function step, back to IOSCHED
                            └─ operator needed ─► key-in pending, message ('MANUAL', ...)
```

## 1. The tables

**IOQ entries** (one per request, chained; free entries hang off `QFREE`):

| Field | Contents |
|---|---|
| `IOQ1`, `IOQ2` | Back and forward links in the channel queue (free chain uses `IOQ2`) |
| `IOQ3` | Request switches: X'80' busy, X'20' monitor buffer used, access key (dual access) |
| `IOQ4`, `IOQ5` | Function code, and the current function step (an index into the handler's DOT) |
| `IOQ6` | DCB address and function, 0 for a `NEWQ` request |
| `IOQ7` | DCT index of the device |
| `IOQ8`, `IOQ9` | Buffer byte address (with data-chain and command-chain flags), byte count |
| `IOQ10`, `IOQ11` | Maximum tries and tries left |
| `IOQ12` | Seek address (converted by `DSCCVT`) |
| `IOQ13` | End-action address and information (doubleword) |
| `IOQ14` | Priority (lower value = more urgent; X'FF' is the lowest) |
| `IOQ15` | User number, 0 for the monitor |
| `IOQ16` | Event control block (ECB) address, if any |

**Per device (DCT)**, the fields IOQ uses:

| Field | Contents |
|---|---|
| `DCT1` | Device address |
| `DCT2` | Channel (CIT) index |
| `DCT3` | Switches 1: X'08' SIO failed, X'10' timed out, and the partitioned flag |
| `DCT5` | Switches 2: X'80' busy, X'40' cleanup pending, X'20' inter-operation, X'10' data transfer, X'08' key-in pending, X'04' control task, X'02' manual, X'01' binary mode |
| `DCT6` | IOQ index of the request the device is working on |
| `DCT7`, `DCT8`, `DCT9` | Command-list address, handler pre-processor, handler post-processor |
| `DCT10` | Activity counter, used to detect re-entry |
| `DCT11`, `DCT18` | I/O deadline (`IOCLOCK` value), and the timeout increment |
| `DCT12`, `DCT13`, `DCT21` | AIO status, TDV status (doubleword; also the handler flags while a key-in is pending), TIO status |
| `DCT14`, `DCT15` | Links in the chain of devices with I/O in progress |
| `DCT17` | Retry and follow-on function steps for the current operation |

**Per channel (CIT)**: `CIT1`/`CIT2` head and tail of the request queue, `CIT3` the subchannel
busy and hold flags (X'C0' busy, X'30' held), `CIT5`/`CIT6` the requests holding subchannels.

## 2. Queueing a request (`IOQ.txt:105`–`:418`)

**`NEWQ`** is the monitor's entry. The request is in registers:

| Register | Contents |
|---|---|
| R12 | Function code, priority, number of tries, DCT index (8,8,8,8) |
| R13 | Data-chain and command-chain flags, buffer byte address (1,1,6,24) |
| R14 | Byte count |
| R15 | Seek address |
| R0 | Trigger flag and end-action address |
| R1 | End-action information |

It returns to the instruction after the call if the device is partitioned out (unless the caller
is the diagnostic user, `DID`), and one further on otherwise. **`QUEUE`/`QUEUE1`** take a DCB
instead and convert its function code with the `TYPCOR` tables (`IOQ.txt:745`); this is the
path for user `M:READ`/`M:WRITE`.

1. **`FRONTEND`** (`:183`): for a mapped user, counts the I/O and enforces the user's limit of
   requests in progress (`UB:MF` against `SL:BXMF` or `SL:OXMF`), blocking the user if needed.
   The monitor skips this.
2. **`GETQ`**: takes the first free entry from `QFREE` and stores priority, DCT index and user
   number. With no free entry it forces I/O on every device (`FORCEIO`) and tries again.
3. **`Q13`** fills in the entry: function code and step, buffer, count, seek address (`DSCCVT`),
   end action, tries.
4. **Linking** (`Q15`–`Q30`): the entry goes into its channel's queue in priority order. Among
   requests of equal priority for the same disc, lower cylinder numbers go first.
5. **`Q50`**: calls **`DRIVEIO`** with the caller's priority, then returns.

## 3. Scheduling (`DRIVEIO`, `IOQ.txt:801`)

`DRIVEIO` uses the current job's priority (`CJOB`), `DRIVEIO1` one in R0, and `FORCEIO`
X'FF'. Background callers are treated as `FORCEIO`.

- **`DSERV`** checks the device first: if it is busy or has a key-in pending, `CLOCKIO` checks for
  a timeout (§8); if a cleanup is pending, `CLEANUP` runs (§6).
- **`IOSCHED`** then scans the channel queue from the head. A request is started if its subchannels
  are available (`SELECTAB`, for dual-access devices) and its device is free (`REQSERV`): a
  device with a key-in pending or busy is skipped, one in inter-operation continues with its
  waiting request, and one with a cleanup pending is cleaned up.
- With `DEFER` assembled, a request whose priority is below the scheduler call's is left for the
  control task (`DEFER1`/`DEFER2`).

## 4. Starting the I/O

**`STARTIO`** (`IOQ.txt:1113`) calls the device's handler pre-processor (`DCT8`), unless the
request supplies its own command list.

**The handler** chooses a command list from its **DOT** (device operation table) by the request's
current function step (`IOQ5`). Each DOT entry is four bytes (`:DOT`, `HANDLERS.txt:79`):

| Byte | Contents |
|---|---|
| 0 | Offset of the command-list description |
| 1 | Timeout increment, in 5-second units (0 = no limit) |
| 2 | Function step to use for a retry |
| 3 | Function step to use for a follow-on operation |

For the operator console (`KBTIO`, `HANDLERS.txt:130`):

| Step | Operation | Timeout | Retry | Follow-on | Commands |
|---|---|---|---|---|---|
| 0 | Read with editing | 60 s | 4 | 5 | `RDTYE` |
| 1 | Write | 20 s | 0 | 0 | `WRBNC` |
| 2 | Write with device name | 20 s | 0 | 0 | `WRCR`, `WRTYDC`, `WRBNC` |
| 3 | Read without editing | 60 s | 0 | 0 | `RDBNC` |
| 4 | Read with editing, retry | 60 s | 4 | 5 | `WRNLC`, `RDTYE` |
| 5 | Write NL | 5 s | 0 | 0 | `WRNLNC` |
| 6 | Write device name, tabbed | 20 s | 0 | 0 | `WRCR3T`, `WRTYDC`, `WRBNC` |

The 0s are never used: `KBTCU` asks for a retry or follow-on only after the two reads with editing
(steps 0 and 4).

For the line printer and card reader (`DOTCR`, `HANDLERS.txt:282`), each with a 5-second timeout,
no follow-on, and a retry that repeats the same step: 0 read cards binary, 1 print without format,
2 read cards automatic, 3 print with format, 4 format.
`PRTOUT` first checks for a top-of-form character (X'F1') on a printer already at top of form, and
then suppresses the upspace.

**`COMLIST`** (`HANDLERS.txt:314`) builds the command doublewords from templates (`:CDW`,
`HANDLERS.txt:907`). Each template's function byte says what to fill in (`CLTV`):

| Code | Fill-in |
|---|---|
| 0 | Nothing, store as is |
| 1 | The seek address in `IOQ12` |
| 2 | The request's buffer and byte count, or a data chain |
| 3 | A device name: the `DCT16` entry, 8 bytes, of the DCT index in `IOQ12` |
| 4 | Call back into the handler |

The flag bytes are `FC` (X'2E', command chain) and `FNC` (X'1E', no chain). The orders used are 1
write, 2 read, 3 format or seek, 4 sense, 5 write binary, 6 read binary, and 134 (X'86') read
typewriter with control. `COMLIST` ends at **`IOSST`**, which takes the timeout, retry and
follow-on steps from the DOT entry.

**`IOSTRT`** (`IOQ.txt:1143`) then:

1. Checks that nothing re-entered (`DCT10`) and that the channel is free.
2. Saves the timeout increment and the retry and follow-on steps (`DCT18`, `DCT17`).
3. Issues **`SIO`**. A rejection goes to **`IOREJECT`** (`:1338`): it sets the SIO-failed bit in
   `DCT3` and makes the device cleanup pending, so the handler sees the failure at once.
4. Puts the device on the active chain (`DCT14`). If the device is in **manual** mode, it sets the
   manual flag (`DCT5` X'02'), a 15-second timeout, and the `MANUAL` message.
5. Sets the deadline (`DCT11` = `IOCLOCK` + increment), marks the device busy with data transfer and
   the subchannel busy, and links the request to the device (`DCT6`).
6. Types any message (`MSGOUT`) and goes back to the scheduler.

## 5. The I/O interrupt (`IOINT`, `IOQ.txt:1358`)

1. Saves the registers and does **`AIO`** to find out which device interrupted. An
   unrecognised one is counted (`UNEXP`).
2. Looks the address up in the active chain, then in the whole DCT, and takes it off the chain.
3. If the device wasn't busy: a pre-empted device's own interrupt routine is called; a
   device-end from a tape drive starts **AVR** through the control task (code 2); otherwise an
   error is logged.
4. If it was busy: saves the AIO status (`DCT12`), sets **cleanup pending** instead of busy, and
   saves the TIO and TDV status (`DCT21`, `DCT13`). It releases the subchannel.
5. Clears the I/O interrupt level and calls `DRIVEIO` for the device, which runs the cleanup and
   starts the next request.

## 6. Cleanup and the handler's verdict

**`CLEANUP1`** (`IOQ.txt:1546`) calls the handler post-processor (`DCT9`). It returns in R12 a
**completion type** (TYC, byte 3) and flags, and in R13 a message (0 = none):

| R12 bit | Meaning |
|---|---|
| X'8000' | Retry |
| X'4000' | Follow-on operation |
| X'2000' | Inter-operation (the device is kept for this request) |
| X'1000' | Key-in pending, normal |
| X'0800' | Key-in pending, special: `C` (continue) not allowed |
| X'0400' | Keep the channel held |

| TYC | Meaning |
|---|---|
| 1 | Normal |
| 2 | Lost data (incorrect length with no bytes left) |
| 6 | End of data (`!EOD`) |
| 8 | Error |
| 9 | Write error (set by `REQCOM` for a DCB) |

**`IOSERCK`** (`HANDLERS.txt:444`) is the common error check most handlers call first:

| Condition | Message | R12 |
|---|---|---|
| SIO failed (`DCT3` X'08') | `NOT OPERATIONAL` | X'2800': inter-operation, key-in, no continue |
| Timed out (`DCT3` X'10') | `TIMED OUT` | X'3000': inter-operation, key-in |
| Bad status (AIO or TDV error bits, `GENSTAT` mask) | `ERROR` (logged with `REC:ERR`) | X'C008': retry, follow-on, TYC 8 |
| Write lock violation, or a user command list | — | TYC 8, no retry |
| Otherwise | — | TYC 1, or 2 for lost data |

**The console post-processor `KBTCU`** (`HANDLERS.txt:86`) doesn't call `IOSERCK`, so the console
never asks the operator about its own errors. It turns the console alarm on after a
timeout or SIO failure and off otherwise. For a read with editing it scans the characters read:
an X'08' (end of message) means retry; an NL followed by `!EOD` gives TYC 6; a timeout puts an NL in
the buffer; a line that filled the buffer without an NL gets a follow-on to type an NL
(X'6000'). **The printer post-processor `PRTCU`** (`HANDLERS.txt:269`) uses `IOSERCK`; on an error
with a buffer or code-disc parity bit (X'C000') it asks for a key-in with `CODE DISC ERR`, otherwise
it retries.

**`IOSCU`** (`IOQ.txt:1562`) acts on the verdict:

- **No flags**: the request is complete, `REQCOM` (§7).
- **Key-in** (`IOKEYIN`/`SETKEYIN`): the device becomes **key-in pending** (`DCT5` X'08'),
  the flags are kept in `DCT13` for the key-in, and a 30-second deadline is set. The operator answers
  with `YYNDD,C`, `R` or `E` (`keyin.md` §3).
- **Retry**: the request's tries left (`IOQ11`) go down by one; at zero it completes with TYC 8
  (`REQERR`). Otherwise the retry step becomes the next function step.
- **Follow-on**: the follow-on step becomes the next function step.
- The message, if any, is typed (`MSGOUT`), and the scheduler runs again.

## 7. Completion (`REQCOM`, `IOQ.txt:1649`)

For a **DCB** request it records the tries left, the TYC (the highest so far), the actual record
size, releases a monitor buffer used for a user write, decrements the DCB's function count, and
posts the ECB if there is one. For a **`NEWQ`** request it sets up the end action's registers:

| Register | Contents |
|---|---|
| R12 | TYC (byte 0) and residual byte count |
| R13, R14 | TDV status |
| R10, R11 | End-action information and address |
| R6 | Buffer word address |

It unlinks the entry from the channel queue, returns it to `QFREE`, calls the **end action** if
there is one (`TP30` is the end action of the key-in read, `keyin.md` §2), and reports I/O
complete (`E:IC`) to a waiting user.

## 8. Timeouts (`CLOCKIO`, `IOQ.txt:938`)

When `DSERV` finds a busy or key-in-pending device past its deadline, and its timeout increment
isn't 0:

- **Manual last time**: if still manual, the `MANUAL` message is typed again; if now automatic, a
  new deadline is set for the I/O in progress.
- **Key-in pending**: `PLEASE RESPOND` is typed, with a new deadline 50 seconds on (`TYPERSP`).
- **Busy with data transfer**: the I/O is halted (`HIO`), the timed-out bit is set (`DCT3`
  X'10'), and `INTSIM` makes the device cleanup pending, so the handler reports `TIMED OUT`.

## 9. Messages to the operator

`MSGOUT` (`IOQ.txt:2067`) types a message with the device's name in front, through `OCWRITE1`
with function `Y06` (console step 6, write device name tabbed). The messages (`IOQ.txt:2085`) are
`MANUAL`, `ERROR`, `TIMED OUT`, `NOT OPERATIONAL`, `WRITE PROTECTED`, `PLEASE RESPOND`,
`CODE DISC ERR`, `REQ RETRY` and `INCONSISTENT STATUS`.

## What a first translation needs

| Piece | Source | Notes |
|---|---|---|
| Entries, `QFREE`, channel queue | `NEWQ`, `GETQ`, `Q13`–`Q30` | Monitor requests only, no `FRONTEND` |
| Scheduler | `DRIVEIO`, `DSERV`, `IOSCHED`, `REQSERV` | Single access only |
| Start | `STARTIO`, `COMLIST`, `IOSST`, `IOSTRT`, `IOREJECT` | Command lists as data; `SIO` to the device stubs |
| Interrupt | `IOINT` | The stub completes the operation and raises the interrupt |
| Cleanup and completion | `CLEANUP1`, `IOSCU`, `SETKEYIN`, `REQCOM` | End actions as Python callables |
| Timeouts | `CLOCKIO` | Driven by a simulated `IOCLOCK` |
| Handlers | `KBTIO`/`KBTCU`, `PRTOUT`/`PRTCU`, `IOSERCK` | Console and printer |

**The layout of a device message.** `OCQUEUE` and `MSGOUT` put the DCT index of the device to name
in the request's seek-address field (`LW,R15 R7`), which is where `CLTV` code 3 takes it from. `CR`
and `CR3T` (`HANDLERS.txt:1186`) are the same word, X'15050505': step 2 writes 1 byte of it (NL), and
step 6 writes all 4 (NL and three tabs, X'05' being HT in EBCDIC). Then come the 8 bytes of
`DCT16`, and then the message. So a `MSGOUT` message reads NL, three tabs, the name, and for example
` NOT OPERATIONAL`.

**`PRE%CU`** (`HANDLERS.txt:1176`), where `IOSERCK` goes after an SIO failure or a timeout, goes
straight to `IOSCU` for any request that isn't the swapper's. The handler's own post-processing is
skipped, and the key-in flags and message stand. For a swapper request (priority `SWAP%PRI`) it
asks for a retry instead (X'C000'), and doesn't count it.

The Python translation is `python/uts/io.py`.

## Open questions
- **Dual access** (`SELECTAB`, `ASSIGNSC`, `ACCHECK`) is described only in outline.
