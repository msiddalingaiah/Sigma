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
| `name [source] [ON\|OVER [object]] [,listing]` | TEL's processor command (`PARSER`, `TEL.txt:609`), translated: the source becomes `M:SI`, the object `M:GO` and the listing `M:LO`. These are assign/merge sets that the program's DCBs are merged with when it starts, plus TEL's options in `J:OPT`. For example, `AP SRC OVER OBJ,LST`; AP then asks ` OPTIONS` with `>`, and Enter takes TEL's. The sets other than `M:SI` stay for later commands. `ON FILE name ILLEGAL` if `ON` names a file that exists. See [`assign.md`](assign.md) |
| `L [fid][(A)]` (or `LIST`) | PCL's LIST: the files in the user's account, or with a fid of `.ACCOUNT` another account's, or `NAME[.ACCOUNT]` one file (COPYTRAN's file-id forms, `COPYTRAN.txt:37`). `--file` puts programs in `:SYS` by default. With `(A)`, PCL's heading `ORG GRAN REC DATE NAME` (`PCLLIST.txt:1113`) and each file's organization, `K`, `C` or `R` (`:521`–`:525`), and record count; the granules and date are left blank. `NO FILES IN DIRECTORY` (`:677`) if there are none |
| `COPY fid`, `COPY fid TO ME`, `COPY fid OVER ME` (or `C`) | PCL's COPY to the terminal: each record of the file typed. `fid` is `NAME` or `NAME.ACCOUNT`. With the `K` option, `COPY fid TO ME(K)`, a record with a 3-byte key gets its record number and EDIT line number in front: `     1 -    1.000 LINE ONE` (`RDWRT.txt:338`–`:370`, WRITE3, with BIN2BCD `UTILITY.txt:82`). With `X`, `COPY fid TO ME(X)`, each record is dumped in hex (HEXDUMP): `KEY=` and the key (as `X'...'` if it isn't printable, UNPRINT) or `REC #n`, the size in bytes, then 4 words a line with the word offset; a run of lines equal to the one before is left out and the next line marked `*`. This is how a load module's records can be looked at. `X` takes precedence over `K` (`RDWRT.txt:1077`) |
| `DELETE fid[,fid…]` (or `D`) | PCL's DELETE (`TEL.txt:4590`), done by TEL: each file opened (M:OPEN, with its checks) and closed with REL (M:CLOSE's disposition 1: CLSFIL releases the entry and the granules). A name with bytes that don't print is given as LIST shows it, each run of them as hex in parentheses, or whole as `X'hex'`. AP's scratch files are `FX1` and `FX3` followed by the SYSID as a binary halfword (`CI$APCCI.txt:898`–`:900`), for example `FX1(0007)` (`X'C6E7F10007'`). Only the user's own account; the messages (`fid DELETED`, `DELETE: fid: NO SUCH FILE`) are invented |
| `TAPE`, `TAPE reel`, `TAPE reel name …` | **Not CP-V.** The tapes the operator mounted with `--mount TAPE.tap`: their reels; one reel's files and record counts; each named file copied into the user's own account, an existing one replaced (`labtape.restore`). TEL finds a program in the user's account before `:SYS`, so `TAPE CPCO EDIT` then `EDIT` runs EDIT from the boot tape. With `--disc`, the copy stays on the disc image |
| `IMPORT`, `IMPORT host [TO fid]` | **Not CP-V.** The host folder the operator shared with `--share DIR`. `IMPORT` alone lists its files, with size and date. `IMPORT host` copies a host text file into the user's own account as an EDIT-style keyed file (keys 1.000, 2.000, ...), named after the host file without its extension unless `TO fid` is given. An old file of that name is replaced. ASCII (UTF-8) becomes EBCDIC, and tabs go to the assembler's columns: 10, 19, then every 8. A character with no EBCDIC code stops the copy, with its line number. Lines longer than 80 are counted in the reply (`hostfiles.py`) |
| `EXPORT fid [TO host]` | **Not CP-V.** A keyed or consecutive file of the user's own account into the shared folder, a line a record, in key or record order. Trailing blanks are dropped, lines end with CRLF, and the default name is `FID.txt`. A listing's carriage-control column (`1`, ` `, `A`) is left as it is. Random files are refused |
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
| `M:LDTRC` (load and transfer, CAL1,8 X'03'; ALTCP.txt `MLNK`, LNKTRC.txt `LDT0`, `L10LNK`) ends the program and `T:ASP` starts the named processor: a shared one from `P:NAME`, else a load module | Translated as far as `T:ASP`: exit control first (the `M:LINK` bit), the trap and timer entries cleared, the program's DCBs and `M:XX` closed, the name, account and password from the FPT. Then the stand-ins stand in for `P:NAME`: **`LOGON`** logs the user off, as `OFF` does (`STEP10`: `T:DELUS`), which is EDIT's `BYE` and `OFF`; **`TEL`** is TEL again; any other name is run in place through FETCH. Not modeled: `VALID`'s checks, `RTCHK`, the FPOOLs, a saved IDN file. `M:LINK`, which keeps the caller, isn't translated |
| A labeled tape is mounted on a drive and copied with PCL or FRES (the labeled-tape OPEN, `OPNL`, and `LBLT`) | `TAPE`, a convenience: tapes are host images the operator names with `--mount`, never a terminal user. A user can copy only into their own account |
| SYSGEN's PASS3 and the operator (PCL) put the processors and system files in `:SYS` | `--install TAPE.tap [NAME …]`, host-side: the named files (by default AP, `$:STDDEF`, LYNX, LOADER, ERRMSG, `:LIB`, EDIT) into `:SYS` |
| A step ended by an I/O error with no error routine: TEL reports it with ERRMSG's text | The stand-in TEL types `I/O ERROR X'cc'-ss ON dcb, NO ERROR ROUTINE: THE STEP ENDS`, its own words |
| Source is punched on cards or typed with EDIT; files leave the system on tape or cards | `IMPORT` and `EXPORT`, a convenience: the operator names one host folder with `--share`, and a terminal user names only bare file names in it. No drive, path or `..`; a name that would resolve outside the folder is refused. Only the user's own account. Anyone who can reach the terminal port can read and write that folder, so with `--bind` share only what they may see |
| TEL's `LIST` sets where a program's listing goes (`LIST ON`/`OVER`, `TEL.txt:1019`) | `LIST` is another name for `L` |
| PCL's LIST prints a file's name as it is | Each run of bytes in a name that don't print is shown as hex in parentheses, `FX1(0007)`; COPY and DELETE take that form |
| LIST `(A)` prints granules, records, a date and the file's attributes in PCLLIST's own columns | Organization and record count only, in the heading's columns |
| HEXDUMP's printable test is the EBCDIC table `CCTAB` | A key is printable if every byte is an EBCDIC character in ASCII's graphic range |
| A record's bytes go to the terminal through COC's output translation (TTYOUT) | A record is shown as EBCDIC characters, with any that has no printable ASCII equivalent as `.` |
| A BREAK with TEL in control interrupts the program, and TEL can `CONTINUE` it | A BREAK ends the program, and TEL prompts again |
| `UB:ACP` an index into `P:NAME` | The processor's name |
| A BREAK interrupts the user at the break address (`STBEEA`) | The user is marked, and at the next `T:PULLE` the command processor gets the terminal |
| LOGON and TEL are shared processors, loaded and swapped | Python generators in the user's place; nothing is loaded |
