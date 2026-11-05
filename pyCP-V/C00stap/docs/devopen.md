# Opening a device DCB

A DCB whose assignment is a device (`ASN` 3) doesn't name a device directly. Before it is opened,
its word 1 holds an **operational label** such as `SI` or `LO`, or a device name such as `ME`.
OPEN resolves that to a device through a table chosen by the kind of user. This document covers
that resolution, as far as is needed to open the DCBs of a real program such as SLIP
([`loadmodule.md`](loadmodule.md)).

> Source: `OPN.txt` (`MSROPN`, the OPEN CAL's parameters), `OPND.txt` (`OPENDEV`, the device),
> `P2OPL.txt` (SYSGEN's `:OPLB` command and the default tables), `CCITABLS.txt` (the label
> numbers). Comments of the form `:NNN` point at `OPND.txt` unless another file is named.

## 1. The way in

`M:OPEN` goes to the OPEN overlay's `MSROPN` (`OPN.txt:92`). That moves the FPT's parameters into
the DCB in presence-bit order, starting at bit 0 (`OPN.txt:109`–`:146`):

| Bit | Parameter |
|---|---|
| 0, 1 | error and abnormal addresses |
| 2, 3 | buffer, record size |
| 4–8 | tries, organization, access, function, generation |
| 9–12 | file option, user label, tape label, key length |
| **13** | **device option** (`MSROPN5`, `OPN.txt:689`) |
| 14 | byte displacement |

A DCB that is open already gets X'2E' (`OPN.txt:94`). For a device, the file processing is
bypassed (`CHKASN`, "BYPASS FOR DEVICE", `OPN.txt:183`–`:186`). `SETFUN` then dispatches on the
assignment: a device goes to `OPENDEV`, an overlay entry in segment `MULSEG` (`OPN.txt:576`–`:584`,
`:775`).

**The device option** is two characters, an operational label or device name. `MSROPN5` looks it
up in the name table (`OH:NM`) and takes its assignment for the kind of user, as `OPENDEV` does
for word 1 (`OPN.txt:700`–`:732`). A name not in the table is "ILLEGAL OPLB" (`OPN.txt:707`).

## 2. `OPENDEV` (`OPND.txt:57`)

Word 1 of the DCB (`DSI`) is read one of three ways:

| Word 1 | Meaning | Where |
|---|---|---|
| `X'10000'` and `X'8000'` clear | an **operational label** by number in the right byte | `OPD1`, `:84`–`:96` |
| `X'10000'`, `X'8000'` and `X'4000'` set | a **name**, 2 EBCDIC characters in the right half, looked up in `OH:NM` | `OPD29`, `OPD30`, `:167`, `:254`–`:261` |
| `X'8000'` set, `X'10000'` clear | a type code and DCT index already | `:62`–`:83` |

A diagnostic open by device address needs privilege X'A0' (`OPD6`). A label beyond the table, or
a name not in it, gets X'14' with subcode X'0A' (`OPNERAB`, `:94`, `:261`, `:406`).

**The assignment** comes from one of three tables, by J:JIT's kind of user (`KRD2`, `:268`–`:272`;
`XTX`, `:403`–`:405`): `OB:BTX` for batch, `OB:GTX` for ghosts and `OB:OTX` for on-line users.
An entry is one of:
- a **DCT index**: a device (`:274`–`:276`);
- a **RAT index**: a device type the job may reserve (`KRD11`, `KRD3`);
- a **LAT index**: a logical device, a symbiont stream (`KRD4`).

The result goes into word 1: the type, the DCT index or 0, and the `L` bit for a listing device
(`KRD9`, `:283`–`:296`). A device type with no device yet is **allocated**: `OPENDEV` looks for a
DCT of the type, and checks that the user has one or may have one (`DHHIT`, `SPINS`, `JB:MAX`,
`:320`–`:367`). If none can be had, the error is X'49' with subcode 2 (`KRD10`, `:336`) or 4
(`KRD7`, `:352`). An on-line user's `M:UC` gets the user's line number (`:384`–`:399`). Last,
`SETOPN` sets the open bit and resets the TYC (`:418`, `:445`).

