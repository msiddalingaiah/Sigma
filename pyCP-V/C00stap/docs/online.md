# On-line users: from a BREAK to TEL

How a terminal user's session starts, runs and ends, and how the translation provides it: a TCP
port for terminals, COC ([`coc.md`](coc.md)), and small stand-ins for the LOGON and TEL
processors.

## In CP-V

1. **A BREAK, or a line coming ready**, on a line with no user: COC initializes the line
   (`COCMINT`) and reports `E:CBK` through `T:RCE` ([`coc.md`](coc.md) §2, §6).
2. **The scheduler's `LOGON`** (`SCHED.txt:1869`) takes a user number from `SNULL` and checks the
   on-line limits. It ties the user to the line (`LB:UN`) and starts them through `ADD1`, with `TIC`,
   "TEL in control" ([`scheduler.md`](scheduler.md) §8).
3. **The user's command processor**, `UB:ACP`, an index into the shared-processor table `P:NAME`
   (`SPROCS.txt:169`–`:200`), is **LOGON** (`LOGON.txt`). Where it is first set for a new on-line
   user wasn't found. LOGON starts in master mode and drops to slave itself (`LPSD,0 SLAVE`,
   `LOGON.txt:327`). It types:

   ```
   XEROX CP-V AT YOUR SERVICE
   ON AT 13:45 JUN 15,'76
   LOGON PLEASE:
   ```

   (`:331`–`:353`). It reads the account, name and password, and reads `:USERS` by account and name
   (`:359`–`:379`). It checks the password (`:390`–`:397`), and fills the JIT from the record.
