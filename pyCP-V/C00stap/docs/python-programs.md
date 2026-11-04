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

A service error raises `cpv.CpvError` with the CP-V code. For example, X'43' is a missing key and
X'16' is NEWKEY on an existing key. End of file ends the iteration.

## Deviations from CP-V

| Area | CP-V | Here | Why |
|---|---|---|---|
| What a program is | A load module (`LMN`): Sigma machine code, built by LOAD/LINK | Python source, compiled when the ghost starts | No instruction emulator (decided 2026-11-02) |
| Where it's kept | A load-module file in the account | A **keyed file** in the account, keyed like an EDIT file: the line number × 1000 as a 3-byte binary key, `KEYM` = 3 (`EDIT.txt:495`, `:1524`) | Keyed files are translated; consecutive files aren't yet |
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
| Files open when a run ends | Lost with the monitor's memory; at the next start-up, FIX1 repairs the files (HGP reconstruction) | The image is saved as the disc stands, open or not. A file never closed isn't in its directory, so its granules are lost to the free list | FIX1's repair isn't run at start-up |
| A tape boot onto a disc with files | Decided by GHOST1's `PASS0`/`RECOVER2` path (not read) | The files are kept: the tape boot rewrites the swap disc's monitor only. Delete the image file to start with an empty disc | Not read yet |
| Accounts | Created by SUPER | `:SYS` exists at boot; `--file` creates other accounts as needed | SUPER not read |
| A failed load | The step code's own messages (not read) | `nn: LOAD NAME: <error>` typed on the console, then `M:XXX` | Invented |
| The ID on a ghost's lines | `MSRTYPE` types `J:JIT`'s ID ([`rdwr.md`](rdwr.md) §3) | The user number | `J:JIT`'s ID wasn't traced |
| Time while the operator types | Real time; the system keeps running | After each key-in, the scheduler runs for **10 seconds** of simulated time (5000 clock units, the same 10 s the I/O clock already allows per key-in), then waits for the next key-in. A program that sleeps longer resumes during later key-ins | The console is a script |
| A reserved slot that logs off | (T:DELUS not read) | Ghosts in reserved slots (below `MING`, such as KEYIN) leave the null queue when they log off, since `ADDGJOB` links them in again when they next start | Found as a bug: KEYIN's user was being reused by the next ghost |
| Stopping a program | The monitor deletes the user; its pages go away | `T:DELUS` closes the user's generators, and the bridge tells the program's thread to stop (`Killed`) | Threads must be stopped explicitly |

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
- **the public disc**: the granules in use, byte for byte, the free list, and the account
  directory's address. In CP-V that address is `ACNCFU`'s `FDA`, set at start-up in a way not
  read yet. The free list stands in for the allocation tables (HGP) that the real disc carries
  ([`files.md`](files.md) §8).

The files also stay with the machine within a run. A crash recovery, `--reboot` or the shutdown's
reboot mounts the same file system again (`FileSystem.mount`) instead of making a new one.

## Open points

- **Threads and the scheduler**: switching happens only at service calls, so the scheduler's
  quantum and preemption decisions take effect at the next call, not mid-computation. A
  `cpv.compute(n)` call can charge n clock units of CPU time explicitly.
- **A program that loops without calling a service** hangs the whole system. There is no guard.
- **Python's own power**: a program can do anything Python can, outside the simulation (files,
  network). It is a local tool.
