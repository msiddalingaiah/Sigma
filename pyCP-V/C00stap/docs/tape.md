# The UTS system tape and boot-time patching

What SYSGEN WRITEMON (`UTMBPMBT`) puts on the BO/PO tape, how a tape boot (`TBOOT:` in `BOOTSUBR`)
reads it back, and how XDELTA applies the patch deck that is interleaved with the segments.
[`boot.md`](boot.md) has the overall boot process. This document covers the record-level details
that the writer and the reader have to agree on.

> Source paths are relative to `c00co/`. Sigma memory is word-addressed. Tape records and I/O byte
> counts are in bytes; a page is 512 words (2048 bytes); a doubleword (dw) is 2 words.

## 1. Tape layout

Every record WRITEMON writes is 2048 bytes (one page), except the patch cards, which are 80 bytes.

| # | Records | Written by | Read by |
|---|---|---|---|
| 1 | `MTBOOT`, the tape bootstrap | `WRTD1` at `UTMBPMBT.txt:88` | the hardware boot, into X'2A' |
| 2 | The monitor root: *N* page records | `RMON`/`WMON` (`:94`) | `MTBOOT` |
| 3 | The creation-data record (`GENINFO`) | `UTMBPMBT.txt:243` | `TBOOT:` (`BOOTSUBR.txt:601`) |
| 4 | XDELTA: a head record, then its pages with the symbol table appended | `NXTULBL` loop (`:268`) | `TBOOT:` (`BOOTSUBR.txt:655`) |
| 5 | Root patch cards (segment 0) | `RPATCH` (`:428`) | XDELTA |
| 6 | For each of ALLOCAT, GHOST1, FIX, each overlay in name order, then RECOVER: a head record, then its data, DCB and procedure pages, each piece followed by its patch cards | `NXTULBL` / `WPROT` / `RPATCH` | `SWAPINIT`/`RECOV` (`BOOTSUBR.txt:1036`, `:1127`) and XDELTA |

The symbol table built from `M:MON` (`SYMGEN`, `UTMBPMBT.txt:114`) isn't written to the tape on its own.
It goes to the temporary file `M:TEMP` and is written out with XDELTA's pages (see §4).

### 1.1 `MTBOOT` (`UTMBPMBT.txt:800`)

`MTBOOT` is assembled to run at X'2A' (`LOC A+X'2A'`). WRITEMON patches two fields before writing it:

- **The record count** in its first instruction, `LI,1 0` (`STS,6 MTBOOT`, `:85`). This is the root size
  from the `M:MON` tree, rounded up to whole pages.
- **The exit branch** `STRTADRT B 0`, set to the start address from the `M:MON` head (`STS,6 STMONMTB`, `:76`).
  The comment calls this "INITIAL".

The loop reads from the device at X'25' (`SIO,0 *37`), with up to 10 retries per record (`RETRY`). The
first read goes to X'5A' (`MTCDW`: `GEN,8,24 2,90*4`). Each later read starts (512−90)×4 bytes further
on for the first step and X'800' bytes after that. This is because WRITEMON writes the first root record
starting at word X'5A' of the root's first page (`AI,15 90`, `:93`). The first record therefore holds
X'5A'–X'259', overlapping the second record by X'5A' words.

Because the bootstrap itself occupies X'2A', on a tape boot that location holds `MTBOOT`'s first
instruction (`LI,1 n`), not one of the codes in the boot-type table in `boot.md`.

### 1.2 The creation-data record (`GENINFO`, `UTMBPMBT.txt:776`)

The record is a header word followed by 24-byte lines (`MSZ` = 6 words):

- **Header word:** byte 0 is the word offset of `VERSION` within the record. Bytes 1–3 are the number
  of lines.
- **Fixed lines** (`M1` up to `M7`): a blank line, `***`, `C P - V`, `SYSTEM GENERATED ON:`, the
  `M:TIME` date/time, `VERSION NO. IS: xxxx`, `***`, `PATCH SEGMENT NAMES:` and `(ROOT)`.
