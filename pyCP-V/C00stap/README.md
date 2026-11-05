# C00stap: Xerox UTS / CP-V monitor source

Assembler source for the Xerox UTS (CP-V) operating system for the Sigma 7, Sigma 9 and
Xerox 560, plus documentation of it and a runnable Python translation of the parts documented
so far: the SYSGEN system tape and its install, the disc boot, crash recovery, and the operator
console key-ins, up to a shutdown.

| Directory | Contents |
|---|---|
| `c00co/` | Monitor source modules (`.txt`, Meta-Symbol assembler). |
| `c00si/` | Further source files. |
| `docs/` | Documentation of the code. [`docs/status.md`](docs/status.md) says where the project stands and what's next. Start with [`docs/boot.md`](docs/boot.md) for the boot process; [`docs/tape.md`](docs/tape.md) covers the system tape format and boot-time patching, [`docs/recovery.md`](docs/recovery.md) crash recovery, [`docs/keyin.md`](docs/keyin.md) operator key-ins, and [`docs/io.md`](docs/io.md) monitor I/O (IOQ and the device handlers). |
| `python/` | The Python translation (package `uts`). Internals are in [`python/README.md`](python/README.md). |

## Running the Python translation

### 1. Start Anaconda and activate the environment

The code needs Python 3.11 or later, and uses the miniconda environment **`p3.13`**
(Python 3.13, with pytest). Python is not on the system PATH, so start from an Anaconda
prompt or activate the environment yourself.

**Option A: Anaconda PowerShell Prompt (simplest).**
Open **Start → Anaconda (miniconda3) → Anaconda PowerShell Prompt**, then:

```powershell
conda activate p3.13
cd C:\Users\madhu\Documents\github\Sigma\pyCP-V\C00stap\python
```

**Option B: an ordinary PowerShell window.**
Set conda up for PowerShell once:

```powershell
C:\ProgramData\miniconda3\Scripts\conda.exe init powershell
```

Close the window and open a new one. From then on, every PowerShell window can do:

```powershell
conda activate p3.13
cd C:\Users\madhu\Documents\github\Sigma\pyCP-V\C00stap\python
```

If `conda init` reports that running scripts is disabled, allow scripts for your user
once and then open a new window:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**Option C: no activation.** Call the environment's Python by its full path. The `&`
is PowerShell's call operator:

```powershell
cd C:\Users\madhu\Documents\github\Sigma\pyCP-V\C00stap\python
& C:\Users\madhu\.conda\envs\p3.13\python.exe -m uts -i
```

To check you have the right Python, run `python --version`. It should report 3.13.

### 2. Boot the monitor

There are two kinds of boot:

- **Disc boot** (the default): `DBOOT` → `INITIAL` → `MONINIT` → page-pool setup → handoff
  to the scheduler `T:SE`. The disc has to hold an installed system, so the program first
  does a quiet tape install with default answers, then boots from the disc that install
  wrote.
- **Tape boot** (`--tape`): WRITEMON writes a system tape. Then `MTBOOT` → `INITIAL` →
  `MONINIT` → `TBOOT:` installs the system on the swap disc (segments, RECOVER, XDELTA,
  the root in three parts, and `DBOOT` in sector 0), and the boot carries on to `T:SE`.

Each run prints the console transcript and a summary of the resulting system state.

**Interactive:** you answer the operator's questions yourself.

```powershell
python -m uts -i            # disc boot
python -m uts -i --tape     # tape boot
```

A disc boot asks:

```
DATE(MM/DD/YY)=          e.g. 06/15/76   (years 70-99)
TIME(HH:MM)=             e.g. 13:45
DO YOU WANT DELTA (Y/N)  Y keeps XDELTA (the debugger) resident
```

A tape boot asks first for the options (`ENTER ANY OF:` I, P, F, T, C, D; Enter means T),
then date and time. With the I option it also asks `C/LL/DC ASSIGN OK (YES/NO)` (only
`YES`, `NO` or Enter is accepted), shows the creation-data record, and waits at the sense
switch reminder for Enter. Answering `NO` prompts for each device (`CRA03 => `). Reply
`SA` to keep it, or give a new address such as `A04`.

