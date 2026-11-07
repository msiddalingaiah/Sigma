# Assignments: TEL's processor command and the assign/merge record

How `!AP SOURCE OVER ROM,LIST` gives AP its files. TEL turns the command into
**assign/merge sets**, one per DCB name (`M:SI`, `M:GO`, `M:LO`), and keeps them in the user's
**assign/merge record** (`J:AMR`). When the next program starts, the step code merges each set
into the program's DCB of that name (STPNR.txt `ASP17`–`ASM8`), and the program's own
`M:OPEN` then opens it on the merged assignment. TEL also passes
the options it implies (SI, GO, LO) in the JIT's `J:OPT`.

Sources: TEL.txt (`PARSER`, `:600`–`:900`; `GROUP2C`, `:483`–`:520`; `FILENT`, `:6031`; the
PLIST skeletons, `:4024`–`:4106`), STPNR.txt (`ASP17`–`ASM8`, `:2595`–`:2737`), OPN.txt
(`MSROPN`'s "A" form, `:100`–`:114`, `:258`–`:270`), JIT.txt (`J:OPT`, `JSTDOPT`, `JRESOPT`,
`:517`–`:523`), and AP H00's CCI.txt (`c00si/APH0tap/aph0co/CI$APCCI.txt`, `:191`–`:300`,
`:690`–`:706`).

## 1. The command

A command whose verb isn't one of TEL's (`VERB1`, `VERB2`, `:4629`–`:4756`) names a load module
(`NFND`, `DBL10`, `:438`–`:447`). TEL marks it "unrecognized" (`J:TELFLGS` X'100000') and parses
the rest of the line with `PARSER` (`:609`). The fields, in order:

```
NAME [source] [ON|OVER [object]] [,listing]
```

- **source** (`TOPPARSE`, `:611`–`:660`): a file id `name[.account[.password]]`, or `ME`. It
  becomes the `M:SI` set, mode IN (`MGSI`, `:653`–`:656`). A second source is a syntax error
  (`TESTSI1`). `%` is illegal.
- **ON** or **OVER** (`DOON`, `DOOVER`, `:696`–`:704`) sets J:TELFLGS X'20' or X'40'. `OVER`
  followed by a comma implies the object (`EXTDGO`, `:811`).
- **object** (`OPRSE`, `:705`–`:790`): the `M:GO` set, mode OUT.
  - A file id. After `ON`, it must not exist already (`FLOP`, `:5161`). If it does, TEL says
    `ON FILE name ILLEGAL` (`ONERR`, `:819`–`:836`).
  - `NO`, `CP` or a stream id (`ROMDEV`): a device. A device is illegal after `OVER`.
  - `%`: the default object file (§3).
  - `ME` is illegal (`FILE: ME ILLEGAL`, `ERRME`), and so is `LP`.

  Any of these sets the GO option (X'80', `LOFINS`).
- **listing** (`DOLO`, `:838`–`:900`): the `M:LO` set, a file id (mode OUT, the same `ON`
  check) or `ME`, `LP`, `NO` or a stream id. It sets the LO option (X'1') and ends the command
  (J:TELFLGS X'20000': anything more is a syntax error).

Every set **replaces** the earlier sets for its DCB (`ASSIGN`, `:4783`). The others stay in
the record from one command to the next, except `M:SI`. Unless this command gave a source,
`GROUP2C` releases the `M:SI` sets (`GRPEXT`, `:497`–`:498`). If the record then has no `M:GO`
set, TEL adds the default (`%ROM`, §3). The options go into `JSTDOPT` and stay there too: at the
step, `J:OPT` = `JSTDOPT` with X'10' (SI) added (`:507`–`:510`). `RESET` (`:1300`–`:1311`)
empties the record.

For an unrecognized load module, a **syntax error doesn't stop the command**. `CHKULM`
(`:950`) ignores it and runs the program with the sets made so far. `FILE: ME ILLEGAL` is
ignored the same way (`:725`–`:727`).

## 2. The sets

Each set holds the DCB's name (TEXTC) and an OPEN parameter list. Two skeletons:

**A file** (`PLIST`, `:4093`–`:4106`; `FILENT` fills it in, `:6031`–`:6063`):