- **One line per patch segment name**, built in the `LOOP` at `:183`. Each one increments the line
  count (`MTW,1 *3`).
- **The tail** (`M7`, `M7:2`, `HGPINFO`).

The assembled count is (`ENDINFO`−`M1`)/`MSZ` = 11 (the 11 fixed and tail lines, with the extra `HGPINFO` word
dropped by the division). So **the line count is 11 plus the number of segment names**. `TBOOT:` makes use of this:

- `MAXSEG LI,2 -11` (`BOOTSUBR.txt:674`) has the line count added to it (`AWM,3 MAXSEG`, `:619`). The
  20-bit immediate −11 (X'FFFF5') carries into the register field, so the instruction becomes
  `LI,3 <number of segment names>`. The comment says "BECOMES LI,3 MAXSEG". That value reaches
  XDELTA in R3 as the highest segment number (`STW,3 MAXSEG`, `XDLT.txt:3283`).
- The lines are printed on the LP (P flag), with byte 0 of each line replaced by a newline (`PRNT`,
  `BOOTSUBR.txt:635`). They are also typed as one message on the OC (I flag, `DATCLSTT`).
- **`SYSVERS`** (`BOOTSUBR.txt:602`–`:618`): `LW,4 INFOBUF,3` loads the version word *v*. Then
  `SLD,4 -4` / `SLS,4 -12` / `SLD,4 4` leave R4's low byte equal to
  ((*v* >> 16) & X'F) << 4 | (*v* & X'F). That is, the low nibbles of version characters 2 and 4, which
  for digits are the digit values. `STB,4 5` puts that byte into byte 0 of R5. R5 holds X'4170', plus X'4000'
  per step from Sigma 7 to Sigma 9 to 560. `SCS,5 -8` rotates the word right 8 bits, and the result
  is stored in `SYSVERS`.

### 1.3 Patch segment names