An invalid answer gets ` ??` and you type it again. Pressing Enter with nothing typed is
the same as the console's 10-second timeout.

**Scripted:** the replies are given on the command line, in order.

```powershell
python -m uts --replies 06/15/76 13:45 N
python -m uts --tape --replies IP 06/15/76 13:45 YES -
```

### Options

| Option | Meaning | Default |
|---|---|---|
| `-i`, `--interactive` | Read console replies from the keyboard. | off |
| `--replies R1 R2 …` | Console replies, in order. `-` means Enter. | none |
| `--machine {sigma7,sigma9,x560}` | Machine type that `MONINIT` detects. | `sigma9` |
| `--memory N` | Installed memory in K words (the code probes for it). | `128` |
| `--sense N …` | Sense switches that are set (1–4). `--sense 3` requests operator recovery. | none |
| `--realtime` | SYSGEN as a real-time system: adds the `RESET RESDF YYY,XXXXX ?` prompt. | off |
| `--tape` | Tape boot: install from a WRITEMON tape. | off |
| `--reboot` | With `--tape`: after the install comes up, disc-boot from the disc it wrote, using the remaining replies. | off |
| `--keyins K1 K2 …` | After the boot comes up, operator key-ins typed at the `!` prompt, in order. `-` is an empty line. | none |
| `--console` | With `-i`: after the boot comes up, an interactive key-in session. End of input ends it. Any `--replies` answer the boot questions first. | off |
| `--print LINE …` | Lines the monitor prints on the line printer (through IOQ) before the key-ins. | none |
| `--lp-fault FAULT[:N] …` | Make the line printer fail N times (default 1): `notop` (not operational), `manual`, `error`, `parity` (code disc), `hang` (times out). | none |
| `--crash CC[-SS]` | After the boot comes up, `SCREECH` with this hex code and subcode: recovery, core dump, reboot from disc. | off |
| `--oprec` | After the boot comes up, operator recovery: sense switch 3 and a disc boot. | off |
| `--patches FILE` | Patch deck for WRITEMON's `M:PATCH`, one card per line. | none |
| `--version V` | WRITEMON's 4-character version, which `SYSVERS` is built from. | `C00 ` |
| `--trace` | Print a trace of the boot steps, and the LP output. | off |
| `--file HOST=NAME[.ACCOUNT] …` | Import Python programs into the CP-V file system before the key-ins. Start one with the key-in `GJOB NAME`; see `docs/python-programs.md`. | none |
| `--restore TAPE.tap …` | Restore the files of CP-V labeled tapes (simh `.tap` images) into the file system, in the tape's account. See `docs/labtape.md`. | none |
| `--terminals N` | After the boot comes up (and any `--keyins`), N terminal lines on a TCP port, in real time: connect with `telnet` to log on and use TEL. Ctrl-C ends. See `docs/online.md`. | off |
| `--port P` | The terminals' TCP port. | `2323` |
| `--bind ADDRESS` | The address the terminals listen on. There is no authentication: only for trusted networks. | `127.0.0.1` |
| `--sched` | Instead of a boot, run the scheduler demo: three ghosts and an on-line user on 12 pages, with the scheduler's trace. | off |
| `-h`, `--help` | Show the options. | |

### Examples

