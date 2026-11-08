# A readable model of CP-V

`python/cpvmodel/` is a small, runnable model of how CP-V works, with modern names. It is not a
translation. [`uts`](../python/uts) is the faithful translation, which runs the real monitor's
logic down to the registers. The model keeps the design and leaves out the machine. Its job is to
make CP-V easy to follow. Every name in it maps back to the CP-V symbols and source lines it stands
for, in the [glossary](model/glossary.md).

## Conventions

- **Names.**
  - Classes are capitalized nouns (`StateQueues`).
  - Methods are lowercase verbs in camelCase (`dispatch`, `startUser`), and so are attributes
    and test names.
  - Constants and enum members are UPPER_CASE with underscores (`PriorityBoost.INTERACTIVE`,
    `UserState.AWAITING_TERMINAL_INPUT`), so they stand out. If a name never changes after
    import, it's UPPER_CASE.
- **Priority** keeps CP-V's numbers. It runs from X'00' to X'FF', and a **lower value is more
  urgent**. Below X'C0' is real time. On-line and batch users are normally between X'C0' and X'FF'.
- **Simplifications** are stated in each class's docstring as "In CP-V this is really...". Where
  the model follows a CP-V quirk on purpose, the code says `CP-V quirk:`.
- **Independent of `uts`.** The model and its tests never import `uts`.

## Keeping it honest

- **Glossary.** A `cpv(...)` ref ties each class, method, attribute and enum member to CP-V.
  `modelOnly(...)` marks a name with no counterpart. The tests fail when a public name has no
  ref, or when a cited symbol isn't in the cited source lines.
- **The transition table is checked against CP-V's.** A test parses the `ESTS` and `RESOURCE`
  lines in `SCHED.txt` (44 entries, 437 event and state combinations). It checks every one against
  `TransitionTable.lookup`, with the in-core and out-of-core twin states merged as the model
  merges them. It also checks that the model adds no entries CP-V doesn't have.
- **Generated docs.** [`model/glossary.md`](model/glossary.md) and the state diagram in
  [`model/states.md`](model/states.md) are generated from the code. A test fails when they're
  out of date.

## Running it

From `python/`, with the `p3.13` environment:

```
python -m cpvmodel              # a demo run, printed as a trace
python -m cpvmodel terminal     # a user logs on at a terminal, beside a cruncher
python -m cpvmodel docs         # regenerate docs/model/glossary.md and states.md
python -m pytest cpvmodel/tests # or: make modeltest
```

## The model so far

The model is built from **components**, one per major part of CP-V. Each component is a
subpackage with one class in front. The rest of the system calls that class's methods, never
its parts.

| Package | Front class | CP-V | Parts |
|---|---|---|---|
| `cpvmodel.scheduler` | `Scheduler` | SCHED, "execution and swap scheduler" | `StateQueues`, `EventRouter` and `TransitionTable`, `ExitPath`, `SwapScheduler`, `ResourceManager`, `SchedulerSettings` |
| `cpvmodel.terminals` | `TerminalController` | COC, "character-oriented communications" | `Line`, `TerminalSettings`; `echoSession` stands in for TEL |
| `cpvmodel.filesystem` | `FileSystem` | OPNF, CLS, RDF, WRTF: the file management modules | `Disc`, `Directory`, `FileHeader`, `File`, `ConsecutiveFile`, `FileHandle`, `FileSystemSettings` |

`System` (`cpvmodel/system.py`) puts the components together. It owns what's machine-wide: the
user slots, `Memory`, the clock, `FutureEvents`, the run loop and the trace. The components talk
to each other only through their front classes: the terminals report events to the scheduler
with `scheduler.report`. `User` and the
program steps are shared by everything.

