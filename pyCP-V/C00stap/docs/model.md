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
- **The transition table is checked against CP-V's.** A test parses the `ESTS` lines in
  `SCHED.txt` (30 entries, 255 event and state combinations). It checks every one against
  `TransitionTable.lookup`, with the in-core and out-of-core twin states merged as the model
  merges them. It also checks that the model adds no entries CP-V doesn't have.
- **Generated docs.** [`model/glossary.md`](model/glossary.md) and the state diagram in
  [`model/states.md`](model/states.md) are generated from the code. A test fails when they're
  out of date.

## Running it

From `python/`, with the `p3.13` environment:

```
python -m cpvmodel              # a demo run, printed as a trace
python -m cpvmodel docs         # regenerate docs/model/glossary.md and states.md
python -m pytest cpvmodel/tests # or: make modeltest
```

## The model so far

The model is built from **components**, one per major part of CP-V. Each component is a
subpackage with one class in front. The rest of the system calls that class's methods, never
its parts.

| Package | Front class | CP-V | Parts |
|---|---|---|---|
| `cpvmodel.scheduler` | `Scheduler` | SCHED, "execution and swap scheduler" | `StateQueues`, `EventRouter` and `TransitionTable`; later `ExitPath` and `SwapScheduler` |
| `cpvmodel.filesystem` (later) | `FileSystem` | the file management modules | directories, file kinds, `GranuleAllocator` |

`System` (`cpvmodel/system.py`) puts the components together. It owns what's machine-wide: the
user slots, the clock, `FutureEvents`, the run loop and the trace. `User` and the program steps
are shared by everything.

```mermaid
classDiagram
    class System {
        clock
        users
        startUser(name, program, priority)
        endUser(user)
        execute(user)
        advanceClock(ticks)
        idleUntil(time)
        run(tickLimit)
    }
    class Scheduler {
        currentUser
        usersInSystem
        report(user, event)
        addUser(user, priority)
        removeUser(user)
        dispatch()
        endQuantum(user)
        isShutDown()
    }
    class User {
        number
        state
        priority
        basePriority
        inCore
        ioInFlight
        program
    }
    class StateQueues {
        bands
        bandFor(priority)$
        add(user)
        remove(user)
        firstReady()
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
        schedule(time, user, event)
        popDue(time)
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
    System *-- FutureEvents
    Scheduler *-- StateQueues
    Scheduler *-- EventRouter : router
    EventRouter *-- TransitionTable
    TransitionTable ..> Event
    TransitionTable ..> PriorityBoost
    StateQueues o-- User : 12 bands
```

A program is a generator that yields `Compute(ticks)`, `Sleep(ticks)`, `DoIo(ticks)` or
`Yield()`. Each stands for what a user's code does in CP-V: run until the clock ends the quantum,
or make a CAL that leads to an event report.

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

### The run loop

In CP-V, `T:SE` is entered again after every quantum, block and interrupt exit. Here it is a
plain loop:

```mermaid
flowchart TD
    run([run]) --> current{"scheduler.currentUser<br/>still running?"}
    current -->|yes| execute
    current -->|no| dispatch["scheduler.dispatch: first in-core user,<br/>most urgent band first (T:SE)<br/>boost decays 1 (SE1)"]
    dispatch -->|user| execute["execute: next program step"]
    dispatch -->|nobody ready| check{"scheduler.isShutDown?<br/>S:CUIS + GOODNGT ≤ 0"}
    check -->|yes| shutdown(["shutdown (SCREECH X'404')"])
    check -->|no| pending{"future events?"}
    pending -->|yes| idle["idleUntil the next one (WAIT)"]
    pending -->|no| stuck(["stuck"])
    idle --> run
    execute -->|"Compute(n)"| quantum["advanceClock(n): due events are reported<br/>endQuantum: base priority, tail of band"]
    execute -->|"Sleep, DoIo, Yield"| report["scheduler.report(...)"]
    execute -->|program ended| endUser["endUser: free the slot (STEP70)"]
    quantum --> run
    report --> run
    endUser --> run
```

### What it shows

From the demo (`python -m cpvmodel`). `editor` alternates computing and I/O, `clock` sleeps, and
`alpha` and `beta` crunch at the same base, X'F8':

```
   165  editor     IO_STARTED: RUNNING -> IO_WAIT
   165  alpha      dispatched at 0xf8
   165  alpha      computes 40
   185  clock      WAKE_UP: ASLEEP -> READY
   195  editor     IO_COMPLETE: IO_WAIT -> READY
   205  editor     dispatched at 0xf7
```

- `editor`'s I/O boost puts it at X'F6'. It runs as soon as `alpha`'s quantum ends, ahead of
  `beta`, which has been waiting longer.
- `clock` woke at 185 with the special-compute boost. But its base is X'FC', so X'FC' − 3 =
  X'F9' is still less urgent than the crunchers. It waits until they finish at 250.
- With everyone waiting, the system idles until the next event.

What is CP-V's so far:

- **Bands, order and dispatch.** Priority bands are from `CHSE1`. A user goes behind equal
  priorities (`T:CHSE`). Dispatch takes the first in-core user, most urgent band first (`T:SE`).
- **Priority over time.**
  - A new user starts with the interactive boost (`ADD1` → `STIRC`).
  - An event that makes a user ready gives the `SH:PINC` boost for that kind of event.
  - The boost decays by 1 at each dispatch (`SE1`, `S:PRIODEC`).
  - At quantum end the user goes back to their base, at the tail of the queue (`T:CHSE0`).
  - A real-time user always runs at their base ("DONT FLOAT RT").
- **Events.** CP-V's whole state-and-event table, checked against the source.
- **Shutdown.** When nobody is ready and `usersInSystem − ghostsKeptAtShutdown ≤ 0`, the run ends
  ("shutdown"). This is the idle check, `S:CUIS`+`GOODNGT` ≤ 0, which ends in `SCREECH X'404'`.

Not yet: each `Compute` is a whole quantum and isn't interrupted, nobody is preempted, and
nobody is swapped, so every user stays in core.

## Iterations

1. **A shallow System** (done). Users, bands, dispatch, priority boost and decay, shutdown.
2. **Events and the transition table** (done). `Event`, `TransitionTable`,
   `InconsistentEvent`, `EventRouter`, `FutureEvents`. Programs that sleep, do I/O and yield.
   The generated state diagram. Then the refactor into components: `Scheduler` in front of
   SCHED's parts, with `System` putting the components together.
3. **The exit path.** Real quanta cut by the clock, preemption by a more urgent user (`S:HIR`,
   `QMIN`), and signals (break, control-Y, error, abort), which replace the first
   `NotModelledYet` stubs.
4. **Resources.** Blocking on and releasing `R:*` resources, and their events.
5. **Swapping.** `inCore`, pages, the swap scheduler choosing who comes in and who goes out,
   kick-out.
6. **Terminals and log-on.** Terminal read and output blocking, and log-on from a break.
