# CP-V's design, and lessons from running its programs

Notes from documenting and translating the monitor, and then running the real processors from
the CP-V C00 boot tape (`c00si/cpcp.tap`) on the translation: SHOW, PCL, EDIT, SORT, AP and others.
The first part is about CP-V's design and how it compares with modern systems; the second is
what running real programs taught us, much of it the hard way. Everything here comes from the
source or from what the tape's programs actually did. Where it is inference it says so.

## Part 1: the design

### The overall shape: a table-driven monitor for a very small machine

Much of CP-V is data rather than code:
- **The scheduler** is a set of event and state transition tables: events such as `E:CRD`,
  `E:CIC` and `E:AP` move users between queues such as `STI` and `STOB`
  ([`scheduler.md`](scheduler.md)).
- **CAL dispatch** is transfer vectors indexed by the FPT's code ([`cal.md`](cal.md)).
- **The monitor's own services live in overlays** (OPEN, CLOSE, MISOV, STEPOVR and the rest),
  paged in through the same scheduler as user work: a CAL whose overlay isn't in core reports
  `E:AP` and waits.

That is a direct answer to a Sigma with a 128K-word address space, in which even the operating
system didn't fit at once. It makes the system very regular: a new service is an entry in a table.
It also makes it hard to follow, because control flow is spread across tables, `EXU`s and
register conventions rather than visible in the code.

### Scheduling: priorities with round robin inside each level

A **multilevel priority scheduler with round robin within each level**, with priorities that are
boosted by events and decay back ([`scheduler.md`](scheduler.md) §1, §4, §5, §9):
- **The levels.** Every executable user has a priority byte (`UB:PRIO`; lower is more urgent).
  Below X'C0' is real-time (`SRT`); X'C0'–X'F5' share one queue (`SC0`); each of X'F6'–X'FF' has
  a queue of its own (`SC1`–`SC10`). `T:SE` takes the first runnable user from the most urgent
  non-empty queue. Within a queue, users are ordered by priority, a newcomer behind equals.
- **Round robin.** Each user gets a quantum (`SL:QUAN`). When it runs out the priority returns to
  its base and the user goes to the tail of their queue.
- **Boosts.** An event that makes a user runnable sets the priority to the base less an increment
  (`SH:PINC`): compute 0, special compute 3, I/O completed 2, **interactive input 6**. Opening or
  closing a file gives another 4 (`OPNBOOST`). The boost decays by `S:PRIODEC` (1) each time the
  user is scheduled.
- **Preemption.** An event that makes an in-core user more urgent than the running one preempts it
  (`T:CHSE`, `CHSE0`).
- **Coupled to swapping.** A user just swapped in has a swap quantum (`SL:SQUAN`) to use before it
  may be swapped out again, so swapping doesn't thrash; preempted partway through it, the user is
  requeued slightly less urgent (`SL:SQPB`).