```mermaid
classDiagram
    class System {
        clock
        users
        startUser(name, program, priority, pages)
        endUser(user)
        execute(user)
        advanceClock(ticks)
        idleUntil(time)
        run(tickLimit)
    }
    class Scheduler {
        currentUser
        usersInSystem
        settings
        report(user, event)
        addUser(user, priority)
        removeUser(user)
        dispatch()
        swapSchedule()
        exitToUser(user)
        endQuantum(user)
        moreUrgentUserWaiting(user)
        requeue(user)
        claimOpenClose(user)
        endOpenClose(user)
        isShutDown()
    }
    class TerminalController {
        lines
        onlineUsers
        pressBreak(line)
        type(line, text)
        hangUp(line)
        logOn(line)
        read(user)
        write(user, text)
    }
    class Line {
        number
        user
        typedLines
        readPending
        outputCount
        transcript
    }
    class ResourceManager {
        queues
        openCloseUser
        block(user, resource)
        release(resource, reportedFor)
        unqueue(user)
        releaseForSignal(user, signal)
    }
    class Resource {
        <<enumeration>>
        OPEN_CLOSE
        DISC_PAGE
        ENQUEUE
        ...
    }
    class ExitPath {
        check(user)
        actOnSignals(user)
        deliverBreak(user)
        checkSwapQuantum(user)
        endQuantum(user)
        preempt(user)
    }
    class SwapScheduler {
        swapInProgress
        schedule()
        chooseUsersToSwapOut(incoming, shortfall)
        startSwap(outgoing, incoming)
        finishSwap(outgoing, incoming)
    }
    class SchedulerSettings {
        quantum
        minimumRun
        swapQuantum
        swapQuantumNear
        swapPenalty
        swapTime
    }
    class Memory {
        totalPages
        freePages
        take(pages)
        give(pages)
    }
    class User {
        number
        state
        priority
        basePriority
        inCore
        pages
        swapQuantumPending
        ioInFlight
        blockedOn
        quantumLeft
        dispatchedAt
        pendingSignals
        program
    }
    class StateQueues {
        bands
        waiting
        bandFor(priority)$
        add(user)
        remove(user)
        firstReady()
        firstReadyOutOfCore()
        swapOutOrder()
    }
    class EventRouter {
        eventCount
        report(user, event)
        changeState(user, state)
        makeReady(user, boost)
        waitForIo() completeIo() ignore() ...
    }
    class TransitionTable {
        rules
        lookup(event, state)
    }
    class FutureEvents {
        schedule(time, action, user)
        popDue(time)
        cancelFor(user)
    }
    class Event {
        <<enumeration>>
        IO_STARTED
        IO_COMPLETE
        SLEEP
        WAKE_UP
        BREAK
        ...
    }
    class PriorityBoost {
        <<enumeration>>
        COMPUTE = 0
        SPECIAL_COMPUTE = 3
        IO_DONE = 2
        INTERACTIVE = 6
    }
    System "1" *-- "SMUIS" User : users
    System *-- Scheduler
    System *-- TerminalController : terminals
    System *-- FileSystem : files
    TerminalController *-- Line : lines
    Line --> User
    System *-- Memory
    System *-- FutureEvents
    Scheduler *-- StateQueues
    Scheduler *-- EventRouter : router
    Scheduler *-- ExitPath
    Scheduler *-- SwapScheduler
    Scheduler *-- ResourceManager : resources
    ResourceManager ..> Resource
    Scheduler *-- SchedulerSettings
    EventRouter *-- TransitionTable
    TransitionTable ..> Event
    TransitionTable ..> PriorityBoost
    StateQueues o-- User : 12 bands, waiting queues
```

A program is a generator that yields `Compute(ticks)`, `Sleep(ticks)`, `DoIo(ticks)`,
`Yield()`, `WaitFor(resource)`, `Release(resource)`, `OpenClose(ticks)`, `ReadTerminal()` or
`WriteTerminal(text)`, `Open(name, mode)`, `ReadRecord(handle)`, `WriteRecord(handle, text)` or
`Close(handle)`. What a step returns is sent back into the program, such as
`text = yield ReadTerminal()` or `handle = yield Open("DATA", FileMode.IN)`. An error is thrown into
the program, so a program can catch a `FileError`. Each stands for what a user's code does in CP-V: compute, or make a CAL that leads
to an event report. A tick is a clock-4 tick, 2 ms. A program can catch `Break`; that is its
break routine (`M:INT`).

