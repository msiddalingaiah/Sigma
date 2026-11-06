# COC: terminals

**COC** is the monitor's handler for the character-oriented communications controller, the 7611,
which connects Teletype-class terminals. It takes each character as it arrives, echoes it, edits
the line, and hands complete lines to a program's reads on `M:UC`. It formats and paces a
program's writes, and it turns a BREAK or a new connection into an event for the scheduler.
This document covers what a line needs. The parts for IBM 2741 terminals, paper tape, slave
lines and the timing algorithms are noted but not followed.

> Source: `COC.txt` (4,726 lines). Comments of the form `:NNN` point at it. The scheduler side,
> `T:RCE` and the log-on, is [`scheduler.md`](scheduler.md) §8. The session it starts is
> [`online.md`](online.md).

## Overview

```
7611 hardware ── (character, line) pairs into a ring buffer ── input interrupt: COCIP (:412)
      per pair: line X'80' set = BREAK (COCIPBRK :857)       translate ASCII -> EBCDIC (TTYIN)
      immediate characters: BS, Ctrl-Y, ESC, Ctrl-X, rubout   into the line's input buffers
      echo if a read is pending (COCECHO :1157)               activation -> E:CIC (T:RCE)

program  M:READ / M:WRITE on M:UC ─► IOQ ─► COCIO (:3832) ─► COCRD (:2272) / COCWR (:2851)
      read: prompt, echo type-ahead, wait (E:CRD) for an activation, move the line (COCMU :2655)
      write: format control, into output buffers; too much output blocks the user (E:CBL)
output interrupt: COCOP (:1899) sends characters; below the unblock limit, E:CUB

CLOCK4 every 1.2 s: T:COCHC (:4182): time-outs, and a newly ready line with no user
      -> COCMINT, as for a BREAK: the scheduler's LOGON
```

## 1. The line tables

Each line has an entry, indexed by line number (`:164`–`:305`):

| Table | Holds |
|---|---|
| `LB:UN` | The line's user number (0: none) |
| `MODE`, `MODE2`, `MODE3`, `MODE5` | Mode bits: read pending, escape pending, the break count (in `MODE`); disconnected, 2741 (`MODE2`); lost data, paper tape (`MODE3`); slave line (`MODE5`) |
| `COCIR`, `COCII` | The input chain's head (removal point) and insertion point |
| `COCOR`, `COCOC` | The output chain's head and character count |
| `COCTERM` | The terminal type: it picks the translate tables (`COCITV`, `COCOTV`, `:342`–`:376`) |
| `BUFCNT` | Buffers the user holds; `SL:ONCB` is the limit |
| `CPOS`, `CPI` | The carriage position, and its value at the start of the read |
| `EOMTIME` | Read-ahead state |

Buffers are 16-byte blocks from a common pool (`COCBUF`, `COCGETB`), chained per line.

## 2. Input (`COCIP`, `:412`–`:1108`)

The controller stores each character with its line number in a ring buffer, and an input
interrupt runs `COCIP` over the new pairs (`:430`–`:461`):

1. **The line number**: X'80' added means a **BREAK** on that line (`:472`–`:475`). A line out of
   range is counted (`COCBLC`) and dropped.
2. **A disconnected line's input is dropped** (`MODE2`, `:500`). Parity is checked; a bad character
   becomes X'1A' (`:508`–`:512`).
3. **Translation**: `TTYIN` (`:4615`) gives the character's EBCDIC code. The same index into the
   output table `TTYOUT` (`:4655`) gives the character's **class**, in its high bits:
   - `*` needs an action of its own;
   - `+` activates a read (or is a "delta" activation character);
   - `&` changes the line's mode.

   CR and NL (LF) both translate to `*` entries (X'82'): they end a line.
4. **Immediate characters** (`IMCHR`, `:685`–`:717`) act at once:

   | Character | Action |
   |---|---|
   | backspace | Buffered. Two in a row become a special "contiguous backspace" |
   | Ctrl-Y (EM) | `E:CEC`, the interrupt to the command processor (`COCIYC`, `:719`) |
   | ESC | Sets "escape pending": the next character is an escape sequence (`COCIESC`, `:788`; the table `TTESCS`) |
   | Ctrl-X (CAN) | Throws away the line's output and its pending input; echoes a back arrow and CR/LF (`COCIXC`, `:795`) |
   | rubout | Buffered as a deletion, for the read to apply (`COCIRUB`, `:848`) |