An error ends the CAL through `MSR01EXIT` (`IORT.txt:598`–`:603`). The code's X'C0' bits make it
an error, which goes to the error address, rather than an abnormal.

## 3. The labels and their defaults

The label numbers (`CCITABLS.txt:133`–`:149`; the characters, `P2OPL.txt:52`–`:61`):

| | | | | | | | | |
|---|---|---|---|---|---|---|---|---|
| 1 `C` | 2 `OC` | 3 `LO` | 4 `LL` | 5 `DO` | 6 `PO` | 7 `BO` | 8 `LI` | 9 `SI` |
| 10 `BI` | 11 `SL` | 12 `SO` | 13 `CI` | 14 `CO` | 15 `AL` | 16 `EI` | 17 `EO` | 18 `UC` |

After them, the name table has pseudo-entries for the device types `CR`, `CP`, `LP`, `PR` and
`PP`, and for `ME`.

The tables are built at SYSGEN by `P2OPL` from the `:OPLB` command. Its defaults are
(`P2OPL.txt:63`–`:90`):

| Label | Batch | On-line | Ghost |
|---|---|---|---|
| `C` | C1 | ME | TY |
| `OC` | TY | **ME** | TY |
| `LO`, `LL`, `DO` | L1 | ME | L1 |
| `PO`, `BO` | P1 | none | P1 |
| `LI` | C1 | none | TY |
| `SI` | C1 | **ME** | TY |
| `BI` | C1 | none | TY |
| `SL` | L1 | ME | L1 |
| `SO` | P1 | none | P1 |
| `CI` | C1 | none | TY |
| `CO`, `AL` | P1 | none | P1 |
| `EI` | C1 | ME | TY |
| `EO` | P1 | none | P1 |
| `UC` | TY | ME | TY |
| `ME` | none (`NO`) | ME | TY |

`ME` is the user's terminal, `TY` the operator's console, `L1`, `P1` and `C1` logical devices
(symbiont streams for the printer, punch and reader), and `NO` the null device. "None" is an
entry left 0, which P2OPL skips, as it does `NO` (`P2OPL.txt:199`–`:201`). So for an on-line user, nearly all output, and
the source input, is the terminal, even `OC`.

## 4. What OPEN takes from the FPT