### Events and the transition table

When something happens to a user, it is **reported** as an event: `scheduler.report(user, event)`.
The transition table looks up the user's state and the event and returns an action:

- a **state**: just move there (`SLEEP` from `RUNNING` → `ASLEEP`);
- a **priority boost**: make the user ready, that much more urgent than their base
  (`WAKE_UP` from `ASLEEP` → ready with `SPECIAL_COMPUTE`, 3);
- a **handler**, an `EventRouter` method, for anything more involved (`IO_STARTED` →
  `waitForIo`, which waits only if the I/O isn't already done).

An event that doesn't apply to the user's state is `InconsistentEvent`, CP-V's `SCREECH X'02'`.
Many events are deliberately harmless in most states: `WAKE_UP` for a user who isn't asleep is
ignored. The transitions that later iterations will model are in the table already. They raise
`NotModelledYet`: signals, terminals, access queues, kick-out, shared processors and too much
I/O. All the moves are in the [state diagram](model/states.md).

An I/O round trip:

```mermaid
sequenceDiagram
    participant P as editor's program
    participant S as System
    participant C as Scheduler
    participant R as EventRouter
    participant T as TransitionTable
    participant F as FutureEvents
    P->>S: yield DoIo(30)
    S->>S: user.ioInFlight += 1 (UB:MF)
    S->>F: schedule(now+30, editor, IO_COMPLETE)
    S->>C: report(editor, IO_STARTED)  (T:IOREG, E:IIP)
    C->>R: report
    R->>T: lookup(IO_STARTED, RUNNING)
    T-->>R: waitForIo (STIIP)
    R->>R: I/O still going → changeState(IO_WAIT)
    Note over S: other users run, or the system idles
    F-->>S: due at now+30
    S->>C: report(editor, IO_COMPLETE)  (IOQ, E:IC)
    C->>R: report
    R->>T: lookup(IO_COMPLETE, IO_WAIT)
    T-->>R: completeIo (STIOC)
    R->>R: ioInFlight -= 1 → 0, makeReady(IO_DONE)
    Note over R: priority = base − 2, back in its band
```

### The exit path

Every interrupt, trap and CAL goes back to the user through the **exit path** (`SSE0`–`SSE6`).
That is where CP-V acts on signals, ends quanta and preempts. `scheduler.exitToUser(user)`
runs it:

```mermaid
flowchart TD
    enter(["exitToUser: after an interrupt, a CAL,<br/>or the clock ending the quantum"]) --> signals{"signals pending?<br/>(UH:DL)"}
    signals -->|ABORT| aborted(["user ends: aborted (T:OFF)"])
    signals -->|ERROR| error(["user ends: error (SEERR)"])
    signals -->|CONTROL_Y| cp(["back to the command processor (T:ECCP)"])
    signals -->|BREAK| brk{"program catches Break?<br/>(M:INT)"}
    brk -->|yes| routine(["user goes on in its break routine"])
    brk -->|no| cp
    signals -->|none| squan["swap quantum: met? near it?<br/>(SSE5A: SL:SQNT, SL:SQUAN)"]
    squan --> quantum{"quantum used up?<br/>(J:DELTAT)"}
    quantum -->|yes| newq(["new quantum, base priority,<br/>tail of band (T:ACCTEX, T:CHSE0)"])
    quantum -->|no| qmin{"run at least minimumRun<br/>since dispatch? (SL:QMIN)"}
    qmin -->|no| goon(["user goes on (T:PULLE)"])
    qmin -->|yes| hir{"a more urgent user ready?<br/>(S:HIR)"}
    hir -->|no| goon
    hir -->|yes| preempt(["preempted: back in the queue<br/>at the current priority (CHSE0),<br/>+ SL:SQPB if near the swap quantum"])
```

Signals are reported like any other event. For a running or I/O-waiting user, `BREAK`,
`CONTROL_Y`, `ERROR` and `ABORT` only set a flag (`STBEEA`). The user acts on it the next time
they run. A user who is asleep, waiting for terminal input, or ready is also made ready with
the interactive boost (`STBEEAC`), so they see the signal soon.

A preemption: an I/O completion makes a more urgent user ready.

```mermaid
sequenceDiagram
    participant D as I/O device
    participant S as System
    participant C as Scheduler
    participant E as ExitPath
    Note over S: beta computes at X'F8'
    D-->>S: interrupt: editor's I/O done
    S->>C: report(editor, IO_COMPLETE)
    C->>C: editor ready at X'F6' (IO_DONE boost)
    S->>C: swapSchedule()  (T:SS)
    S->>C: exitToUser(beta)  (SSE0)
    C->>E: check(beta)
    E->>E: no signals, quantum left,<br/>beta has run at least minimumRun
    E->>C: moreUrgentUserWaiting(beta)? yes
    E->>C: requeue(beta) at X'F8'
    S->>C: dispatch()
    C-->>S: editor
```

### Swapping

Users need pages in core to run, and there are fewer pages than users need, so the
**swap scheduler** (`T:SS`) decides who is in core. It runs before every dispatch and on every
interrupt exit. A new user starts out of core, and is swapped in before they first run.

```mermaid
flowchart TD
    start(["swapSchedule (T:SS)"]) --> busy{"a swap going?<br/>(S:SIP)"}
    busy -->|yes| done([nothing])
    busy -->|no| pick{"most urgent ready user<br/>out of core? (PIKUS)"}
    pick -->|none| idleout["swap out the in-core sleepers<br/>and terminal waiters anyway"]
    pick -->|incoming| fits{"enough free pages?"}
    fits -->|yes| swap
    fits -->|no| walk["walk the queues in SB:SWP order, each from its tail:<br/>asleep, terminal input, X'FF' band, output blocked,<br/>resource, interrupt, access, X'FE' ... real-time bands"]
    walk --> take{"in core, no I/O going,<br/>and (if ready) swap quantum met?"}
    take -->|"yes, enough pages now"| swap["report KICK_OUT for each one going out;<br/>the swap takes swapTime per user"]
    take -->|"reached the incoming user,<br/>or the end"| giveup(["no room (GIVEUP)"])
    idleout --> swap
    swap --> finish(["finishSwap: pages move; the incoming user<br/>is in core with the swap quantum pending"])
```

Some consequences, all CP-V's:

- **Only waiting users and less urgent ready users can be swapped out** for a user coming in.
  The walk starts with the least urgent band and stops when it reaches the user coming in.
- **A just-swapped-in ready user is protected** until they've run the swap quantum
  (`SL:SQUAN`) in a quantum, so swapping can't thrash. CP-V only looks at the swap quantum once
  the user has used `SL:SQNT` (300 ms), so in effect it is never shorter than that.
- **Nobody is swapped out while I/O is going**, and the running user is in no queue, so it is
  never a candidate either.
- **When nobody needs to come in, sleepers and terminal waiters are swapped out anyway**, so
  the room is there when someone does.
- **A user preempted when nearly through the swap quantum goes back 2 notches less urgent**
  (`SL:SQPB`, commented "BOOST TWO NOTCHES" but added to the priority value).

A swap, from the demo:

```mermaid
sequenceDiagram
    participant S as System
    participant C as Scheduler
    participant W as SwapScheduler
    participant Q as StateQueues
    participant M as Memory
    Note over S: alpha's quantum ends (t=515)
    S->>C: dispatch()  (T:SE)
    C->>W: schedule()  (T:SS)
    W->>Q: firstReadyOutOfCore()
    Q-->>W: clock, needs 4 pages; 3 free
    W->>Q: swapOutOrder()
    W->>W: alpha: ready, in core, swap quantum met
    W->>C: report(alpha, KICK_OUT)  (E:KO: inCore = false)
    Note over W: swap device busy for 2 × swapTime
    C-->>S: editor (in core) runs meanwhile
    W->>M: give(alpha's 5), take(clock's 4)  (t=535)
    W->>W: clock in core, swap quantum pending
```

### Resources

When something a user needs is short (a disc page, a terminal buffer, a symbiont file slot),
the monitor **blocks** them on that resource: the user waits in `AWAITING_RESOURCE`. When it
comes free, the resource is **released** and waiting users are made ready with the
special-compute boost. Each resource has its own release rule (`SH:RFLG`):

| Resource | CP-V | Release |
|---|---|---|
| `SYMBIONT_FILE_SLOT` | `R:SYMF` | everyone (FLUSH) |
| `SYMBIONT_DISC_SPACE` | `R:SYMD` | everyone |
| `OPEN_CLOSE` | `R:OCR` | one user, and only if nobody is the open/close user (`OPNUNBLOCK`) |
| `TERMINAL_BUFFER` | `R:CBA` | everyone |
| `DISC_PAGE` | `E:ND`/`E:DPA` | everyone |
| `ALLOCATOR` | `E:QFAC`/`E:UQFAC` | everyone, after updating ALLOCAT's buffers (not modelled) |
| `ENQUEUE` | `R:NQW` | only the user the release is reported for (SPECIFIC); a signal also releases |

Open/close is a lock built from a resource. Only one user at a time may open or close files
(`OPNCLSUS`), so `OpenClose(ticks)` does what CLS does. If someone else is the open/close
user, it blocks on `OPEN_CLOSE` and tries again when released. At the end it gives the lock
up and, if anyone is waiting, reports the release (`E:NOCR`, from IORT).

```mermaid
sequenceDiagram
    participant A as a (open/close user)
    participant C as Scheduler
    participant R as ResourceManager
    participant B as b, c (blocked)
    Note over A: a holds the open/close
    B->>C: claimOpenClose: someone else has it
    C->>R: block(b), then block(c)  (head of the queue)
    A->>C: endOpenClose(a)
    C->>R: release(OPEN_CLOSE)  (E:NOCR)
    R->>R: OPNUNBLOCK: nobody holds it, c becomes the open/close user
    R->>C: makeReady(c, SPECIAL_COMPUTE)
    Note over B: c runs, claims again (it's c's), opens; b waits for c
```

Two CP-V quirks show here:

- **Last in, first out.** Blocking pushes the user on the *head* of the resource's queue
  (`T:RES`), and release takes the head (`T:REL`). In `testOpenCloseWaitersAreReleasedLastInFirstOut`,
  `c` blocks after `b` but gets in first.
- **The released user is usually more urgent than the releaser.** With the special-compute
  boost, `c` preempts `a` on `a`'s way back from the CAL that released it.

A signal for a blocked user is only noted, and acted on when they next run, after the
release. The exception is `ENQUEUE`, whose flags list the signals (`SETDL`): there the user
is released at once to act on the signal.

### Terminals and log-on

The **terminal controller** (CP-V's COC) owns the terminal lines and reports what happens on
them to the scheduler:

| On the line | The model | Event, state |
|---|---|---|
| A program reads, nothing typed yet | `read` (`COCRD`) | `TERMINAL_READ` (`E:CRD`): `AWAITING_TERMINAL_INPUT` (`STI`) |
| A line is typed, a read waiting | `type` (`COCIP`) | `TERMINAL_INPUT_DONE` (`E:CIC`): ready, interactive boost (`STIRC`) |
| A line is typed, no read yet | `type` | kept as type-ahead; the next read takes it without waiting |
| A write with `SL:TB` characters still to go out | `write` (`COCWR`) | `OUTPUT_BLOCKED` (`E:CBL`, `STOB`) |
| The output drains to `SL:UB` | `outputDrained` (`COCOP`) | `OUTPUT_UNBLOCKED` (`E:CUB`): ready, I/O-done boost |
| Break on a line with a user | `pressBreak` | `BREAK` (`E:CBK`) |
| Break on a line with nobody | `pressBreak` → `logOn` (`LOGON`) | a new user, through `ADD1` |
| The line drops | `hangUp` | `ABORT` (`E:OFF`) |

**Log-on** (`LOGON`, `SCHED.txt:1869`) takes a free slot if the on-line users are under
`S:OUAIS`. It ties the user to the line (`LB:UN`) and starts them at the on-line priority
`SL:OPRIO`. In CP-V the user starts in TEL, the command processor; the model runs the line's
`session`, by default an echo loop that stops at `OFF`. When the user ends, the line is free
again and the on-line count drops (`STEP.txt:159`).

**Input that beats the block.** COC reports the read (`E:CRD`) after finding no input. If the
input completes in between, `E:CIC` arrives while the user is still running. `STIRCU` then
remembers it (`UH:FLG` X'4000'), and `STCRD` lets the read go straight on. The access queue
(`STQA`, `STUQA`) uses the same flag.

From the terminal demo (`python -m cpvmodel terminal`), a user typing beside a cruncher:

```
    20  line0      logged on, line 0
    20  line0      TERMINAL_READ: RUNNING -> AWAITING_TERMINAL_INPUT
    20  line0      KICK_OUT in AWAITING_TERMINAL_INPUT
   ...
   300  line0      TERMINAL_INPUT_DONE: AWAITING_TERMINAL_INPUT -> READY
   300  line0      swapped in
   300  cruncher   preempted
   300  line0      dispatched at 0xf3
```

- While the user waits for input they are swapped out, because nobody else needs to come in.
- Each typed line brings them back with the interactive boost (X'F2'), ahead of the cruncher.
- At 700 the cruncher is preempted 190 ticks into its quantum, near its swap quantum, so it goes
  back at X'FA' rather than X'F8' (`SL:SQPB`).

### The file system

The file system is the third component. Its front class is `FileSystem` (CP-V's OPNF, CLS, RDF
and WRTF, about 25,000 lines). In this first iteration it has:

```mermaid
classDiagram
    class FileSystem {
        accounts
        openFiles
        openFile(user, name, mode, account)
        readRecord(handle)
        writeRecord(handle, text)
        closeFile(handle)
        closeAll(user)
    }
    class Directory {
        keys
        find(key)
        insert(key, value)
        remove(key)
    }
    class File {
        header
        openCount
        inDirectory
    }
    class FileHandle {
        user
        mode
        position
    }
    class ConsecutiveFile {
        granules
        recordCount
        append(text)
        read(position)
        release()
    }
    class FileHeader {
        name
        account
        organization
    }
    class Disc {
        getGranule()
        releaseGranule(granule)
    }
    class Granule {
        address
        capacity
        segments
    }
    FileSystem *-- Disc
    FileSystem *-- Directory : accounts
    Directory o-- Directory : an account's files
    Directory o-- File : by name
    FileSystem o-- File : open files
    FileHandle --> File : DCB
    File <|-- ConsecutiveFile
    File --> FileHeader : FIT
    ConsecutiveFile o-- Granule : chain
```

- **Two levels of directory.** The account directory maps an account to its file directory,
  which maps a file name to the file. Both are ordered by name. In CP-V they are chains of index
  blocks on the disc, kept in two copies; iteration 2 gives the model's directories those
  blocks.
- **A consecutive file** is a chain of granules of 2048 bytes. The header (the FIT, the closest
  modern idea is an inode) takes 320 bytes of the first. Records follow one another, each with
  a 4-byte control word, and a record that doesn't fit is split into segments continued in the
  next granule.
- **Open** first looks among the open files, so a second reader shares the `File` and reads no
  directories. Each program gets its own `FileHandle` (the DCB), with its own position. In
  CP-V an open file's state is a separate table in core, the CFU, which exists only while the
  file is open. The model's files are in memory anyway, so that state is on the `File`:
  `openCount` and `inDirectory`. **A file opened OUT is new**: it goes into its directory only at close,
  replacing any file of the same name and releasing its granules. Until then, opening the name
  IN finds the old file, or nothing.
- **Open and close take the open/close lock** (`OPNCLSUS`), the resource from the scheduler,
  and hold it while they wait for the disc. A second user opening at the same time blocks on
  `OPEN_CLOSE`.
- **Disc time.** Every granule read or written, and every directory looked up, is a disc access
  of `discTime` ticks. The program waits in `IO_WAIT` as it would for any I/O, so file work
  shows up in the scheduler. `discTime` is 0 by default.

A read, through the components:

```mermaid
sequenceDiagram
    participant P as reader's program
    participant S as System
    participant F as FileSystem
    participant C as Scheduler
    P->>S: yield ReadRecord(handle)
    S->>F: readRecord(handle)
    F->>F: the record from its granules (2 touched)
    F-->>S: "X...X", 2 disc accesses
    S->>C: report(reader, IO_STARTED)  (E:IIP)
    Note over C: reader in IO_WAIT for 2 × discTime
    C-->>S: IO_COMPLETE, reader runs again
    S->>P: send("X...X")
```

### The run loop

In CP-V, `T:SE` is entered again after every quantum, block and interrupt exit. Here it is a
plain loop:

```mermaid
flowchart TD
    run([run]) --> current{"scheduler.currentUser?"}
    current -->|yes| execute
    current -->|no| dispatch["scheduler.dispatch: swap schedule (T:SS), then<br/>first in-core user, most urgent band first (T:SE),<br/>boost decays 1 (SE1)"]
    dispatch -->|user| run
    dispatch -->|nobody ready in core| pending{"anything still to come?"}
    pending -->|yes| idle["idleUntil the next one (WAIT)"]
    pending -->|no| check{"scheduler.isShutDown?<br/>S:CUIS + GOODNGT ≤ 0"}
    check -->|yes| shutdown(["shutdown (SCREECH X'404')"])
    check -->|no| stuck(["stuck"])
    idle --> run
    execute{"execute: go on with the<br/>Compute step, or take the next"} -->|Compute| compute["compute until the step is done, the<br/>quantum runs out, or something is due"]
    compute -->|"interrupt or quantum end"| exit["swap schedule if interrupted (T:SSE),<br/>then scheduler.exitToUser"]
    compute -->|step done| run
    execute -->|"Sleep, DoIo, Yield (a CAL)"| report["scheduler.report(...),<br/>then exitToUser if still running"]
    execute -->|program ended| endUser["endUser: free the slot<br/>and the pages (STEP70)"]
    exit --> run
    report --> run
    endUser --> run
```

### What it shows

From the demo (`python -m cpvmodel`). It has 12 pages of memory, swaps of 10 ticks per user, and
a 500 ms quantum. `alpha` and `beta` (5 pages each) crunch at base X'F8', `editor` (4 pages)
alternates computing and I/O, and `clock` (4 pages, base X'FC') sleeps:

```
   270  beta       quantum ended
   270  beta       KICK_OUT in READY
   270  -          swap starts: out beta; in editor
   270  alpha      dispatched at 0xf4
   290  beta       swapped out
   290  editor     swapped in
   290  alpha      preempted
   290  editor     dispatched at 0xf3
   ...
   535  clock      dispatched at 0xf7
   535  clock      SLEEP: RUNNING -> ASLEEP
   535  clock      KICK_OUT in ASLEEP
   535  -          swap starts: out clock; in beta
```

- `editor` and `clock` start out of core and wait for room. At 270 `beta`'s quantum ends. It
  has met its swap quantum, so it goes out to make room for `editor`, and `alpha` runs during
  the swap.
- When `editor` is in core it preempts `alpha`, being more urgent on its newcomer boost.
- At 535 `clock` goes to sleep and is swapped out at once to bring `beta` back.
- When `clock` wakes at 635 it is ready at X'F9', less urgent than the crunchers at X'F8'. The
  walk reaches `clock` before them, so there is no room until a cruncher ends.
- At the end, with nobody waiting to come in, the sleeping `clock` is swapped out anyway and
  swapped back in when it wakes.

What is CP-V's so far:

- **Bands, order and dispatch.** Priority bands are from `CHSE1`. A user goes behind equal
  priorities (`T:CHSE`). Dispatch takes the first in-core user, most urgent band first (`T:SE`).
- **Priority over time.**
  - A new user starts with the interactive boost (`ADD1` → `STIRC`).
  - An event that makes a user ready gives the `SH:PINC` boost for that kind of event.
  - The boost decays by 1 at each dispatch (`SE1`, `S:PRIODEC`).
  - At quantum end the user goes back to their base, at the tail of the queue (`T:CHSE0`).
  - A preempted user keeps their current priority (`CHSE0`).
  - A real-time user always runs at their base ("DONT FLOAT RT").
- **Events.** CP-V's whole state-and-event table, checked against the source.
- **The exit path.** Signals are acted on in CP-V's order of importance, and all four are
  cleared at once, so a break that comes with a control-Y is lost. Then the swap quantum,
  quantum end, the minimum run and preemption.
- **Swapping.** Who comes in, the swap-out walk in `SB:SWP` order with its exclusions, the
  swap quantum, swapping out idle waiters, and kick-out (`STKO`, `STKOT`).
- **Resources.** The seven resources with their release flags, last in first out, the
  open/close lock (`OPNCLSUS`, `OPNUNBLOCK`), and signals releasing ENQ waiters.
- **Terminals and log-on.** Reads, type-ahead, output pacing, break, hang-up and log-on, with
  the "input before the block" flag.
- **Shutdown.** When nobody is ready and `usersInSystem − ghostsKeptAtShutdown ≤ 0`, the run
  ends ("shutdown"). This is the idle check, `S:CUIS`+`GOODNGT` ≤ 0, which ends in
  `SCREECH X'404'`. CP-V's system ghosts keep that count up until a `ZAP`. The model has no
  ghosts, so it also waits for anything still to come, such as a log-on.

Not yet:

- **Swapping detail.** Pages are only counted: no shared processors (their use counts and
  pages), no page stealer, no locks in core. A failed swap-in is retried at every schedule;
  CP-V waits until the swap set changes (`S:SEVF`).
- **Resource detail.** ALLOCAT's buffers (`STUQFAC`) aren't modelled, and nothing in the
  model is short of disc pages, buffers or symbiont space yet; programs block with `WaitFor`.
- **Terminal detail.** COC's characters, echo, editing and line modes; the model types and
  reads whole lines. TEL is stood in for by `echoSession`.
- **Still `NotModelledYet`:** too much I/O (`STIOMF`) and associating a shared processor
  (`STASP`).
- No DO list and no command processor. Control-Y and an uncaught break end the user instead
  of returning to TEL.

## Iterations

### The scheduler

1. **A shallow System** (done). Users, bands, dispatch, priority boost and decay, shutdown.
2. **Events and the transition table** (done). `Event`, `TransitionTable`,
   `InconsistentEvent`, `EventRouter`, `FutureEvents`. Programs that sleep, do I/O and yield.
   The generated state diagram. Then the refactor into components: `Scheduler` in front of
   SCHED's parts, with `System` putting the components together.
3. **The exit path** (done). `ExitPath`, `SchedulerSettings` and `Signal`. Quanta cut by the
   clock, preemption at interrupts after the minimum run, and signals, with `Break` thrown
   into programs.
4. **Swapping** (done). `Memory`, `SwapScheduler`, waiting-state queues in `StateQueues`,
   kick-out, the swap quantum, and swap time.
5. **Resources** (done). `Resource`, `ResourceManager`, the resource events, and `WaitFor`,
   `Release` and `OpenClose` in programs.
6. **Terminals and log-on** (done). `TerminalController`, `Line`, `TerminalSettings`, and
   `ReadTerminal` and `WriteTerminal` in programs. Log-on from a break, hang-up, and the access
   queue.

### The file system

1. **A shallow file system** (done). `FileSystem`, `Directory`, `Disc`, consecutive files,
   open and close (IN and OUT) under the open/close lock, open files shared, a
   new file entered at close, disc time, and `Open`, `ReadRecord`, `WriteRecord` and `Close` in
   programs.
2. **Index chains and keyed files.** Blocks, slides, splits and the pyramid built at close,
   shared by the directories and keyed files.
3. **Granule allocation.** The stack, the bit map, the thresholds, and the ALLOCAT ghost with
   `E:QFAC`/`E:UQFAC`.
4. **Random files, deleting files, and OPEN's access checks.**