This is the family of VMS and classic Unix: fixed levels, round robin, decaying boosts for I/O and
terminals (VMS's terminal boost is the closest relative). Linux's CFS has no levels or quanta at
all; it tracks weighted CPU time and runs whoever has had least. And CP-V schedules whole users
with swapping, where a modern system schedules threads and leaves memory to demand paging.

The quantum lengths and limits (`SL:QUAN`, `SL:QMIN`, `SL:SQUAN`, `SL:OPRIO`) are SYSGEN values
not in the source; the translation's values are invented.

### Memory: swapping, not demand paging

The Sigma has a hardware page map, but CP-V mostly swaps whole users: `T:SS` reasons in page
counts, and a user is in core or not. The page calls (`M:GP` and friends) record pages in the
user's map and count them towards the swap size; a running program's idle pages aren't paged out
([`pages.md`](pages.md)). Simpler and more predictable than demand paging, which suited
interactive users on a small machine.

### The virtual memory map, and the monitor's overlays

Pages are 512 words; the virtual space is pages X'00'–X'FF' (128K words). The page constants are
at `JIT.txt:269`–`:287`:

| Pages | Addresses (words) | What |
|---|---|---|
| X'2C'–X'3F' | X'05800'–X'07FFF' | The user's file-management buffers (`JXBUFVP`) |
| X'40'–X'45' | X'08000'–X'08BFF' | **The overlay window** (`JOVVP`): the current monitor overlay |
| X'46' | X'08C00'–X'08DFF' | The user's JIT (`JJITVP`), with `M:UC` and `M:XX` in it |
| X'47' | X'08E00' | The additional JIT (`JAJITVP`) |
| X'48', X'49' | X'09000', X'09200' | Special buffers 1 and 2 (`JSBUF1VP`, `JSBUF2VP`) |
| X'4E', X'4F' | X'09C00', X'09E00' | `JCOVP`, `JCO2VP` (not traced) |
| X'50'–X'DF' | X'0A000'–X'1BFFF' | **The user's program** (`JBUPVP`–`JEUPVP`): 144 pages |
| X'E0'–X'FF' | X'1C000'–X'1FFFF' | The special processor area: Delta and debuggers (`JSPVP`) |

**The overlay window is 6 pages, 3,072 words, ending where the JIT begins.** Every monitor
overlay is linked to run at X'8000' (WRITEMON gives them bias X'4000' dw; [`tape.md`](tape.md)
§1.4), so they all overlap one another, not the user area. For a user, one is mapped at a time;
`T:OVERLAY` changes which (`UB:OV`), and a routine in one overlay that needs another must switch
back afterwards (`T:REMEMBER`). Different users can have different overlays in the window at
the same moment. Program overlays (EDIT's `EDITOV`, `EDITDI`) are the same idea inside the user
area.

**The real sizes**, from `M:MON`'s tree on the tape:

| Segment | Words | Pages |
|---|---|---|
| MON::ORG, the root | 38,840 | 76 |
| UMOV | 7,604 | 14.9 |
| STEPOVR, OPEN, MULOV, MISOV, KEYIN, CLOSE | 3,072 each | 6.0 |
| OPENTP | 3,048 | 6.0 |
| DEBUG | 2,048 | 4 |
| RMAOV, ENQOV, LTAPE, LDLNK | 1,024–1,536 | 2–3 |
| ECBOV | 370 | 0.7 |

- **The designers were up against the window.** Six overlays are exactly 3,072 words and OPENTP
  is 24 words short: code was split to fit.
- **About 29,400 words of overlays** (UMOV aside) run through the 3,072-word window: ten times
  its size, a third again on top of the root.
- **UMOV is larger than the window**, starting at X'8000' and running past the JIT's address, and
  `M:MON`'s start address (X'81DA', in its `HEAD`) is inside it. It is most likely the boot-time
  initialization, run once before there are users. (Inference.)
- **The tape's overlay set isn't the source's**: UMOV, KEYIN and ECBOV are on the tape, not in
  `T$OV.txt`'s list; RTOV, TQOV1 and TQOV2 are in the source and not on the tape.

**Is that expensive?** Less than it sounds. An overlay is a shared processor: one copy in core
serves every user, and using it when it is in core costs a remap, not I/O (`T:OVERLAY`: `PX:HPP`,
`PB:UC`, `PH:FRQ`; nothing at all if it's already mapped, `OVXIT`). The hot paths are resident:
read and write (`CAL11N7`), terminal I/O, M:TYPE, the exits. OPEN, CLOSE, the page calls and the
rarer services are overlaid. Swapping went to a fixed-head RAD with no seek. That the swapper
keeps frequently used overlays in core (`PH:FRQ`) is likely but not traced. Real costs can't be
measured here: the translation's overlay sizes are invented and its swaps instant.

**So yes: the monitor was bigger than its share of the address space, and it relied on the page
map to show each user the overlay they needed, in a fixed window.** The pressure was the
*virtual* space: the user area takes 144 of the 256 pages, and the monitor gets what is left.

**Open:** the root is 38,840 words linked from X'0000' to X'97B7', through the window's and the
JIT's addresses. How it is mapped for each user (part reserved space, perhaps the monitor's own
JIT, the tape's `JIT0`, at X'8C00'; a monitor's map different from a user's) wasn't traced.

### The file system: records and keys in the monitor

Files aren't byte streams ([`files.md`](files.md)):
- **consecutive** files: records in segments;
- **keyed** files: records with keys up to 31 bytes, a master index and a "pyramid" of index levels
  rebuilt at close, granule allocation underneath;
- **random** files: granules addressed directly.

EDIT's line numbers are real keys (X'0003E8' for 1.000); inserting line 1.5 is a keyed write, not a
rewrite of the file. That is an indexed database built into the monitor; VMS's RMS and IBM's
ISAM/VSAM are its cousins. Unix went the other way (byte streams in the kernel, structure in
libraries), and history mostly sided with Unix: SQLite and key-value stores now do in user space
what CP-V did in the monitor. Using EDIT shows what that cost: an editor that never rewrites the
whole file came almost for free.

Protection is by account, password and read/write/execute account lists, kept in VLPs in the file's
FIT: closer to access lists than to Unix's owner/group/other bits.

### The DCB

A DCB, a **data control block**, is the record a program keeps for each I/O stream: the file
descriptor and the `FILE` together, but in the program's own memory ([`dcb.md`](dcb.md)). DCBs
are in the program's DCB section, found by name through `J:DCBLINK`'s table: `M:` names for
system streams (`M:SI`, `M:LO`, `M:UC`, `M:EI`, `M:EO`), `F:` for a program's own files. Two live in
the JIT: `M:UC` and `M:XX`.

The fields we used: word 0's flags (open X'200000', the assignment type `ASN`, VFC X'100'); word 1
the function and a device's label; word 2 `TYC` and the buffer; word 3 the record size and the error
address; word 4 `ARS` and the abnormal address; word 5 the organization; word 6 `FLP`, the VLP list;
word 10 the key buffer; word 11 the CFU. The **VLPs** hold the variable parts: name, account,
password, access lists. Each is a control word (code, words reserved, words used) and data; **a
slot with 0 words used means "not given"**.

How it is used: a program names only `M:SI`; **TEL, `!ASSIGN` or the defaults decide what it is**.
OPEN merges the FPT's parameters into it; each read and write is a CAL naming it, and the monitor
reads and writes its fields in place; CLOSE saves or releases the file.

**The assign/merge record** is where assignments are kept: one 2,048-byte disc record per user,
its address in `J:AMR`. It is a chained list of entries by DCB name from word `:AMHED` (22,
`JIT.txt:246`), plus identity and accounting items (date, user name, log-on time, billing;
`ACCTSUM.txt:229`–`:237`); word 13's SYSID is checked against the user's on every read (A9
otherwise). It is read and written with `CAL1,1 X'2D'`/`X'2E'` through `T:AMRDWT`
(`STPNR.txt:3628`); only a command processor or master mode may write it. `!ASSIGN` (ASSGR) reads
it, replaces the DCB's entry and writes it back (`ASSGR.txt:643`–`:719`, `SUBR.txt:888`–`:953`); TEL
writes it too. When the step starts a program it reads the record into special buffer 2
(`J:ABUF`) and **merges** each entry into the program's DCB of that name (`ASM3`,
`STPNR.txt:2648`). TEL logs a user off if there is none (`TEL.txt:296`). The translation has no
assign/merge record yet; `SHOW DCBS` stops at X'2D'.

**Is the DCB a good abstraction?** The idea at its heart is sound and outlived CP-V: **logical
stream names in the program, bound late by the user or operator**, with one interface for every
device and file. Unix's stdin/stdout/stderr with redirection, IBM's DD statements and today's
container volume mounts are the same idea. The implementation aged badly:
- **It lives in the program's memory, and the monitor trusts it.** Every CAL has to defend itself
  against a corrupted DCB (`DCBCHK`, the checks throughout IORT), and the layout became a binary
  interface that could never change.
- **One block does too many jobs**: the name binding (VLPs), the open-file state (CFU, position,
  key), buffering and record size, and the parameters of the request in progress. Modern systems
  split these: a path, a kernel-side open file, user-side buffering, per-call arguments.
- **Three sources of truth to merge**: the DCB as assembled, the assign/merge record, and OPEN's
  FPT, with precedence spread over the code (`CHKASN`, `MSROPN09`, the VLP merge).
- **Static and positional**: laid out at link time, a fixed set, VLP slots reserved in advance,
  "0 words used" standing in for optional parameters.

With 128K words and no room for per-user state in the monitor, putting it in the user's space
was a reasonable trade then. It is the opposite of what we'd choose now.

### The program–monitor interface

The most dated part, and where most of our bugs were. Programs talk to the monitor through
structures in their own memory: the DCB, and the JIT at a fixed virtual address, where they read
`J:CCBUF`, `M:UC`'s ARS and `J:EXTENT` directly, and where exit control (`M:XCON`), trap control
(`M:TRAP`) and BREAK (`M:INT`) keep their state. Real programs bake those offsets in when they
are assembled, so the layout is a rigid ABI. Modern kernels hand out opaque handles, keep state
private and version their calls. Several CP-V ideas survive in modern form:
- the JIT: a thread environment block, or Linux's vDSO;
- `M:XCON`: `atexit` crossed with a signal handler; `M:TRAP`: signals; `M:INT`: SIGINT;
- COC, the terminal handler in the monitor: a tty line discipline;
- DCB assignment: file-descriptor redirection.

### Processes and programs

No `fork`/`exec`. A job is a sequence of steps; a program replaces itself with `M:LDTRC` or calls
another with `M:LINK`. Overlay trees with `M:SEGLD` let a program larger than memory run at all.
Shared processors (TEL, LOGON, libraries) are mapped into users, not separate processes. LOGON is
both log-on and log-off: a processor ends a session with `M:LDTRC LOGON` (EDIT's `BYE`), and the
step code, seeing LOGON, deletes the user (`STEP10`). One thread per user; carefully engineered for
its constraints, without the composability that made Unix pipelines possible.

### Overall

A well-engineered, very tightly coupled system for its machine. Its record-structured file
system and interactive design were sophisticated for 1970. Its coupling, an ABI made of memory
layout and control flow made of tables, is what modern design moved away from, and we felt it
directly in the bugs.

## Part 2: lessons from running the real programs

### The source isn't the system on the tape

The `c00co` source is a **UTS** monitor (`SYSTEM UTS`); the tape is **CP-V**. They differ, and the
real programs follow the tape:
- **The JIT has 4 more words** between `TMPDCPK` (word 73) and `TSTACK` in CP-V. Words 0–73 match
  the source; everything from `TSTACK` on is 4 words later (`J:CCBUF` 204, not 200; `M:XX` 234).
  It came out by counting which JIT addresses TEL, SHOW, EDIT and LOGON actually use. Until it was
  fixed, SHOW complained about its command line, PCL quit, and EDIT's BUILD returned at once
  ([`jit.md`](jit.md) §1).
- **The tape's EDIT isn't the source's EDIT.txt** (the tape's has `M:LDTRC` for BYE and OFF; the
  source has none); we read the load module instead.
- **The tape's monitor overlays aren't the source's list** (above).
- **The tape's `JIT0` is yet another JIT layout** (`M:UC` at word 46), so it isn't the user JIT.

**Lesson:** when the source and the binaries disagree, the binaries are the truth about the
system that ran, and their instruction addresses are evidence: a histogram of the JIT words a
dozen processors address settled the layout.

### Our own documentation can be the bug

coc.md once said a record without VFC "starts on a new line". The source (`COCWR38`, `COCWR80`)
says otherwise: no new line before a record, **none after it on `M:UC`**, a CR LF after it on
other DCBs unless it ends in a new-line character, trailing blanks dropped if more than 3. EDIT,
which writes a line and then an NL as a record of its own, printed a blank line after every line
until it was fixed. The stand-ins (LOGON, TEL) had been written to suit the wrong rule.

**Lesson:** a paraphrase of the source that isn't checked against it becomes a fact everything else
is built on. Re-read the source when a real program disagrees with the documentation.

### An assumption flagged as assumed is still a bug waiting

The M:WRITE flags NEWKEY and ONEWKEY were placed at X'08' and X'04', marked "positions assumed".
They are bits 26 and 25 (X'20', X'40'; `BPM.txt`'s `M:WRITE` procedure, :598–:602). Every line EDIT
wrote was refused (X'13') and its files stayed empty. The FPT layouts were in `BPM.txt` all along;
the WAIT bit's position, also an open question, was confirmed there at the same time.

**Lesson:** look for the macro definitions (`BPM.txt`'s procedures) before inferring a layout from
shift counts; and revisit the assumptions list when something fails without explanation.

### What a program can see, it will read

Wherever the translation kept monitor state only on the Python side, a real program saw stale
memory:
- **`M:UC`'s ARS.** The monitor kept `M:UC` as an object; EDIT reads the record length from the
  DCB's word 4, saw 0, and rejected every command.
- **The key buffer.** EDIT reads a record's line number from the DCB's key buffer (KEYTRAN).
- **The default account.** OPEN's CHKFLACN writes `J:ACCN` into the DCB's account VLP; SHOW and
  EDIT print it from there.
- **The JIT** itself, rebuilt at program start, and **J:USENT, J:EXTENT, J:TCB** kept in the page.

**Lesson:** the program-visible state is the real interface. It wants one systematic layer that
owns it and writes it back at defined points, rather than fixes added one bug at a time.

### "Not given" has to be modeled exactly

A VLP slot with 0 words used means "not given". Treating EDIT's empty protection slots as empty
access lists made its files unreadable by their owner (X'14'). The same convention decides
whether the account is supplied.

### Every fix a real program needs is two

Nearly every stop was a missing service, and translating it exposed a mistake behind it:
- M:TRAP and M:XCON exposed that TEL's `TIC` stayed set while a user program ran, so every program
  was treated as TEL (including at CAL1,6's privilege check).
- M:SEGLD worked first time on SORT and AP; EDIT then needed M:DISASSOC, M:TS, and the terminal
  record's NL counted in the ARS (`MUCRLFNL`).
- M:PRECORD exposed TRN, the "positioned one record before" flag (`RDF.txt:392`).

### Tools that made it tractable

- **A sweep** of every load module on the tape at a terminal, ranking what stops them, chose the
  next service each time.
- **Instruction traces** of a program between two CALs, and logs of its reads of the JIT or the
  monitor, found the causes (the ARS of 0, the JIT shift).
- **Disassembling the load module** found what the source didn't have: EDIT's command table and
  its `M:LDTRC LOGON`.
- **Small assembled test programs** written as real load modules made each fix testable.

### On reimagining the monitor

The internals could be rewritten freely: overlays are already bookkeeping in the translation;
swapping could be demand paging; the scheduler could be anything; files could live in host files
or SQLite; the DCB could be monitor-side state with only its visible fields kept in step. What
must stay is everything a program can see: the CAL interface down to which CC bits change, the
FPT and DCB layouts, the JIT offsets, record formats, the memory map. That is how Wine runs
Windows binaries and how IBM's mainframes still run 1960s programs. For this project the
documentation's value is that it describes CP-V faithfully, so the recommendation is to keep the
translation faithful, tidy the program-visible state into one layer, and leave a reimagined
monitor for a separate project built on the docs.

## Open questions

- How the 38,840-word root is mapped for each user (above).
- The SYSGEN values: quanta, limits, `MODE4INIT`, the terminal type.
- What the 4 extra words in CP-V's JIT hold.
- Whether the swapper keeps hot overlays in core by `PH:FRQ`.
- `PAGEZAP`'s privilege test ([`pages.md`](pages.md)).
