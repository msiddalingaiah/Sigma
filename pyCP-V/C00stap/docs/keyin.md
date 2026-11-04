# Operator key-ins

How an operator command typed on the operator console (OC) of a running UTS system gets from the
INTERRUPT button to the code that carries it out. This covers the console interrupt, the I/O control
task, the key-in buffer, the device key-ins that IOQ handles itself, and the KEYIN ghost with
its command table.

> Source paths are relative to `c00co/`. Characters are EBCDIC: X'15' is NL, X'5A' is `!`.
> As in the source's comments, a key-in is written here with the `!` prompt the system types, as in
> `!T 14:30`; the operator types only the part after the `!`.

## Overview

```
operator presses INTERRUPT on the OC
   │  console interrupt: XPSD,8 OCPSD at X'5D' (INITIAL.txt:267)
   ▼
OCINT (IOQ.txt:1846) ── CTRIG Y01 ──► IOCTQ (control-task stack)
   │                                      │
   ▼                                      ▼
CTIOP / TP5: pop a control word, switch on its code byte (TPBASE)
   │ code 1
   ▼
TP20: type NL '!' ; queue a 72-byte OC read into KEYINBUF, end action TP30
   │ (the operator types the key-in)
   ▼
TP30 (IOQ.txt:1067):  "YYNDD,C/R/E" for a device that asked? ── yes ──► TP31/TP33: device key-in
   │ no
   │  CTRIG Y03
   ▼
TP50: T:GJOBSTRT 'KEYIN' ── can't ──► "LATER"
   │
   ▼
KEYIN ghost (KEYN.txt:361): parse the first field, look it up in KITBL, run the handler,
                            exit through T:DELUS (the ghost logs itself off)
```

## 1. The console interrupt and the control task

`INITIAL` installs `XPSD,8 OCPSD` as the console interrupt at X'5D' (`INITIAL.txt:267`). The PSD
enters **`OCINT`** (`IOQ.txt:1846`), the console interrupt receiver:

1. Saves registers (`PSM`, `T:SAVE`).
2. If the interrupt wasn't triggered by the control task itself (`CTOC` = 0), this is the
   operator: it pushes control word `Y01` (code 1, "console interrupt") onto the control-task
   stack with **`CTRIG`** (`IOQ.txt:1075`).
3. If the control task is already running (`CTACT`), it re-arms the OC level and returns through
   `T:SSE`. Otherwise it marks the control task active and falls into the control-task processor.

**`CTRIG`** pushes a control word onto `IOCTQ` and sets `CTFLAGS`. Then it triggers the control-task
interrupt level, or, on a system without one (`CTINT` = 0), the OC interrupt itself (`CTOCINT`: `WD X'1700'`,
`CTOC` + 1). Other parts of the monitor use the same call to queue control-task work.

**`CTIOP` / `TP5`** (`IOQ.txt:1871`) pops control words until the stack is empty. Byte 0 of each
word selects an entry in `TPBASE`:

| Code | Entry | Work |
|---|---|---|
| 0 | `TP10` | Device function (deferred cleanup, `FORCEIO`) |
| 1 | `TP20` | Console interrupt: start reading a key-in |
| 2 | `TP40` | AVR (automatic volume recognition), passed to ALLYCAT |
| 3 | `TP50` | Key-in message in the buffer: start the KEYIN ghost |
| 4 | `TP60` | Check all devices (time-outs) |
| 5 | `TP70` | Restart I/O after power fail-safe |

When the stack is empty (`TP90`, `IOQ.txt:1996`), it starts the symbionts if asked to (`SACT`),
clears `CTACT`, and returns through `T:SSE`.

## 2. Reading the key-in (`TP20`, `IOQ.txt:1923`)

`TP20` types `TP25`, a two-byte message of NL and `!`, with `OCWRITE`. It then queues an OC read
(`QUEUE`) of 72 bytes into **`KEYINBUF`**:

- Function, priority, tries and DCT index come from `TP26` (`GEN,8,8,8,8 0,X'F0',15,OCDCT`), in
  `NEWQ`'s R12 layout: function 0 (the console's read with editing), priority X'F0', 15 tries, device
  `OCDCT`.
- The end action is `TP30`, so `TP30` runs when the operator has typed the line.

## 3. Device key-ins (`TP30`–`TP33`, `IOQ.txt:1067`, `:2107`)

When a device needs the operator, the I/O system types its name and a message. Examples are `MANUAL`, `ERROR`,
`TIMED OUT`, `NOT OPERATIONAL`, `WRITE PROTECTED` and `PLEASE RESPOND` (`MSG1`–`MSG9A`, `IOQ.txt:2085`). It marks the device
"key-in pending" (`DCT5` bit X'08'). The operator answers with the device name, a comma, and one letter:

```
!CRA03,C
```

- **Matching** (`TP30`): characters 2–5 of the key-in (`SCD,R8 -24` on the first doubleword) are
  compared with the second word of each `DCT16` entry, which is the device name's last four
  characters (`YNDD`). The first character isn't checked.
- **Syntax** (`TP31`): the next character must be `,`, and the one after it `C`, `R` or `E` (`DEVKEYN`).
  Anything else, or a device with no key-in pending, gets `EH?`. Unlike `KEYERR`, this doesn't push
  another console interrupt, so there is no new `!` prompt.
- **Action** (`TP33`, `KEYDV`): this clears the key-in pending bit and the request's busy bit, then:

  | Letter | Meaning | What `KEYDV` does |
  |---|---|---|
  | `C` | Continue | Completes the request normally (TYC 1), unless the handler doesn't allow continue (flag X'800'), when it is treated as `R` |
  | `R` | Retry | Restarts the I/O (`FORCEIO`) |
  | `E` | Error | Completes the request with an error (TYC 8) |

  For tapes (`DCT4` types 8–10) whose request was a rewind (function 8), the retry count is
  decremented first.

How a device ends up key-in pending, and what `C`, `R` and `E` do to its request, is in
[`io.md`](io.md) §6.

A key-in that doesn't name a device is passed on: `TP30A` pushes control word `Y03`, and `TP50`
starts the KEYIN ghost.

## 4. Starting the KEYIN ghost (`TP50`, `IOQ.txt:1944`)

`TP50` calls **`T:GJOBSTRT`** with the name `KEYIN` (`T$OV.txt:386`). That routine, disabled,
with the default ghost priority `SL:GPRIO` and the `:SYS` account (`T:GJOB` takes another account in
R8–R9):

- **Looks the name up** in the ghost table `S:GJOBTBL` (a doubleword name per slot, from `MAXG`
  down), and checks the account (`S:GJOBACN`).
  - If the slot has no user (`SB:GJOBUN` = 0), it is a pre-established name, which is logged on (`ADDGJOB`).
  - If the ghost is asleep (`SW` or `SQFI`), it is woken with `E:WU` and returns CC = 4.
  - Otherwise it is already running and returns CC = X'A'.
- **A name not in the table** is refused while `BOOTFLG` is non-zero ("NO NO-NAMES IF NOT UP YET").
  Otherwise it takes an empty slot.
- **`ADDGJOB`** (`T$OV.txt:404`). A slot below `MING` is reserved, and its user number is the slot
  number: that user is first pushed onto the head of the `SNULL` queue. Then the head of `SNULL`
  becomes the ghost's user. Its base priority, name and account are stored, `S:GUIS` is counted,
  and `ADD1` adds the user ([`scheduler.md`](scheduler.md) §8). It returns CC = 0 with R4 = the user.
- With no free slot or user, it returns CC = 8 (`GJOB10`).