The patch segment names are the names patch cards use to say which piece of code they apply to.
There is one name per **piece** that `TBOOT:` copies, not one per module (`UTMBPMBT.txt:166`, "EACH
GHOST HAS 2 MORE EXCEPT ALLOCAT"):

- The shared processors (`NONOVS`: ALLOCAT, GHOST1, FIX) have a name for each of their data, DCB and
  procedure pieces. ALLOCAT has no DCB piece (`PT01`, "SKIP DCBS IF ALLOCAT"). Each name
  is the module name plus a digit. Tracing the `LOOP` through `RECVEC` for GHOST1 gives
  `GHOST10`, `GHOST12` and `GHOST11` for data, DCBs and procedure, which matches
  `MIDSEG`'s comment "ADDRESS OF GHOST11'S NAME". The digit looks like the CSECT number
  (0 data, 1 procedure, 2 DCBs). ALLOCAT's path through `PT01` hasn't been traced.
- Each overlay has one name.
- RECOVER is put at the end of the list (`XRECVR`, `:156`).
- The root is segment 0.

The names become XDELTA symbols whose value is the segment number (`STW,8 0,7` in the `LOOP`). The
segment numbers match the order in which `TBOOT:` calls `SEGPATCH` (§3).

### 1.4 Segment head records

Each module starts with a 2048-byte head record. For the shared processors and XDELTA it is the load
module's own head. For overlays, which have no head of their own in `M:MON`, WRITEMON builds one
(`UTMBPMBT.txt:276`): byte 0 is X'85', the start address is X'8000', and the bias is X'4000' dw (page X'40',
`JOVVP`). The words `TBOOT:` reads (`PARSHEAD`, `BOOTSUBR.txt:1064`) are:

| Word | Contents | Used for |
|---|---|---|
| 1 | Start address (low 17 bits) | `P:SA` |
| 2 | Halfword 0: TCB address in dw | `P:TCB` (shifted left 1, so in words) |
| 3 | Data: halfword 0 = size in dw, halfword 1 = bias in dw | `PB:DSZ` |
| 4 | Procedure: same layout | `PB:PSZ`, `PB:PVA`, `PB:HVA` |
| 6 | DCBs: same layout | `PB:DCBSZ` |
| 7 | Symbol-table size in bytes | written into XDELTA word 4, as words (`GETHEAD`) |

`TBOOT:` reads the sizes in pages with `LB`, which works because the high byte of a doubleword count
is a page count (256 dw = 1 page). In the same way the high byte of a bias is its page number:
`PB:PVA` is the bias page and `PB:HVA` is `PB:PVA` + `PB:PSZ`.

Two transformations apply to overlays:

- **Data becomes procedure.** An overlay is assembled as data. WRITEMON moves the data word into the
  procedure word and clears the data and DCB words (`XW,1 3,2` / `STW,1 4,2` / `ZAPDCBS`,
  `UTMBPMBT.txt:319`).
- **UMOV.** If an overlay at bias X'4000' is at least X'700' dw (7 pages), WRITEMON assumes it is UMOV.
  It takes 7 pages off the size, sets the bias to X'4700' (page X'47', `JJITVP`+1), and checks that the
  name is `UMOV` (`WHEAD`, `:337`). Any other name aborts with `OVERLAY EXCEEDS 6 PAGES`. The overlay
  area is pages X'40'–X'45', which is six pages; the next page is the monitor JIT.

The pieces follow the head in the order data, DCBs, procedure (`RECVEC`, `:744`). Each is a whole number of
page records, and a piece of size 0 is left out.

XDELTA's head also gives its bias and start address in word 1 (`INT,15 INFOBUF+1` → `DLTBIAS`) and its
page count in byte 0 of word 4 (`LB,7 INFOBUF+4`). After reading the first page, WRITEMON moves XDELTA's
next-symbol pointer past the appended symbol table. It aborts with `XDELTA TOO BIG - REDUCE ITS BIAS` if
that pointer plus a 30-word hole goes past X'10000' (`WPAGE1`, `:397`).

## 2. Patch cards on the tape

### 2.1 How WRITEMON places them (`RPATCH`, `UTMBPMBT.txt:428`)

After writing the records of a piece, WRITEMON copies cards from the `PATCH` file (`M:PATCH`, 80-byte
records) onto the tape. It stops after the first card that names a later segment. That card is
written, and then WRITEMON skips the following pieces (`SEGCNT`) until it reaches the piece the card
names. A card for an earlier segment aborts with `OUT OF ORDER PATCH`.

- Cards starting with `/`, `<` or `#` (`PSTART`) are copied without a segment check.
- A card whose segment field isn't a known name is copied as part of the current segment.
- When the file runs out, WRITEMON writes an `*` card (`ASTBANG`). It then changes `ASTBANG` to `!`
  (`MTB,-2 ASTBANG`, `:474`; X'5C'→X'5A'), sets the skip count to the last segment, and writes the
  `!` card after RECOVER. If the file has its own `*` card, the cards after it are written after the
  last segment in the same way.

So on the tape, each piece is followed by the cards for that piece plus one card that looks ahead
to a later segment.

### 2.2 Why `TBOOT:` isn't confused by cards it doesn't read

`TBOOT:` reads segment records 2048 bytes at a time (`TREAD`, `RTAPE`). If the next record is an 80-byte
card, the read ends with incorrect length. `ERROREC`'s tape recovery (`TPREC`, `BOOTSUBR.txt:939`)
treats a residual count of 2048−80 as "ignore and retry" (`CI,1 2048-80` / `BE RTNXIT`). The retry
reads the next record. So cards that XDELTA hasn't consumed, for example on a boot without the T
flag, are skipped without any error.

### 2.3 How XDELTA reads them (`PACHSTRT`, `XDLT.txt:3238`)

`TBOOT:` enters XDELTA through `SEGPATCH` (`BOOTSUBR.txt:675`). `SEGPATCH` increments `SEGNO`, loads it into
R1 and branches to `PACHSTRT`; the branch address in `BPCH` has been offset by `DLTBIAS`. The first
call is for segment 0 and returns to `SWAPINIT` (`LI,11 SWAPINIT`). After that, `RWDSK` calls it once
for each piece, after reading the piece into the buffer and before writing it to disc.

- **First call (segment 0):** XDELTA works out where to keep the patch file on the swapper
  (`MPRREL`). On a RAD this is `PSA%END`−420 sectors (`RADSWAP`). It records `MAXSEG`, and picks the
  card source from `BOOTFLG`: tape if T, cards if C, and both if both are set, starting with cards (`INIT0`).
- **`GETACARD`** (`:3298`) reads a card and dispatches on its first character:
  - `:` goes to RECONFIG through `RECNFG` (see `boot.md` §6).
  - `#` defines a symbol.
  - `*` ends patching (`EXITP0`): the segment number becomes "infinite", so later calls return straight away.
  - `<` is a comment.
  - Anything else is a patch, with fields separated by `/`. The first field is the segment, an
    expression usually naming a patch segment name; it is evaluated and must not exceed `MAXSEG`.
- **`CHKSEG`** (`:3343`): if the card's segment is below the current `SEGNUM`, that's an error. If it is
  above, XDELTA returns to `TBOOT:` and keeps the card for later. If it is equal, `ANALSTOR` evaluates
  the location and value, checks an optional old value given in parentheses, and stores the new
  value. For segment 0 the store goes to the absolute location. Otherwise the location is converted
  to a position in the piece's buffer, and must fit within the piece (`SEGBASE`, `SEGMAX`). Locations
  in the registers or above 64K are rejected.
- Every card is also saved in the patch file on the swapper (`MOVCARD` / `MPRFILE`). With the P flag
  each card is listed on the LP.
- **Last segment** (`EXITP3`, `:3521`): when `SEGNUM` = `MAXSEG`, XDELTA copies the rest of the deck
  up to the `!` card into the patch file (`EXIT1`). It then turns off further patching and, with the I
  flag, reports the number of cards and how much of the patch area (`MPATCH`, ending at `MX:PPUT`) is left.
- **Reading a card** (`READCARD`, `:3633`): with neither T nor C set, no card is read, and the
  first byte of the card image is changed so that it reads as the end of the deck. Otherwise the card
  is read through `ERROREC` (code 0 for tape, 1 for cards), with incorrect length suppressed.

The patch expression syntax and evaluator are the rest of XDELTA's debugger (`DRINITB`, `DREVALIT`),
and aren't described here.

## 3. The order of `SEGPATCH` calls

| `SEGNO` | Called from | Piece |
|---|---|---|
| 0 | after loading XDELTA (`BOOTSUBR.txt:673`) | the root |
| 1, 2 | `RWDSK` | ALLOCAT data, procedure |
| 3, 4, 5 | `RWDSK` | GHOST1 data, DCBs, procedure |
| 6, 7, 8 | `RWDSK` | FIX data, DCBs, procedure |
| … | `RWDSK` | each overlay (procedure only) |
| `MAXSEG` | `RWDSK` from `RECOV` | RECOVER |

This assumes each ghost piece exists. A piece of size 0 is neither written by WRITEMON nor read by
`TBOOT:`, so both sides skip the number. The table also assumes the segment names are in the same
order: shared processors, then overlays, then RECOVER.

## Open questions

- **The `SEGCNT` arithmetic:** WRITEMON counts its skip in steps of 3 (`MTW,-3 SEGCNT`), the size of a
  segment-name table entry. §2.1 describes the effect, not the exact bookkeeping.
- **Overlay head words:** for overlays WRITEMON builds word 3 from the saved segment number, page
  count and the X'4000' bias with halfword stores (`UTMBPMBT.txt:276`–`:284`). The exact contents of
  halfword 0 before the data-to-procedure move haven't been traced.
- **The T and C merge:** with both flags set, `EXITP` (`XDLT.txt:3493`) switches between the two
  devices by comparing their next segment names. The tape is read first the first time.
