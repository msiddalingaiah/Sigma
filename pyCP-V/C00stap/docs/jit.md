# The JIT page

Each user's **job information table** (JIT) sits in the user's own virtual memory, at page X'46'
(`JJITVP`, `JIT.txt:272`), word X'8C00'. The monitor keeps the job's state there, and programs read
it directly: the kind of user, the account and name, the privilege, the command line, and the
DCBs `M:UC` and `M:XX`. A program's references to `M:UC` are to its address in the JIT.

> Source: `JIT.txt` (the template, from `J:JIT`, `:304`), `TEL.txt` (`TELCCBUF`, `:6235`),
> `OPND.txt` (the kind of user, `:268`–`:270`). Word offsets are from `J:JIT`.

## 1. The layout

`JIT.txt` assembles the JIT's initial contents. Its first 270 words, as assembled:

| Word | Label | Holds | Initially |
|---|---|---|---|
| 0 | `J:UN` / `SYSID` | Bits 0–1: the kind of user, 0 batch, 1 ghost, 2 on-line (`LB,R1 J:JIT` / `SLS,R1 -6`, `OPND.txt:268`–`:270`); the low half: the job's ID | 0 |
| 1–2 | `J:ACCN` | The account | |
| 3–5 | `J:UNAME` | The user's name | |
| 6–16 | `J:CTIME` … `J:MRT` | Times and limits | |
| 17 | `J:ABC` | The abort code | X'80700000' |
| 18 | `J:RNST` | The run status | |
| 20 | `J:ASSIGN` | | |
| 21, 22 | `ERO`, `ABO` | The error and abnormal addresses of the CAL in progress | |
| 26 | `J:JIP` | | X'0FFE0000' |
| 33 | `J:TELFLGS` | TEL's flags | |
| 34 | `J:CASSIN` | | X'02000000' |
| 35 | `J:INTENT` | The BREAK address (`M:INT`) | |
| 36 | `J:TIMENT` | The timer's exit (`M:STIMER`) | |
| 38 | `J:USENT` | The trap entry and the trap flags (`M:TRAP`, [`trapxcon.md`](trapxcon.md)) | |
| 39 | `J:TCB` | The TCB's address | |
| 40 | `J:TREE` | The overlay tree in memory | |
| 43 | `J:DCBLINK` | The DCB table | |
| **44–65** | **`M:UC`** | **The terminal DCB**, 22 words: assignment 3, the name `UC` (`DATA 3,X'1E4C3'`) | |
| 66 | `J:XP` | | |
| 67, byte 0 | `JB:PRIV` | The privilege | |
| 68 | `J:ABUF` | The assign/merge buffer | |
| 69 | `J:PUF` | Byte 0: the command line's length (`TELCCBUF`) | X'0000000F' |
| 70 | `JB:LPP`, `JB:LC`, `JB:PCW`, `JB:PROMPT` | Lines a page 54, the line count 49, the platen width 72, the prompt | X'36314800' |
| 71 | `J:IDELTAT` | | |
| 72 | `J:EXTENT` | Exit control: the address and its flags (`M:XCON`, [`trapxcon.md`](trapxcon.md)) | |
| 74–196 | `TSTACK` | The temporary stack: its pointer, its counts (102, 19), the write key, saved registers, `:SYS`, a `CAL1,9 1`, then 102 words of X'BAD' | |
| 197–199 | `J:OVRLY`, `J:CPROCS`, `J:CFLGS` | | |
| **200–212** | **`J:CCBUF`** | **The command line**: TEL moves the line it read here (`TELCCBUF`, `TEL.txt:6235`–`:6245`), up to 80 bytes | |
| 213–219 | `J:CLM` | | |
| 226–228 | `J:LMN` | The load module's name | |
| 229 | `J:START` | The start address | |
| **230–** | **`M:XX`** | **A DCB for the program's own load module**, with its VLPs (`MXFPL`, word 252) and key buffer (`MXKB`, word 262) | |

The memory-management words follow (`J:BUP` on, `:542`): words 270–285, the areas' limits,
page counts and `JB:TDP`/`JB:BCP` ([`pages.md`](pages.md)). The table was made by assembling the
template with a small one-off assembler for its `DATA`, `GEN`, `TEXT`, `RES`, `BOUND`, `DO` and
`SET` statements. Its offsets agree with a count by hand. Two words are forward references, which a
one-pass assembly leaves 0: `M:XX`'s FLP is `MXFPL` (X'8CFC') and its key buffer `MXKB` (X'8D06').

## In the translation

`python/uts/jit.py` holds the table. When FETCH starts a load module, `jit.build` writes the page
into the user's memory:
- the template's words;
- the kind of user and the user number in word 0;
- the account, the log-on name, the privilege and the prompt;
- `J:TCB`, `J:DCBLINK`, `J:TREE`, `J:START`, `J:LMN`, `J:INTENT`;
- the command line in `J:CCBUF` with an EBCDIC NL after it, and its length in `J:PUF`. TEL
  passes the whole line typed, the program's name included. A name followed by more is run as a
  program, as TEL runs an unrecognized command as a load module (`CHKULM`, `TEL.txt:950`).

`M:UC` is at its real address, X'8C2C', and `M:XX` at X'8CE6'. The monitor's `M:OC` isn't in the
JIT: its address is still invented, now X'8E00', outside the page.

**A departure**: the page is built when the program starts and isn't kept in step with the
monitor's own fields, which stay Python objects (`sched.Jit`). Only `J:INTENT` is written again,
by `M:INT`; `J:USENT`, `J:EXTENT` and `J:TCB` are kept in the page itself (`M:TRAP`, `M:XCON`,
exit control). A program that reads, say, `J:ABC` after an error sees the value from its start.

## Open questions

- **`SYSID`**: word 0's low half is taken to be the user number. CP-V's job ID may be another
  number.
- **The command line's form**: what CCI leaves for a batch job, and whether TEL's line keeps its
  NL in the count, weren't traced. SHOW still answers `COMMAND LINE MUST NOT EXCEED 50 CHARACTERS`.
- **The words after the memory limits** (word 286 on: `J:USER`, the physical page counts,
  the command list, `J:JAC`, `JB:LMAP`, `JX:CMAP`) aren't built.