```powershell
# Standard boot on a Sigma 9 with 128K words
python -m uts --replies 06/15/76 13:45 N

# Xerox 560 with 96K words, keep XDELTA, show the boot trace
python -m uts --machine x560 --memory 96 --replies 06/15/76 13:45 Y --trace

# Bad answers are re-asked: the first date and first time are rejected
python -m uts --replies 02/29/77 02/29/76 25:00 9:05 N

# Real-time system: reserve 5 RESDF pages starting at X'10000'
python -m uts --realtime --replies 5,10000 06/15/76 13:45 N

# Operator key-ins on the running system: set the time and date, allow 10 batch users,
# and one bad key-in (EH?)
python -m uts --replies 06/15/76 13:45 N --keyins "T 14:30" "D 6/16/76" "ONB 10" HELLO

# A printer that isn't operational: the monitor types LPA02 NOT OPERATIONAL, and the
# operator's LPA02,R retries the print, which then goes through
python -m uts --replies 06/15/76 13:45 N --print "HELLO PRINTER" --lp-fault notop --keyins "T 14:30" "LPA02,R"

# A printer that hangs: TIMED OUT after 5 seconds, then retried
python -m uts --replies 06/15/76 13:45 N --print "HELLO PRINTER" --lp-fault hang --keyins "T 14:30" "LPA02,R" --trace

# Shut the system down: ZAP, then the scheduler's idle check issues SCREECH X'404'
python -m uts --replies 06/15/76 13:45 N --keyins "T 14:30" ZAP --trace

# Interactive operator console with the date and time already set: the boot questions are
# answered from --replies (date, time, no XDELTA), then you type key-ins at the ! prompt.
# End with Ctrl-Z then Enter.
python -m uts -i --console --replies 06/15/76 13:45 N

# The same, but answering the boot questions yourself too
python -m uts -i --console

# Crash the running system with SCREECH 2E-03: RECOVER dumps memory and reboots
python -m uts --replies 06/15/76 13:45 N --crash 2E-03 --trace

# Operator recovery of the running system (sense switch 3, boot from disc)
python -m uts --replies 06/15/76 13:45 N --oprec

# Sense switch 3 on a cold machine: there is no monitor in memory to recover, so it stops
python -m uts --sense 3

# The scheduler on its own: quantum ends, a woken sleeper preempting, swaps when memory runs
# out, an on-line user waiting for I/O, and SCREECH X'404' when the last user ends
python -m uts --sched

# A Python program as a ghost job: imported into :SYS, started by the operator's GJOB
python -m uts --replies 06/15/76 13:45 N --file examples/hello.py=HELLO --keyins "GJOB HELLO"

# The same with a disc image: the discs are saved to sys.json.gz, and the next run disc-boots
# from it with HELLO and its files still there
python -m uts --disc sys.json.gz --replies 06/15/76 13:45 N --file examples/hello.py=HELLO --keyins "GJOB HELLO"
python -m uts --disc sys.json.gz --replies 06/16/76 08:00 N --keyins "GJOB HELLO"

# Sigma machine code (the user-mode interpreter): a visitors' book kept in a file
python -m uts --disc book.json.gz --replies 06/15/76 13:45 N --file examples/guests.s=GUESTS --keyins "GJOB GUESTS" ADA

# On-line users: two terminal lines on localhost port 2323. In another window, telnet
# localhost 2323, log on with any ACCOUNT,NAME, then at TEL's ! type HELLO, LIST or OFF.
python -m uts --replies 06/15/76 13:45 N --file examples/hello.py=HELLO --terminals 2
```

```powershell
# Install from tape with console and printer output, then boot the installed disc
python -m uts --tape --reboot --replies IP 06/15/76 13:45 YES - 06/16/76 08:00 N --trace

# Install with a patch deck. Storing a patch needs XDELTA's evaluator, which isn't
# translated, so the boot stops at the first real patch and names its segment.
python -m uts --tape --patches deck.txt --replies - 06/15/76 13:45
```

When a boot reaches code that isn't translated yet (a `:` command, storing a patch, a
single-user abort, or the scheduler), it stops with a `--- boot stopped: … ---` line saying where. A successful run
ends with `--- boot up ---`.

In `--replies`, a single `-` stands for pressing Enter (no input, the same as a timeout).
Use it instead of `""`, which Windows PowerShell 5.1 drops.

### 3. Run the tests

```powershell
python -m pytest            # from python\
python -m pytest -v         # list each test
python -m pytest python     # from the repository root
```
