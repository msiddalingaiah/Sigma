# Python programs as ghost jobs

The translation can run **Python programs as CP-V ghost jobs**. The operator types `GJOB NAME`
on the console, and the monitor starts a ghost whose "load module" is a Python source file of
that name in the CP-V file system. Every service the program asks for is a real CAL through the
translated dispatch, overlays, file system and I/O, and the program runs only when the translated
scheduler gives it the processor.

This layer is **not a translation**. It is new design that stands in for the parts of CP-V that
load and run programs (the step code, the loader, the program's own machine code). This document
describes it and, most of all, **keeps track of every place it departs from the real system**.

> Code: `python/uts/pyprog.py` (the loader stand-in, the `cpv` library, the thread bridge),
> `python/uts/keyin.py` (`KIGJOB`, translated), `python/uts/__main__.py` (`--file`, `--disc`),
> `python/uts/image.py` (disc images). The key-in
> is described from the source in [`keyin.md`](keyin.md) §6.

## How it fits together

```
!GJOB HELLO              operator key-in (translated: KIGJOB, KEYN.txt:715)
   │
KEYIN ghost ─► T:GJOBSTRT "HELLO", :SYS ─► a ghost slot, a user, ADD1 (translated)
   │
the new ghost's first step ─► LOAD: open HELLO.:SYS, read its records in key order,
   │                          compile them as Python                       ◄── stand-in
   │
main(cpv) runs in its own thread; each cpv.xxx() call is one CAL1, handed to the
   scheduler, which runs it as the ghost's CAL (translated) and hands back the result
   │
return ─► CAL1,9 1 (M:EXIT) ─► the ghost logs off        exception ─► message, M:XXX
```

## A program

```python
def main(cpv):
    cpv.type("HELLO OPERATOR")              # M:TYPE: on the console as "nn: HELLO OPERATOR"
    f = cpv.open("PARTS", fun="OUT")        # M:OPEN on a file DCB
    f.write("P0001", b"first part")         # M:WRITE by key (ONEWKEY)
    f.close()                               # M:CLOSE
    who = cpv.keyin("WHO ARE YOU?")         # M:KEYIN: ask the operator, read the reply
    cpv.wait(2)                             # M:WAIT
    for key, data in cpv.open("PARTS"):     # M:READ, next record after KBUF, to end of file
        cpv.type(key + " " + data.decode())
```

**Run from a terminal** (TEL, [`online.md`](online.md)), the same program talks to the user's
terminal: `cpv.type` writes on `M:UC`, `cpv.keyin` asks at the terminal, and two more calls read
it:

```python
    cpv.prompt("?")                         # M:PC: COC sends '?' at the start of each read
    name = cpv.readline()                   # M:READ on M:UC: waits for the line (COCIO)
```

`readline` is for on-line users only. A ghost has no line.

A service error raises `cpv.CpvError` with the CP-V code. For example, X'43' is a missing key and
X'16' is NEWKEY on an existing key. End of file ends the iteration.

A key is text or **bytes**. Text keys are stored in EBCDIC, as CP-V's are. A bytes key is
stored exactly as given, so binary keys such as EDIT's 3-byte line keys work. `cpv.line_key(n)`
makes one: the line number times 1000 (`EDIT.txt:495`). With `binary_keys=True`, iteration and
`next()` give keys back as bytes:

```python
    f = cpv.open("LINES", fun="OUT", keym=3)
    f.write(cpv.line_key(10), "LINE TEN")   # key X'002710'
    f.close()
    for key, data in cpv.open("LINES", binary_keys=True):
        cpv.type(key.hex() + " " + data.decode())
    src = cpv.open("HELLO", account=":SYS", binary_keys=True)   # an imported program
    line = src.read(cpv.line_key(1)).decode(cpv.EBCDIC)         # its lines are EBCDIC
```

`examples/mkedit.py` makes an EDIT-style file, POEM, with EBCDIC lines and a line inserted at
2.500. From a terminal, `COPY POEM TO ME(K)` then lists it with EDIT numbers ([`online.md`](online.md)).

Keys sort as bytes, so EDIT keys come back in line order. A bytes key works because memory holds
characters and KEYTRAN encodes them to EBCDIC (`cal._key`): `cpv` stores the key as
`key.decode(cpv.EBCDIC)`, which the encoding turns back into the same bytes. cp037 maps all 256
values one to one.

A **consecutive file** ([`files.md`](files.md) §4) has records in order and no keys:

```python
    log = cpv.open("LOG", fun="OUT", org="consec")   # a new consecutive file
    log.write("FIRST LINE")                 # M:WRITE without a key: after the current record
    log.close()
    for data in cpv.open("LOG"):            # M:READ: the next record, to end of file
        cpv.type(data.decode())
```

A **random file** ([`files.md`](files.md) §6) is a fixed number of granules, read and written by
granule number:

```python
    t = cpv.open("TABLE", fun="OUT", org="random", size=10)   # ten granules
    t.write("A" * 2048, gran=3)             # M:WRITE at granule 3; t.granule is then 4
    data = t.read(gran=3, size=4096)        # M:READ: granules 3 and 4
```

Without `gran`, a request continues where the last one ended. A granule past the end is
`CpvError` X'42', and a request cut short by the end of the file is X'44'.

**Protection** ([`files.md`](files.md) §10). `open` takes the account a file is in (default:
the program's own), a `password`, and, for a new file, the account lists `read`, `write` and
`execute` (accounts, `"ALL"` or `"NONE"`) and an execute `vehicle`. OPEN checks them as `SECCHK`
does: a refusal is `CpvError` X'14'. A program may create files only in its own account.

```python
    f = cpv.open("LEDGER", fun="OUT", password="SESAME", read=["ALPHA"])   # in :SYS
    ...
    f = cpv.open("LEDGER", account=":SYS", password="SESAME")           # from ALPHA: read only
```

Any file is deleted by closing it with `close(release=True)`, which is `M:CLOSE` with the
disposition REL, as a CP-V program would do ([`files.md`](files.md) §9). It is ignored while another
DCB has the file open.

`read(size=2048)` returns the next record, or `None` at the end of the file. A record longer than
`size` raises `CpvError` X'07' (lost data). `delete()` deletes the record just read (`M:DELREC`).
A write before the end of the file cuts the file at that point first, as CP-V does.

## Deviations from CP-V

| Area | CP-V | Here | Why |
|---|---|---|---|
| What a program is | A load module (`LMN`): Sigma machine code, built by LOAD/LINK | Python source, compiled when the ghost starts | No instruction emulator (decided 2026-11-02) |
| Where it's kept | A load-module file in the account | A **keyed file** in the account, keyed like an EDIT file: the line number × 1000 as a 3-byte binary key, `KEYM` = 3 (`EDIT.txt:495`, `:1524`) | Load modules aren't modeled |
| Loading | The ghost's first job step: the step code (`STEP`/`STPNR`) and the loader read the load module into the user's pages | `pyprog.load`, run as the ghost's first action. It reads the file through the file system directly (not through CALs, as monitor code would) and compiles it | The step code and the loader haven't been read |
| Memory | The program's code and data live in its pages, which are swapped | The Python objects live in Python. The pages are only counted (`UB:PCT`), and the CAL parameter areas (FPTs, buffers, keys) are in the user's small word memory | No machine to hold them |
| Running | The CPU executes it; any instruction can be interrupted, and the quantum ends at the clock | A thread per program. It runs only between service calls, and **each service call is a yield**, a switch point | No emulator. Agreed as good enough: a program that never calls a service holds the system |
| Service calls | `CAL1,n FPT` instructions with FPTs the program assembled | `cpv.xxx()` builds the FPT and the CAL1, and the translated dispatch takes it from there | — |
| Results | Condition codes, and the error/abnormal routines in the FPT | `cpv` always passes error and abnormal addresses, and turns a call to them into `CpvError(code)` | Python exceptions instead of branch addresses |
| End of a program | The program does `M:EXIT` (or `M:ERR`, `M:XXX`) | Returning from `main` does `M:EXIT`; an uncaught exception types a message on the console and does `M:XXX` | — |
| Input | A ghost asks the operator with `M:KEYIN` (`MSRKEYIN`, [`rdwr.md`](rdwr.md) §8): the message is typed, then a console read waits for the reply | The same, translated: `cpv.keyin(question)` returns the reply. Several ghosts asking are served one at a time through IOQ | — |
| The operator's reply | Typed on the console while the read is pending; with no reply, the read times out after 60 s and the reply is empty | The next line of the console script (`--keyins`), or what you type with `-i`. While a question is pending, the next line is its answer, not a key-in (a key-in needs INTERRUPT on the real console too). A read starts and completes at once, so the timeout never runs; when the script has no more lines, the reply is empty, as a timeout would give | The console is a script |
| Asking on a terminal | An on-line user's `M:KEYIN` goes to their `M:UC` | Not translated (`NotTranslated`) | Terminals (COC) aren't translated |
| Resources (`GJOB NAME,RESOURCE`) | The resource index goes into the task's `M:UC` | Not supported: the key-in answers `EH?` | The resource tables aren't modeled |
| Getting source onto the disc | An editor, a card reader, a tape | A host-side import: `python -m uts --file host.py=NAME[.ACCOUNT] ...`. With `--disc`, once is enough | No editor, symbionts or card input |
| Files between runs | The discs stay on their drives | Only with `--disc PATH`: the swap and public discs are saved to a host file when the run ends and loaded when the next one starts (see "Disc images"). Without it, every run starts with empty discs | Python objects, not drives |
| Files open when a run ends | Lost with the monitor's memory; at the next start-up, FIX1 repairs the files (HGP reconstruction) | The image is saved as the disc stands, open or not. A file never closed isn't in its directory, so its granules are lost: neither free nor in a file | FIX1's repair isn't run at start-up |
| A tape boot onto a disc with files | Decided by GHOST1's `PASS0`/`RECOVER2` path (not read) | The files are kept: the tape boot rewrites the swap disc's monitor only. Delete the image file to start with an empty disc | Not read yet |
| Organization of a file | The DCB's `ORG` field, set by the program's DCB or OPEN parameters | `cpv.open(..., org="consec")` makes a new file consecutive; the default is keyed. An existing file keeps its own organization, and the DCB follows it | How OPEN treats a DCB whose `ORG` differs from the file's wasn't traced |
| Deleting another account's file | Opened IN, only with privilege X'C0' or more (`CLS.txt:1528`–`:1533`) | The same (translated) | — |
| A ghost's account and privilege | Set up when the ghost is started (not traced) | The account of `GJOB NAME.ACCOUNT` (`:SYS` by default), and privilege 0, so OPEN's checks apply to it ([`files.md`](files.md) §10) | A ghost's `JB:PRIV` wasn't traced |
| OPEN's checks on a file already open | (The CFU-scan path wasn't traced) | `SECCHK` runs on every open, also when the file's CFU is already open | Not traced |
| Waiting for a granule | A program whose granule stack is empty waits (`E:QFAC`) until ALLOCAT has run and been swapped out | It gets its granule at once: ALLOCAT's fill and the commit run inside the program's CAL | The file code can't be suspended in mid-CAL |
| Accounts | Created by SUPER | `:SYS` exists at boot; `--file` creates other accounts as needed | SUPER not read |
| A failed load | The step code's own messages (not read) | `nn: LOAD NAME: <error>` typed on the console, then `M:XXX` | Invented |
| The ID on a ghost's lines | `MSRTYPE` types `J:JIT`'s ID ([`rdwr.md`](rdwr.md) §3) | The user number | `J:JIT`'s ID wasn't traced |
| Time while the operator types | Real time; the system keeps running | After each key-in, the scheduler runs for **10 seconds** of simulated time (5000 clock units, the same 10 s the I/O clock already allows per key-in), then waits for the next key-in. A program that sleeps longer resumes during later key-ins | The console is a script |
| A reserved slot that logs off | (T:DELUS not read) | Ghosts in reserved slots (below `MING`, such as KEYIN) leave the null queue when they log off, since `ADDGJOB` links them in again when they next start | Found as a bug: KEYIN's user was being reused by the next ghost |
| Stopping a program | The monitor deletes the user; its pages go away | `T:DELUS` closes the user's generators, and the bridge tells the program's thread to stop (`Killed`) | Threads must be stopped explicitly |

## Machine code instead

A ghost can also be **real Sigma machine code**, run by the user-mode interpreter
([`interpreter.md`](interpreter.md)). An assembly source given to `--file` (`.s` or `.asm`) is
assembled by `python/uts/asm.py` and stored as an absolute image. `GJOB NAME` then runs it
instruction by instruction, and its `CAL1`s go to the same translated monitor:

```
python -m uts --replies 06/15/76 13:45 N --file hello.s=HELLO --keyins "GJOB HELLO"
```

`examples/guests.s` is a visitors' book in machine code. It asks the operator's name with
`M:KEYIN` and appends it to a consecutive file through its own DCB ([`dcb.md`](dcb.md)), then
types every name so far. With a disc image the book grows from run to run:

```
python -m uts --disc book.json.gz --replies 06/15/76 13:45 N --file examples/guests.s=GUESTS --keyins "GJOB GUESTS" ADA
python -m uts --disc book.json.gz --replies 06/16/76 09:00 N --keyins "GJOB GUESTS" GRACE
```

## Running one

```
python -m uts --replies 06/15/76 13:45 N --file examples/hello.py=HELLO --keyins "GJOB HELLO"
python -m uts -i --console --replies 06/15/76 13:45 N --file examples/hello.py=HELLO
                                  (then type GJOB HELLO at the ! prompt)
```

`examples/ask.py` asks the operator two questions with `M:KEYIN`:

```
python -m uts --replies 06/15/76 13:45 N --file examples/ask.py=ASK --keyins "GJOB ASK" MADHU 3
```

`examples/hello.py` types the time, writes and reads a keyed file, and shows a `CpvError`. The
tests are `python/tests/test_pyprog.py`.

## Disc images

`--disc PATH` keeps both discs in a host file between runs, so programs are imported once and
the files they write are there in the next run:

```
python -m uts --disc sys.json.gz --replies 06/15/76 13:45 N --file examples/hello.py=HELLO --keyins "GJOB HELLO"
python -m uts --disc sys.json.gz --replies 06/16/76 08:00 N --keyins "GJOB HELLO"
```

If `PATH` doesn't exist, the run makes the discs as usual (a disc boot installs from tape first)
and saves them. If it does, a disc boot reads the monitor that an earlier run's `WRTROOT` wrote
(boot type 3, RAD boot, with no install), and `--tape` installs onto it, keeping the files.
The image is saved at the end of every run that booted, including one that stops at code that
isn't translated.

The image (`python/uts/image.py`) is gzipped JSON: about 10 KB, against about 490 KB
unzipped, since most of the disc is zeros. `gunzip` (or 7-Zip) gives the readable file, and a
plain JSON image loads too. It holds:

- **the swap disc**: its sectors, and the root variables attached to the root's first sector
  (`python/README.md`, "Root variables on disc");
- **the public disc**: the granules in use, byte for byte, the allocation table (the HGP bit
  map and where its last get stopped), the stack of free addresses, and the account directory's
  address ([`files.md`](files.md) §8). In CP-V that address is `ACNCFU`'s `FDA`, set at start-up
  in a way not read yet. The stack is in the monitor's memory on a real system. ALLOCAT has a
  request that empties every stack into the maps (`QUIESCE`, `ALLYCAT.txt:310`); who sends it
  wasn't traced. The image keeps the stack as it is. An image from before
  the bit map (version 1, with a free list) loads with its free granules as the map's set bits.

The files also stay with the machine within a run. A crash recovery, `--reboot` or the shutdown's
reboot mounts the same file system again (`FileSystem.mount`) instead of making a new one.

## Open points

- **Threads and the scheduler**: switching happens only at service calls, so the scheduler's
  quantum and preemption decisions take effect at the next call, not mid-computation. A
  `cpv.compute(n)` call can charge n clock units of CPU time explicitly.
- **A program that loops without calling a service** hangs the whole system. There is no guard.
- **Python's own power**: a program can do anything Python can, outside the simulation (files,
  network). It is a local tool.