5. **Into the buffers** (`COCIP9`–`COCIP93`, `:517`–`:546`). **A line with no user buffers
   nothing** (`:524`–`:525`). Past the user's buffer limit, the line is in "lost data" mode: the
   terminal gets a BELL, and the reader gets X'BE' (`:595`–`:631`).
6. **Echo**: if a read is pending, `COCECHO` echoes the character (`:548`–`:553`). When it sees an
   activation character, the read is complete: **`E:CIC`** goes to the scheduler through `T:RCE`
   (`:582`–`:593`).

**BREAK** (`COCIPBRK`, `:857`; `IPBRKCT`, `:897`) counts breaks in `MODE`, and four in a row act
as a Ctrl-Y. On a line with **no user**, `COCMINT` initializes the line's tables (`:728`–`:730`),
and the break, `E:CBK`, reaches `T:RCE`. `T:RCE` sends a break on an empty line to the scheduler's
**`LOGON`**, which creates the user ([`scheduler.md`](scheduler.md) §8). On a line with a user,
the break goes to that user: with TEL in control, back to TEL (`CCFLG811`, `:765`–`:771`).

## 3. Echo (`COCECHO`, `:1157`–`:1898`)

A character is echoed as it is read, through its output class:
- a printable character is echoed as itself, and moves the carriage position;
- **CR or NL** echoes CR/LF and activates;
- **backspace** and **rubout** edit;
- **tab** expands to the user's tab stops (`TABS` in TEL);
- the escape sequences have their own echoes: `ESC X` cancels the line, `ESC R` retypes it,
  `ESC F` and others change modes.

Upper case may be mapped to lower, by mode. Characters typed before a read was issued (type-ahead)
are echoed when the read starts (`COCRD`).

## 4. Reading (`COCIO`, `:3832`; `COCRD`, `:2272`; `COCMU`, `:2655`)

A program's `M:READ` on a terminal DCB goes through IOQ to **`COCIO`**, which takes the request
from the DCB (`:3834`–`:3873`):
- the byte count from word 6;
- the buffer from word 7;
- the byte displacement;
- the line number from `M:UC`.

A record is at most `C:140` bytes. **`COCRD`**:
1. sends the prompt (`JB:PROMPT`) when required;
2. sets the tab stops and the carriage position at the start of the read (`CPI`);
3. echoes the characters already typed ahead;
4. **without an activation yet, waits**: the user is blocked in terminal input (`E:CRD`, the
   scheduler's `STI` state), and `E:CIC` releases them;
5. moves the line to the user's buffer through `COCMU`, which applies backspace, rubout and tabs
   as it goes (`:2655`–`:2850`). **The activation character ends the record**: `MUCRLFNL`
   (`:2770`–`:2773`) stores the CR, LF or NL at the message's last position, so it is counted
   in the ARS;
6. sets the TYC and ARS. A BREAK or Ctrl-Y during the read sets CC2 (`:2272`–`:2654`).

## 5. Writing (`COCWR`, `:2851`–`:3226`)

`COCWR` moves the user's record into the line's output buffers through `TTYOUT`:
- **format control**: with vertical format control in the DCB, the first character is a control
  (X'C1'–X'CF', a number of new lines); otherwise a new line comes first;
- **transparent writes** go out untranslated;
- **pacing**: when the line's output count passes **`SL:TB`**, the user is blocked (`E:CBL`, state
  `STOB`). The output interrupt (`COCOP`, `:1899`) releases them (`E:CUB`) once the count is
  below **`SL:UB`**.

`COCIO` sets TYC 1 for a write, stores the ARS in the DCB, and decrements its function count
(`:3885`–`:3902`).

## 6. Lines coming and going (`T:COCHC`, `:4182`–`:4422`)

CLOCK4 calls `T:COCHC` every 1.2 seconds. It times out users with reads pending (`SL:OITO`,
`SL:OLTO`), and handles the data sets:
- **a line that becomes ready with no user** gets `COCMINT`, and is logged on as for a BREAK;
- **a line that drops** is reported as `E:OFF`. `T:RCE` sets `HANGUP` for the user, and
  `COCOFF` sets the line up as off.

## In the translation