| Word | Value | |
|---|---|---|
| 0 | X'14000000' | OPEN, the DCB address (the step fills it in, `ASM8`) |
| 1 | X'0000E001' | X'2000' the "A" form, X'4000' VLPs follow, ASN 1 (a file) |
| 2 | X'01400000' | The presence bits: FUN and FOPT |
| 3 | 2 | FUN: OUT (1, IN, for `M:SI`) |
| 4 | 2 | FOPT: SAVE |
| 5–8 | X'01000303', name | The name VLP, a TEXTC |
| 9–11 | X'02000202', account | The account (the log-on account if none is given) |
| 12–14 | X'03010002' or X'03010202' | The password VLP, with 2 words used if a password is given |

**A device** (`OPENME`, `:4024`–`:4027`): X'14000000', X'0000A000' (the "A" form, no VLPs),
X'00040000' (the device option is present), and the operational label right-justified:
`UC` for `ME`, or `LP`, `NO`, `CP`, or a stream id.

**The "A" form** (`MSROPN`, OPN.txt:107–:114): when word 1's X'2000' is set, the presence bits
are in the next word, and the parameters follow it. With the "A" form, VLPs follow if word 1
has X'4000' (`CAL11N9`, `:258`–`:265`); in the standard form, if its low 10 bits are nonzero.

## 3. The default object file

When no object is given, the `%ROM` set (`:794`–`:808`, `NAME%`, `:6075`–`:6081`) names a
file after the user: the low halfword of `J:JIT` (the user number), then `G`. That's a
3-character name, two of them binary, in the log-on account, mode OUT.

The step does the same for any program that has an `M:GO` DCB (`ASM2`, STPNR.txt:2605–:2641).
Before the merge, `M:GO` becomes that file: ASN 1, function OUT, and its name VLP set to
`[user number]G`.

## 4. At the step: the merge

`ASP17` (STPNR.txt:2595) runs when a program is fetched. `ASP175`–`ASM2` clear each DCB's open
bits ("to guarantee the security checks upon open") and set `M:GO`'s defaults (§3). `ASM3`
reads the record (CAL1,1 X'2D' through `T:AMRDWT`), then `ASM4`–`ASM8` look for each set's DCB
name in the program's DCB table (`J:DCBLINK`). For each one found, the set's word 0 gets the
DCB address, and the set goes to **MSROPN** (`OVERLAY OPNSEG,0`). A set whose DCB isn't in
the table is skipped.

MSROPN **merges the set without opening the DCB**. After the parameters and VLPs, an "A"-form
FPT without X'1000' leaves through `OPNPXIT` = `OPNX` (`MSROPN7`, OPN.txt:388–:394;
`MSROPN7P`, :400–:403; :487), before `SETFUN` and the open. A device set's operational label
goes into the DCB's DSI (word 1) as a name, X'10000' plus the label (`MSROPN5`, :689–:694). The
program then opens the DCB itself, on the merged assignment. AP needs this: it opens `M:LO`
with an error routine (`OPENLO`, `CI$APCCI.txt:917`), so an `M:LO` the step had already opened
would end AP with X'2E', OPEN AN OPEN DCB.

At the step's end, `CLOSEDCBS` (STPNR.txt:873–:892, `CLSDCBS` :1164–:1242) closes M:XX and
every DCB in the table that is still open.

## 5. What AP does with it

AP finds out whether it runs on-line through **`CJOB`**, monitor word X'4F', which holds
`J:JIT`'s address. A program tests the JIT's first word through it, `MTW,0 *X'4F'`: negative
for on-line (`CI$APCCI.txt:263`; PASS3.txt:1329 "ADDRESS IN MONITOR TO FIND JIT"; DEF.txt:73).

On-line, AP reads `J:OPT` (`:263`–`:272`): LOBIT (1) sets its LO option and GOBIT (X'80') its
GO option. Then it sets the prompt `>`, types ` TELEFILE ASSEMBLY PROGRAM` and ` OPTIONS`
(`SALUTE%START`, `:178`–`:181`, with an EBCDIC CR between them), and reads one line of options
from `M:C`. The processor name isn't repeated there (`B %20` skips that part of the card scan),
blanks are ignored, and an empty line takes the defaults. SI is the default when CI isn't
given (`:702`–`:706`). So after `AP X OVER Y,Z`, pressing Enter assembles file X, writes the
object to Y and lists to Z. In batch, AP reads the whole control card, `AP SI,LO,...`,
processor name included.