If the ghost can't be started (CC1 set on return), `TP50` types canned message 3, `LATER`. The key-in
stays in `KEYINBUF` for the ghost to read. INITIAL starts ALLOCAT (slot 2) and the starter ghost
(slot `MING`) the same way (`INITIAL.txt:124`–`:127`). The starter ghost, GHOST1, sets `BOOTFLG` to
0 and starts RBBAT, ANLZ (when byte 0 of X'2A' is 0, as after a recovery), RVGHOST (with a dump
file), ERR:FIL and MOOSE. Then it renames its slot FILL and exits to FILL (`GHOST1D.txt:320`–`:376`).

So running a key-in needs a working scheduler, a free ghost slot, and the file system the load
module comes from.

### Canned OC messages (`OCQUEUE`, `IOQ.txt:2120`)

`OCQUEUE` takes a message code in R1 and an optional DCT index in R7. With an index it writes the
device name in front of the message (`Y02`).

| Code | Message |
|---|---|
| 0, 1, 4, 6, 7 | `EH?` (`OC53`: NL, two blanks, `EH?`, a blank, NL) |
| 2 | `!!AVRERR` |
| 3 | `LATER` (`OC52`: NL, X'05', `LATER`, NL) |
| 5 | ` AVAIL` |
| 8–13 | Symbiont states: `SYMB NOT ACTIVE`, `SYMB ACTIVE`, `SYMB NOT SUSP`, `SYMB NOT AVAIL`, `SYMB SUSPENDED`, `DISC BLOCK BAD` |

A code above the table (`NMSG`) is taken as the address of a message.

## 5. The KEYIN ghost (`KEYN.txt`)

`KEYN` is assembled for UTS (`IF%UTS` = 1), which sets `SYST` and `RBCODE` and clears
`FRGRND`, `CHKPT`, `WAIT`, `INT`, `SWITCH` and `DOFFON`. Its entry is `START%KEYIN` / `KEYIN1`
(`KEYN.txt:361`).

1. If the first byte of `KEYINBUF` is NL (`KCRET` = X'15'), the key-in is empty and the ghost just
   exits.
2. It copies the parameter list `KIPL` to its stack. The list holds the delimiter list, the
   current character position (`KCCP`), the blank-active flag, the buffer address, the field length
   (`KFL`), and a 12-character field buffer (`KPLB`).
3. It reads the first field (`GKIFLD`) and compares its **first four characters** with each entry
   in **`KITBL`** (`KEYINA`), from the last one down. A match branches to the parallel entry in
   **`KIJMPTBL`**. The assembler checks that the two tables are the same length (`KEYN.txt:539`).
4. With no match, `DEVKEYIN` (`KEYN.txt:2066`) treats a field starting with `S` as a symbiont key-in (`SKIN`).
   Anything else is an error.
5. Handlers end at **`KEYINR`**, which branches to `T:DELUS`: "EXIT TO STEP LOGS SELF OFF".

### Fields (`GKIFLD`, `NXKICHR`, `KEYN.txt:227`–`:299`)

- Characters are taken from `KEYINBUF` one at a time. The input ends at NL, or after 72 characters
  (the end-of-buffer code `KEOB` = X'26').
- The delimiters (`KIDL`) are `:` `/` `(` `)` `,` `.` and blank. A field ends at the first
  delimiter, and the delimiter is left in SR1 for the handler to look at.
- Blanks *before* a field are skipped. Once a field has started, a blank ends it (`KFLAGS`, the
  "blank active" flag).
- A field is padded with blanks to 12 characters. An empty field or one longer than 12 characters
  sets CC1, which every caller treats as an error.

Because only four characters are compared, `!TIMEX 14:30` is a `TIME` key-in, and `!DATEFOO 1/2/76`
a `DATE` one.

### Errors (`KEYERR`, `KEYN.txt:313`)