The FPT can change the DCB before anything is opened, for a file as for a device:
- **The assignment**: the low 3 bits of the FPT's flags (its presence word) are an assignment.
  `CHKASN` returns it if it is non-zero, and the DCB's otherwise (`OPN.txt:548`–`:556`). When it
  differs from the DCB's, it is stored in the DCB (`MSROPN09`, `:276`–`:289`). A program can name
  a file in a DCB built for the terminal, or a device in one built for a file. TEL's assignments
  are made through OPEN too (the step's `ASM3`–`ASM8`, `STPNR.txt:2648`–`:2747`), so a program
  that names its own assignment overrides them.
- **The parameters**: the organization (the value times 16: 0 consecutive, 1 random, 2 keyed,
  `MSROPN51`, `:671`), the function (`SETFUNC`), the key length (`BAKEYM`), the buffer, the
  record size, and the error and abnormal addresses, which also go into the DCB's `ERA` and `ABA`
  (`:111`–`:113`).
- **The VLPs**: when the flags' low 10 bits are set, VLPs follow the parameters, in the DCB's own
  format. Each code the DCB has a slot for is copied in, as many words as the slot reserves, with
  the count of words used (`MSROPN10`–`MSROPN98B`, `:300`–`:351`). A code with no slot is skipped
  (`MSROPN99A`). A VLP with a count of 0 isn't given: an account not given is the user's own
  (`CHKFLACN`, "USER SPEC'D AN ACCT", `OBSE.txt:283`–`:288`).

`M:SETDCB` (CAL1,1 code 6, a device CAL) sets `ERA` and `ABA` alone (`IOD.txt:102`–`:103`,
`:526`–`:531`). An exit through the DCB (`MSR01EXIT`, `IORT.txt:598`–`:603`) uses them. An exit
after a read or write uses the JIT's (`IOCHEK`, `:890`–`:895`), which come from that CAL's FPT.

## 5. Device options and two small services

**Device options** (`M:DEVICE`, CAL1,1 with a device code, `IOSDEV`, `IOD.txt:99`). The code is
looked up in `IOTBL` (`:112`): X'24' COUNT, X'23' DATA, X'21' FORM, X'26' HEADER, X'20' LINES,
X'22' MODE, X'28' TAB, X'27' SEQ, X'25' SPACE, X'04' PAGE, X'05' VFC, X'0B' DIR, X'2A' NLINES,
X'2B' CORRES. SETDCB (6, §4) is always done (`:102`–`:103`). On `M:OC` the others are skipped
(`:104`–`:105`). COUNT to SPACE apply to a device DCB only (`TSTDEV`, `:551`–`:557`); PAGE to
CORRES go straight to their routines (`TSTDEV1`, `:547`–`:549`).
- **PAGE** (`IOPAGE`, `:310`): the DCB is opened if it isn't (`TESTOPN`). Nothing happens on the
  null device. Otherwise a top of form goes out (`TOFCHAR` X'F1'): through a symbiont stream, to
  a listing device, or to COC for a terminal (device type X'90', "ME", `IOPGE19`).
- **VFC** (`IOVFC`, `:446`): the FPT's flag (X'10' in its second word, shifted to X'100') goes
  into the DCB's word 0, the `FRM` bit X'100`. An open DCB that isn't a device is left alone
  (`1A1`). With the bit set, COC takes a record's first character as format control (`COCWR30`,
  `COC.txt:2935`): X'F1' a top of form, X'C1'–X'CF' that many new lines. The character itself
  isn't sent, whatever it is (`COCWR70`, `:3103`).
- **CORRES** (`IOCORRES`, `:507`): are two DCBs assigned alike? `GETDEV` (`IORT.txt:1288`) gives
  each one's assignment, for a DCB never opened too (`GETDEV1`). The answer, 1 or 0, goes into the
  user's register 8 (`NL1`).

**`M:INT`** (CAL1,8 X'0E', `MINT`, `TRAPC.txt:143`): the user's BREAK address into `J:INTENT`,
with X'08000000'. If the user has no TCB, register 0 becomes `J:TCB` (`INT10`). A command
processor's own break control (`INT30`) is separate.

**`T:CHTBL`** (CAL1,8 X'06', `UCAL.txt:436`): for on-line users only; anyone else gets CC1. By
its flags (the FPT's first halfword): X'80' arms BREAK, X'40' gives the terminal status
(`T:TS`), X'20' sets a mode, X'10' resets the break count, and with none of these, the
translation table changes.

## In the translation

`python/uts/devopen.py` translates the label and name resolution, with P2OPL's default tables.
`cal.py` translates the OPEN:
- the FPT's assignment (`CHKASN`, `MSROPN09`), then `device_open` or the file open;
- MSROPN's parameters and the FPT's VLPs, merged into a DCB in memory (`_merge_open`,
  `MemDcb.set_vlp`);
- `M:SETDCB`, and the device options PAGE, VFC and CORRES (`iosdev`). PAGE on a terminal starts
  a new line, VFC sets the bit COC then honours, and CORRES compares two DCBs' assignments.
  The other options stop with `NotTranslated`;
- `M:INT`, which records the BREAK address. A BREAK still ends the program and returns to TEL:
  delivering it to the address isn't translated;
- `T:CHTBL`, accepted with no effect, except the terminal status (X'40'), which isn't translated;
- a **default OPEN**: a read or write on a closed device DCB in memory opens it first
  (`MSRRDWTA`; `msrrdwt1`).

An assignment ends up as one of:
- `ME`: COC, the user's terminal (`cocio`);
- `TY`: the console, through IOQ;
- `NO`: the null device, where a write does nothing;
- `CR` or `CP`: the card reader or punch, below.

### Card devices

There are no card readers today. The card reader and punch are **devices whose media are host
files** (`python/uts/cards.py`), as simh attaches a deck:
- `--reader DECK.txt` loads a deck. Each line is a card, 80 columns in EBCDIC, blank-filled. A
  read takes the next card. With the hopper empty, the read ends abnormally with X'06', end of
  file.
- `--punch FILE.txt` is where punched cards go, a line each.

A device type in an assignment or a device option (`CR`, `CP`) is allocated if a medium is loaded
and no one else holds it (`SPINS`, "DOES ANYONE HAVE IT", `GERM.txt:51`). The job keeps it until
it ends (`T:DELUS`), as `OPENDEV` charges it to the job (`JB:CUR`, `J:ASPIN`,
`OPND.txt:358`–`:366`).

**The departure**: the job's limit for the type, `JB:MAX` (`OPND.txt:346`–`:352`), isn't modeled,
so any user may have a card device, an on-line user too. Where an on-line user's `JB:MAX` comes
from (log-on, `:USERS`) wasn't traced. Also not translated: the reader and punch handlers
(`HANDLERS.txt`). A card read or punch completes at once, below IOQ.

Not translated:
- logical devices (`C1`, `L1`, `P1`: symbiont streams, COOP): they stop with `NotTranslated`;
- other device types (`LP`, `PR`, `PP`): their allocation fails as for a user who may not have
  one, X'49' subcode 2;
- a site's `:OPLB` cards, the `L` bit, the line number in `M:UC`, and DCBs that already hold a
  type and DCT index.

### SLIP

SLIP is a card utility. Its control card on `M:SI` says `CARD TO DISK`, `VERIFY` or `COPY TO
TAPE`, and its OPEN of `M:SI` names the device `CR` itself (its FPT at `X'A1DE'`, flags
`X'C0040003'`: assignment 3 and the device option `CR`). With a deck in the reader:
1. it reads the control card and, for `CARD TO DISK`, prints
   ` THE FOLLOWING FILES WERE COPIED TO DISK:`;
2. it opens `M:EI` on the reader for the deck, sets its addresses with `M:SETDCB`, and opens its
   work file `F:1`, `MTRNMFILE` in the user's account. That FPT names a keyed file, UPDATE. The
   file isn't there (X'03'), so SLIP's abnormal routine opens it OUT, which creates it;
3. it reads the next card, 120 bytes (a binary card), and checks it. A card that isn't what it
   expects gets ` !BIN OR FIRST CATALOG CARD MISSING`, and SLIP aborts.

The deck SLIP wants, a `!BIN` card or "catalog cards" with binary cards after them, is SLIP's own
format, not described in the monitor's source.

With no deck, the `M:SI` OPEN fails with X'49', and SLIP's error routine at `X'A0F0'` opens `F:3`,
whose FPT names `ERRMSG.:SYS`, the system's error-message file. It reads the message keyed by the
error code and prints it with `M:PRINT` (on `M:LL`). There is no `ERRMSG` here, so nothing is
printed.

## Open questions

- **The label range**: `OPD1` compares the label with `OV:SIZ` (`:94`), taken here as 18, the
  operational labels without the pseudo-entries.
- **`OH:NM`'s further entries**: the table also holds `SH:OPNM` and `SH:LNM` names (logical
  device names, `KRD6`). Only the labels and the device pseudo-entries are modeled.
- **The FUN a device sets**: `OPENDEV` sets the DCB's function from the device's DCT3 bits
  (`NONTAPE`, `:373`–`:383`). The DCB's own function is kept here.
- **A job's files at an abort**: SLIP aborts with `MTRNMFILE` open, so it is never entered in the
  directory here. What CP-V does with a job's open files at an abort wasn't traced.
- **The rest of MSROPN's parameters** (tries, access, generation, file option, labels, reel,
  and so on) are skipped, and so are the FPT's extended forms (`X'22000'`).