4. **When LOGON's step ends**, the step code sees that the command processor was LOGON. It
   switches the user to **TEL** (`STEP041`, `STPNR.txt:1783`–`:1796`, "IS THIS LOG-ON INITIALIZING
   ... SWITCH TO TEL"). TEL prompts with `!` and takes commands. A program it starts runs as a
   step; when the step ends with TEL in control, TEL has the terminal again.
5. **A BREAK** while a program runs goes to the user. With TEL in control, TEL gets control back.
6. **`OFF`**: TEL hands over to LOGON again, which is also LOGOFF. When that step ends with the
   command processor still LOGON, the user is removed (`STEP10`, `STPNR.txt:1828`–`:1830`,
   `T:DELUS`). **A hang-up** (`E:OFF`) does the same through the scheduler.

Accounts are created by `SUPER`, which writes the `:USERS` records LOGON reads. A fresh system's
management account bootstraps the file (`LOGON.txt:725`–`:731`).

## In the translation

### Terminals: a TCP port

`python -m uts ... --terminals N --port P` listens on **localhost** port P (default 2323) for
up to N terminal lines. Each connection is a line, speaking **telnet in character mode**. The
server says `WILL ECHO` and `WILL SUPPRESS-GO-AHEAD`, so COC does the echo and the editing, as on
a Teletype:

| On the connection | To COC |
|---|---|
| Connect | The line becomes ready: log-on, as for a BREAK (`COCMINT`, `E:CBK`) |
| A character | Input, as from the 7611 |
| Telnet BREAK (`IAC BRK`) or interrupt (`IAC IP`), or a raw Ctrl-C | A BREAK on the line |
| Disconnect | The line drops: `E:OFF` |
| (the line's user is gone: `OFF`, or no log-on) | The connection is closed |

Output goes to the connection with CR/LF line ends. A connection when every line is busy gets
`ALL LINES BUSY` and is closed. `--bind ADDRESS` listens elsewhere; there is no authentication,
so that is for trusted networks only.

```powershell
python -m uts --replies 06/15/76 13:45 N --file examples/hello.py=HELLO --terminals 2
# in another window
telnet localhost 2323
```

`-i --console` with `--terminals` lets you type operator key-ins in the first window while the
terminals run. Ctrl-C ends the run (and saves the `--disc` image).

**Time.** While terminals are open, the system runs in **real time** (`terminals.realtime`). A
host loop waits on the connections and the operator's console, feeds what arrives to COC, and
runs the scheduler for the wall-clock time that passed. A clock unit is 2 ms; with nothing to
run, the clock is moved on as the idle loop would. The scripted `--keyins` run first. The tests
drive COC directly, unchanged.

### LOGON and TEL: stand-ins

Both are Python programs (`python/uts/online.py`) run as the user's command processor. They use
the same CALs and COC paths as any program. Every departure is listed below.

**LOGON** types its greeting and `LOGON PLEASE:`, then reads `ACCOUNT,NAME[,PASSWORD]`. A
malformed reply gets `ID?` or `ACCOUNT?`, and three bad tries end the session with `SORRY, UNABLE
TO LOG YOU ON`. With no `:USERS` file, any account is accepted. The user's account becomes the
one given, with privilege 0. When LOGON ends, the step code's `STEP041` switch makes TEL the
command processor.

**TEL** prompts `!` and knows:

| Command | Does |
|---|---|
| `RUN name` or `START name`, or just `name` | Runs the program `name` (Python or machine code) from the user's account, else from `:SYS`. When it ends, TEL prompts again |
| `L` (or `LIST`) | PCL's LIST: the files in the user's account (not `:SYS`, where `--file` puts programs by default); `NO FILES IN DIRECTORY` (`PCLLIST.txt:677`) if there are none |
| `COPY fid`, `COPY fid TO ME`, `COPY fid OVER ME` (or `C`) | PCL's COPY to the terminal: each record of the file typed. `fid` is `NAME` or `NAME.ACCOUNT`. With the `K` option, `COPY fid TO ME(K)`, a record with a 3-byte key gets its record number and EDIT line number in front: `     1 -    1.000 LINE ONE` (`RDWRT.txt:338`–`:370`, WRITE3, with BIN2BCD `UTILITY.txt:82`). With `X`, `COPY fid TO ME(X)`, each record is dumped in hex (HEXDUMP): `KEY=` and the key (as `X'...'` if it isn't printable, UNPRINT) or `REC #n`, the size in bytes, then 4 words a line with the word offset; a run of lines equal to the one before is left out and the next line marked `*`. This is how a load module's records can be looked at. `X` takes precedence over `K` (`RDWRT.txt:1077`) |
| `OFF` | Logs off |

Anything else gets `EH?`, TEL's own message (`EHMSG`, `TEL.txt:3879`). So does a bare name that
isn't a program; `RUN name` for a missing program gets `name NOT FOUND`.

**The step's end** is translated as hooks on `T:EXIT`, `T:ERROR`, `T:ABORT` and CALBAD's
`T:ABORTM`, for on-line users. Ghosts keep the hooks they had.
- LOGON is the processor and the user logged on: `STEP041`, switch to TEL.
- TEL is in control (a program ended, however it ended): TEL again.
- The processor is still LOGON (`OFF`, or three bad tries): `STEP10`, `T:DELUS`.

A program a user runs works in the **user's account** (J:JIT's account is the user's), wherever
the program came from: a file it creates goes there, and `L` shows it. A ghost works in its
`GJOB` account instead.

A Python program reads the terminal with `cpv.readline()` (`M:READ` on `M:UC`), and sets the
prompt with `cpv.prompt(c)` (`M:PC`). `cpv.keyin()` from an on-line user asks at the terminal.

**Departures:**

| CP-V | Here |
|---|---|
| `:USERS`, written by `SUPER`; passwords, limits, privilege | Any account; privilege 0; the password ignored |
| LOGOFF through LOGON, with accounting | `OFF` removes the user (`T:DELUS`) at once |
| TEL's 30-odd commands, and processors started through the step and loader | A few commands; programs started directly |
| `COPY`, `C` and `L` load the PCL processor (`TEL.txt:3889`–`:3891`, `:4567`, `:4590`), which parses the command (`COPYTO.txt`, `DEVTRAN.txt`) | TEL does them itself, through the same CALs (`M:OPEN`, `M:READ` to the end, `M:WRITE` on `M:UC`, `M:CLOSE`). Only output to `ME`; of the options only `K` and `X`, `K` only for 3-byte keys (the record's key length stands in for the DCB's KEYM, and other keys aren't printed with WRITE6, nor unkeyed records numbered with WRITE5); no devices or file-to-file copies; random files refused |
| PCL's error messages come from an error file, keyed by error number (`ERROR.txt:96`–`:100`) | Invented: `COPY: CAN'T OPEN fid: CODE nn`, `COPY: SYNTAX ERROR`, `COPY: ONLY TO ME` |
| TEL's `LIST` sets where a program's listing goes (`LIST ON`/`OVER`, `TEL.txt:1019`) | `LIST` is another name for `L` |
| HEXDUMP's printable test is the EBCDIC table `CCTAB` | A key is printable if every byte is an EBCDIC character in ASCII's graphic range |
| A record's bytes go to the terminal as they are | A record that isn't ASCII is read as EBCDIC, since EDIT-style files hold EBCDIC and other records hold ASCII here (the memory convention, `interpreter.md`) |
| A BREAK with TEL in control interrupts the program, and TEL can `CONTINUE` it | A BREAK ends the program, and TEL prompts again |
| `UB:ACP` an index into `P:NAME` | The processor's name |
| A BREAK interrupts the user at the break address (`STBEEA`) | The user is marked, and at the next `T:PULLE` the command processor gets the terminal |
| LOGON and TEL are shared processors, loaded and swapped | Python generators in the user's place; nothing is loaded |