`KEYERR` types canned message 4, `EH?`. It then pushes control word `Y01` with `CTRIG`, which
re-runs `TP20`, so the operator gets a fresh `!` prompt straight away ("TRIGGER ANOTHER COPY OF
KEYIN"). `KEYERR1` does the same with message 3, `LATER`.

## 6. The commands

The UTS assembly of `KITBL` / `KIJMPTBL` (`KEYN.txt:386`, `:465`). "Touches" is what each handler
reads or changes, which decides how much of the system it needs.

| Key-in | Handler | What it does | Touches |
|---|---|---|---|
| `ERSEND` | `ERSEND` | Operator error-log entry | error log |
| `ABORT`, `X` | `KIABORT` | Abort a user or ghost: event `E:ABRT` for the user named by its ID or ghost name | users |
| `DATE`, `D` | `KIDATE` | Set the date: `!D MM/DD/YY` | `DATE`, `DATE+1` |
| `ERROR`, `E` | `KIERROR` | Error event `E:ERR` for a user or ghost | users |
| `START`, `S` | `KISTART` | Start (symbionts and devices) | symbionts |
| `TIME`, `T` | `KITIME` | Set the time: `!T HH:MM` | `TIME` |
| `SYST` | `KEYERR` | Not supported in UTS: always `EH?` | — |
| `MOUNT` | `KIMOUNT` | Tape mount | devices, AVR |
| `INT` | `ENTINT` | Console-break event `E:CBK` for a user | users |
| `ON` | `KIGUP` | Number of on-line users allowed (`S:OUAIS`). `EH?` on a system without COC | `S:OUAIS`, `S:BUAIS`, `S:GUAIS`, `SMUIS` |
| `ONB` | `KIGBUP` | Number of batch users allowed (`S:BUAIS`) | same |
| `OFF` | `KIGDOWN` | Gentle down: no new on-line or batch users. Also `XCPU` on a multiprocessor, and `RBX`. Doesn't shut the system down (see below) | `S:OUAIS`, `S:BUAIS` |
| `ZAP` | `KIFDOWN` | Force down and **shutdown**: `GOODNGT` = −2, aborts every user above the system ghosts (`T:RUE`), then as `OFF` | `GOODNGT`, users |
| `SEND` | `KISEND` | Message to all on-line users (COC buffer `COCMESS`, at most 55 characters), or to one user (`!SEND id,...`). `EH?` without COC | COC |
| `GJOB` | `KIGJOB` | Start a ghost job (below) | ghosts: translated with Python programs as the load modules |
| `DELETE` | `KIDEL` | Delete a symbiont file | symbionts |
| `PRIO` | `KIPRI` | Change a job's priority | symbionts |
| `FORM` | `KFRMCG` | Form change | symbionts, devices |
| `SCPU`, `XCPU` | `KSCPU`, `KXCPU` | Start or stop a slave CPU | multiprocessor |
| `RBSEND`, `RBBDCST`, `RBX`, `RBS`, `RBDISC`, `RBSWITCH`, `RBLOG`, `RBCOM` | `KRB…` | Remote batch | remote batch |
| `SS` | `KISTSY` | Start a symbiont | symbionts |
| `REQUEST` | `KIREQ` | Request a tape drive | devices |
| `DISPLAY` | `KIDIS` (`DISPLAY.txt`) | Displays: `Q`, `NORU`, `OC`, `SYMB`, `OUTP`, `CPU`, `RBT`, `DISC`, `JOB`, `VOLU`, `TAPE`, `USER`, `PACK`, `COC`, `RES` | many tables |
| `SCRATCH` | `KISCRTH` | Card reader / scratch tape | devices |
| `PREF` | `KIRAD1ST` | Sets `RAD1ST` to 1 if the delimiter after `PREF` is a blank, otherwise 0 | `RAD1ST` |
| `ANSS`, `ANSM`, `OVER`, `READ` | `KIANSS`, `KIANSM`, `KIANSO` | ANS labelled-tape scratch, mount, overwrite. `READ` shares `KIANSO` with `OVER` | devices |
| `DIAG` | `KDIAG` | Authorizes a user ID for diagnostics (`DID`) | users (`GETUSER#`) |
| `OBON`, `OBOF` | `KOBN`, `KOBF` | Clears or increments `SSTAT` byte 0 | `SSTAT` |
| `S…` (no match) | `SKIN` | Symbiont key-ins | symbionts |

### Starting a ghost job: `GJOB` (`KIGJOB`, `KEYN.txt:715`)

The forms, from the handler's comment (`:694`–`:713`):

```
GJOB NAME                    a :SYS task
GJOB NAME.ACCOUNT            a task from another account
GJOB NAME,RESOURCE           ... with a resource name, passed in the task's M:UC DCB
GJOB NAME.ACCOUNT,RESOURCE   "SO THAT IT CAN TALK TO THAT RESOURCE WHEN IT COMES INTO CORE"
```

1. Take the name field (`GKIFLD`, after removing `:` from the delimiters). More than 7
   characters is `KEYERR`, and so is `KEYIN`: "DONT START OURSELF".
2. The name ends the key-in (NL): **`T:GJOBSTRT`**, a `:SYS` ghost (`KIGJOB5`).
3. A `.` is followed by the account (`KIGJOB4`), and a `,` by a resource name. The resource must
   be in the resource table (`SH:RNM`), or it is `KEYERR`. Any other delimiter is `KEYERR`. With an
   account or resource, the code goes to **`T:GJOBR`** (`T$OV.txt:378`), which passes the resource
   index and the account to `T:GJOB` ([§4](#4-starting-the-keyin-ghost-tp50-ioqtxt1944)).
4. **The reply**, from `T:GJOBSTRT`'s condition codes (`KIGJOB6`):

   | CC | Meaning | Typed (`OCQUEUE`) |
   |---|---|---|
   | 0 | Started | nothing |
   | CC3 (with CC1) | Already running | `TASK CURRENTLY ACTIVE` |
   | CC2 | Was asleep, woken (`E:WU`) | `TASK AWAKENED` |
   | CC1 | No slot or user | `TASK TABLES FULL` |

   Each message is TEXTC with a tab and `**` in front (X'05', X'5C', X'5C').

What the new ghost then runs is its first job step: the step code loads the load module of that
name from the account and starts it. Neither the step code nor the loader has been read.

### Shutdown: `ZAP` and the scheduler's idle check

There is no `SHUTDOWN` key-in. `!ZAP` (`KIFDOWN`, `KEYN.txt:805`) starts the shutdown, and the
scheduler finishes it:

1. `KIFDOWN` stores −2 in **`GOODNGT`** (`TABLES.txt:382`, "SAVE SYMB FILES").
2. It aborts every user that isn't in the null state (`UB:US` ≠ `SNULL`) and whose user number is
   above `MING`−1, with `T:RUE` and `E:ABRT`. The lower numbers are "KEYN, ALLOCAT, RBBAT", which are spared.
3. It falls into `KIGDOWN` (`OFF`): no new on-line or batch users.
4. When **`T:SE`** finds no user it can run (`SCHED.txt:1048`–`:1056`), it reaches the idle check
   (`SCHED.txt:1065`). It adds `GOODNGT` to **`S:CUIS`**, the current number of users in the
   system (`SSDAT.txt:51`). If the result is greater than 0, the system just idles (`IDL1`).
   With `GOODNGT` = −2, the result reaches 0 when only two users are left, for example ALLOCAT and
   RBBAT once KEYIN has logged off.
5. It then checks each symbiont (index `SNDDX`−2 down to 1). A symbiont with `SSTAT` = 1, or with
   `SSIG` = `'I'`, is still busy, and the system keeps idling.
6. Otherwise it waits (`BDR` on `Y004` = X'400000', "WAIT 5 SECONDS TO PERMIT COC OUTPUT") and executes
   **`SCREECH X'404'`** (`SCHED.txt:1084`). Recovery treats code X'404' as a shutdown: nothing is typed,
   no memory dump is taken, the state is saved, and the system reboots (see [`recovery.md`](recovery.md) §5–§6).

`!OFF` alone leaves `GOODNGT` at 0, so the idle check never fires while any user exists. The
system stays up with no new users allowed.

### `DATE` and `TIME` in detail (`KEYN.txt:1102`–`:1192`)

Each value is a field read by `GDTKIVAL`:

- Each character must be an EBCDIC digit (X'F0'–X'F9', `DTVALCK`).
- A field has one or two digits; one digit gets a leading `0`.
- The value is checked as two EBCDIC characters (`CLM`) against the limits `MAXHRVAL` 00–23,
  `MAXMINVAL` 00–59, `MAXMONVAL` 01–12, `MAXDAYVAL` 01–31 and `MAXYRVAL` 00–99. There is no
  `BADATES` or leap-year check, unlike `MONINIT`.
- The values are stored as EBCDIC characters:
  - `TIME`: hours in halfword 0, minutes in halfword 1.
  - `DATE`: month in halfword 0, day in halfword 1.
  - `DATE+1`: the year, right-justified.

Only as many fields as the command needs are read, so anything after them is ignored:
`!T 1:2:3X` sets the time to 01:02. Each value is stored as soon as it has been checked. A later field that fails then goes to `KEYERR`
and leaves the earlier ones changed. For example, `!D 07/32/76` sets the month to 07 and then
gets `EH?`.

## What a minimal translation needs

| Piece | Source | Can be done without the scheduler? |
|---|---|---|
| Console interrupt and `IOCTQ` | `OCINT`, `CTRIG`, `CTIOP` | Yes, as a loop that pops control words |
| Prompt and read | `TP20`, `KEYINBUF` | Yes, with the console stub doing the read and `TP30` as end action |
| Device key-ins | `TP30`–`TP33` | Yes, given a device with a key-in pending |
| Canned messages | `OCQUEUE`, `MSGBASE` | Yes |
| Starting KEYIN | `T:GJOBSTRT` | No: needs the scheduler, a ghost slot and the file system |
| Parser and table | `GKIFLD`, `KITBL` | Yes |
| `DATE`, `TIME`, `ON`, `ONB`, `OFF`, `PREF`, `OBON`/`OBOF`, `SYST`, errors | handlers above | Yes: they change only a few cells |
| `ZAP` and the idle check | `KIFDOWN`, `SCHED.txt:1065` | Yes, if no on-line or batch users exist, so the abort loop finds no one; `S:CUIS` is then the system ghosts left |
| The rest | handlers above | No: they need users, ghosts, symbionts or devices |

The Python translation (`python/uts/keyin.py`) follows this table. The commands marked "Yes" work,
and the rest are logged as not translated. Since the scheduler was translated (`sched.py`),
`TP50` starts KEYIN through a translated `T:GJOBSTRT`, as a stand-in ghost that runs `KEYIN1` and
logs off. `ZAP`'s abort loop reports `E:ABRT` for the users at `MING` and above. The load module
and the file system are still skipped.

## Open questions

- **`OC52`'s X'05'** (resolved): the `LATER` message is NL, a tab, `LATER`, NL. X'05' is HT in EBCDIC,
  and the device messages use the same tabs (`CR3T`, see [`io.md`](io.md) §9).
- **The KEYIN load module**: `KEYN.txt` ends `END START%KEYIN`, and `TP50` starts a ghost called
  `KEYIN`. That the KEYIN load module is built from `KEYN`, and from which other modules, isn't
  recorded in this source.
- **`KIGUP`'s digit loop** (`DCV20`) reads four characters, and accepts a blank as the end of the number.
  Whether leading blanks are allowed hasn't been checked.