`python/uts/coc.py` models the lines (the line tables of §1, a Python list per line in place of
the 16-byte buffer chains) and translates:
- **§2:** input, BREAK and the immediate characters (backspace, rubout, Ctrl-Y, Ctrl-X, ESC).
  A line with no user buffers nothing. CR, LF and CR LF each end one line.
- **§3:** echo of printable characters and CR/NL, backspace and rubout, and Ctrl-X, only while
  a read is pending.
- **§4:** reads through `COCIO` (`CalProcessor.cocio`): the prompt (`JB:PROMPT`, set by `M:PC`),
  the type-ahead echoed, `E:CRD` until `E:CIC`, then the line into the buffer and the ARS. The
  record ends with X'15', the NL, whichever of CR, LF or CR LF ended the line. That CR and LF
  translate to X'15' is an assumption (TEL's `J:CCBUF` line ends in X'15'). `M:UC` is in the JIT
  page, so its ARS and TYC are written to its words as well as to the monitor's object
  (`CalProcessor._mirror`): EDIT reads the ARS there. An on-line user's `M:KEYIN` types its
  message on `M:UC` and reads the reply from it.
- **`M:TS`** (`T:TS`, `UCAL.txt:530`): the line's bytes into R8–R11. The modes are those
  `COCMINT` sets for a TTY (`MODE` X'88', `MODE2` X'20', `MODE3` 0, `COC.txt:4403`–`:4421`), since
  COC keeps no others here. `COCTERM`, `MODE4` (from the SYSGEN table `MODE4INIT`), `CPI`,
  `COCOC`, `BUFCNT` and the table's dummy entries are 0.
- **§5:** writes. A record starts on a new line unless the carriage is at the left margin
  (`CPOS`, kept per line). An EBCDIC NL (X'15') in a record is a new line. With vertical format
  control (the DCB's X'100'), the first character is format control and isn't sent: X'C1'–X'CF'
  that many new lines, X'F1' a top of form, here a new line (`COCWR30`–`COCWR70`,
  `:2935`–`:3103`; [`devopen.md`](devopen.md) §5). The carriage stays at the record's end, so a read that follows takes
  its input on the same line (`LOGON PLEASE: `).
- **§6:** a connection as a ready line, a disconnection as `E:OFF`. The user is removed at
  their next `T:PULLE` (`HANGUP`).

A BREAK or Ctrl-Y also marks the user. At their next `T:PULLE`, the scheduler's `BREAK` hook
hands the terminal to the command processor ([`online.md`](online.md)); that stands in for the
break address `STBEEA` sets up.

The terminals are TCP connections speaking telnet ([`online.md`](online.md)). Not translated:
- tab stops, escape sequences (consumed and ignored);
- vertical format control, transparent mode, output pacing (`SL:TB`/`SL:UB`);
- time-outs, lost-data mode, parity, paper tape, the 2741.

**Characters** are EBCDIC in user memory, as on the machine. A line typed in ASCII goes into the
user's buffer in EBCDIC (`COCIO`'s read, the role of `TTYIN`). A record written goes to the
terminal as the EBCDIC characters' ASCII equivalents (`TTYOUT`'s role). The editing and echo work
on the terminal's characters. `TTYIN` and `TTYOUT` themselves, the character classes as well as
the codes, aren't translated: the conversion is code page 037.

## Open questions

- **TTYOUT for characters with no ASCII equivalent**: memory can hold any byte, and a record
  written goes out as its code page 037 characters, control characters included. What TTYOUT
  sends for those wasn't traced.

- **Echo of a deletion.** On a hard-copy terminal, CP-V's echo of backspace and rubout
  (`COCECHO`'s "PROCESS BACKSPACE" and "PROCESS RUBOUT") wasn't traced in detail. The translation
  echoes backspace, blank, backspace, which suits a screen.
- **The escape sequences** (`TTESCS`, `ESC X`, `ESC R`, `ESC F`, the `&` mode changes) aren't
  followed.
- **When a prompt is sent**: `COCRD` sends `JB:PROMPT` "IF REQUIRED". The condition wasn't traced.
  The translation sends it at the start of every read, on a new line unless the carriage is at
  the margin.
- **The new line before a record**: §5's "otherwise a new line comes first" is read as "unless
  the carriage is at the margin". `COCWR`'s use of `CPOS` there wasn't traced.