**Observed with the tape's AP** (older than H00): LO and GO typed at `OPTIONS` are accepted
(no `ILLEGAL OPTION IGNORED`) but change nothing. On-line, its listing and object come only
from TEL's `J:OPT` bits. In H00 they also come from the line (`ASSEMBLE%FLAG`, `:686`–`:690`).
That this is the older AP's behavior and not the model's isn't proven, since the tape version's
source isn't here.

## 6. Reading and writing the record: `T:AMRDWT`

CAL1,1 X'2D' reads the record and X'2E' writes it (`T:AMRDWT`, STPNR.txt:3628–:3700). The
FPT's ERR and ABN go to the JIT, and its buffer and byte count are taken as for a read (the
fast path, IORT.txt:345–:366). The record is a granule whose disc address is in **J:AMR**
(JIT word 351: J:BUP + 77, counting the 11-word `DO` block at JIT.txt:710). Its layout:

| Word | |
|---|---|
| 0 | The next free word (TEL's RESET: 22) |
| 1 | The offset of the first set, 0 if none |
| 3–5, 6–7 | The load module's name and password (LOADR.txt:403–:415) |
| 13 | The user's number: a read checks it against J:JIT (STPNR.txt:3686–:3690, X'A9') |
| 22 on | The sets: a link to the next (an offset, 0 for the last), the DCB name (TEXTC), the OPEN list |

- **Read:** with J:AMR 0, end of file (X'06'). The byte count must be 1 to 2048 (`BUFCHK`,
  X'4A').
- **Write:** only for a command processor (TIC), the step or special JIT access (`FLAGCHK`),
  else X'14'.
- **Errors:** they leave through `MSR01EXIT`, which takes the DCB's own routines.

LOADER reads the record to find `F:n` assignments, which become references (IN1.txt:756–:813).
The tape's LOADER reads it whenever the LOCCT says assignments exist (LOCWD X'200'); the source's
extra J:AMR test (`MTW,0 J:AMR`, :754) isn't in its code. The on-line user's record comes into
being at LOGON, as TEL requires one (TEL.txt:363–:366).

## In the translation

`python/uts/assign.py` translates §1–§4:
- `parse`: TEL's `PARSER` for an unrecognized load module, into the user's record
  (`cal.amr`) and options (`cal.stdopt`). It returns TEL's message, if any.
- `step`: `GROUP2C`'s SI release and `%ROM` default, and `J:OPT` for the program.
- `merge`: `ASM2`'s `M:GO` default, then `ASM4`–`ASM8` (`cal.step_merge`).

`cal.py`'s step end (`_hook`, and `T:TELDELCCI` in `online.py`) closes the program's open
DCBs (`_close_all`). Before this, files a program left open were never entered in their
directory.

`cal.py`'s OPEN understands the "A" form (`_fpt_layout`). `jit.py` puts `J:OPT` at word 228
and `CJOB` (X'8C00') at word X'4F' of the program's memory; before that, every program took
itself for a batch job there
(JIT.txt's 224, plus CP-V's 4 extra words). `online.py`'s TEL calls `parse` for any program
named with more on the line.

**Departures:**
- **Where the record is kept.** The sets are a Python list per user (`cal.amr`), with the
  header words as last written (`cal.amr_header`), not a granule on disc. `T:AMRDWT` (CAL1,1
  X'2D' and X'2E', below) makes CP-V's layout from them and parses it back, so programs see the
  real record. J:AMR (JIT word 351) is 1, not a disc address, when the user has a record.
- **Not translated:** TEL's own verbs that take this syntax (`META`/`ASSEMBLE`, `LINK`, `RUN`,
  `START`, `SET`, `LIST`/`OUTPUT`/`COMMENT`) and `RESET`. Likewise passwords beyond the VLP,
  streams other than the ones `devopen.py` knows, and `UNDER DELTA`.
- **Syntax errors are reported** as `EH?` for a recognized verb, as the stand-in already does.
  For an unrecognized load module they're ignored, as in CP-V.
