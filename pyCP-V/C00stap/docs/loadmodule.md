# Load modules

A **load module** is a program ready to run: the overlay loader (`LDR`) or `LINK` writes it as a
keyed file, and the step's **FETCH** reads it into the user's memory when the program is started.
This document covers the records FETCH and the command interpreter read, which is what's needed
to start one. It was checked against three real load modules from the UTIL tape: `SLIP`,
`SLPUNCH` and `SLUPDATE` ([`labtape.md`](labtape.md)).

> Source: `STPNR.txt` (FETCH, `:2847`–`:3475`; the setup after it, `XIT10`–`XIT40`,
> `:1325`–`:1590`) and `CCIR.txt` (`!RUN`, `:802`–`:870`). Comments of the form `:NNN` point at
> `STPNR.txt` unless another file is named.

## 1. The records

| Key | Holds |
|---|---|
| `HEAD` | The header: 12 words |
| `TREE` | The overlay tree: an 11-word entry per segment, after a word with the tree's size |
| segment name + `X'03'` | The segment's **data** section |
| segment name + `X'05'` | Its **procedure** section |
| segment name + `X'07'` | Its **DCBs** |
| segment name + `X'00'` | Not read by FETCH. On the UTIL tape it is the segment's symbol table: names (`M:DO`, `SIBUFF`, `BIN2ECD`, …) with their values |

FETCH builds a section's key from the segment's name in the tree entry (`LMKEY`, `TBUF+1`,
`:2841`). It lengthens the name by a byte (`:3102`) and stores the section's type in it: 3, 5
or 7 (`:3104`, `:3118`, `:3121`; `FETCH1`, `:3398`–`:3399`).

## 2. `HEAD`

Read first, as 12 words (`:2942`). It must be 48 bytes (`SMALLHEAD`, `:2965`–`:2967`;
`CCIR.txt:831`–`:835`).

| Word | Holds |
|---|---|
| 0 | Byte 0: the kind. Bit 0 set (`CCIR.txt:832`); `X'84'`, built by `LINK` (`:1391`); `X'85'`, a paged load module (`:2978`). The bits of `HEADMASK`, `X'78FF0000'`, must be clear (`:426`, `:2973`). The UTIL modules have `X'80'`, built by the overlay loader, and `X'30'` (48) in the last byte |
| 1 | The start address, in the right 17 bits (`:1505`) |
| 2 | Halfword 0: the TCB's doubleword address, 0 if none (`:1507`). The rest: the bias, which must be on a page boundary, as must words 4 and 6 (`:2981`–`:2992`) |
| 3, 4, 6 | The data, procedure and DCB areas overall: the size in the left halfword, the bias in the right, in doublewords (`LINKLIMS`, `:1359`–`:1384`, `:1622`–`:1641`) |
| 9–10 | The core library's name, if one is needed (`:1534`) |
| 12–13 | The debugger's name, if one is needed (`:1535`) |

## 3. `TREE`

Word 0 is the tree's size in words (`:1482`). Then come the entries, 11 words each (`TTESIZE`;
`:3364`). For the root, FETCH reads (`:3100`–`:3123`):

| Word | Holds |
|---|---|
| 1–3 | The segment's name: a byte count and the name |
| 6 | The data section |
| 8 | The procedure section |
| 10 | The DCBs |

A section word is the size in its left halfword and the address in its right, both in
doublewords (`FETCH45`: `SLS,6 3` to bytes and `SLS,7 1` to a word address, `:3439`–`:3442`).
FETCH reads the section's record to that address. A section of size 0 isn't read. A tree of
12 words is the root alone: no overlays, so no `M:SEGLD` (`:1482`–`:1485`).

## 4. Starting the program

After FETCH, the step sets up the user (`XIT10`–`XIT39`):
- **Memory limits** for the data, procedure and DCB areas, from `HEAD` and the root's entry
  (`:1357`–`:1384`).
- **`J:DCBLINK`**, the DCB name table (`:1443`–`:1453`): word 10 of the TCB if there is one,
  otherwise the start of the DCB area.
- **The DCB checker** (`DCBCHK`) initializes the DCBs (`:1456`–`:1478`).
- **`J:START`** from `HEAD` word 1, **`J:TCB`** from word 2, and the TCB's address in the
  user's register 0 (`:1503`–`:1519`).
- A module built by `LINK` has no tree in memory. Otherwise the tree is in the first page of
  procedure (`:1523`–`:1529`).

## The UTIL load modules

| | `SLIP` | `SLPUNCH` | `SLUPDATE` |
|---|---|---|---|
| Start | `X'A064'` | `X'A064'` | `X'A064'` |
| Data (type 3) | 7,768 bytes at `X'A000'` | 9,464 at `X'A000'` | 7,912 at `X'A000'` |
| Procedure (type 5) | 48 at `X'AC00'` | 48 at `X'AE00'` | 48 at `X'AC00'` |
| DCBs (type 7) | 4,096 at `X'A800'` | 4,096 at `X'AA00'` | 4,096 at `X'A800'` |
| TCB | `X'A000'` | `X'A000'` | `X'A000'` |
| Tree | 12 words: no overlays | the same | the same |

Each section record is exactly the size its tree word gives, and lies in the area `HEAD` gives
for it: in SLIP, word 3 is `X'04005000'`, data of `X'400'` doublewords (2,048 words) from word
`X'A000'`; word 6 is `X'02005400'`, DCBs from `X'A800'`; word 4 is `X'01005600'`, procedure
from `X'AC00'`. Word 2 is `X'50005000'`: the TCB at `X'A000'` and the bias. SLIP's TCB word 10 is `X'A800'`,
the DCB table, which names `M:DO`, `F:1`–`F:9`, `M:EI`, `M:LL`, `M:OC`, `M:SI` and `M:LO`. The
JCL that built SLIP is on the same tape:

```
!LOAD (LMN,SLIP),(EF,(CDTBO),(VFYBO),(CPYBO)),(MAP),(SL,F),(PERM)
```

## Writing one

The translation's assembler writes its output as a one-segment load module
(`fetch.write_load_module`). That is a stand-in for the overlay loader's output, not a translation
of the loader. It follows the layout of SLIP's module and meets FETCH's checks:

| Record | Holds |
|---|---|
| `HEAD` | Word 0 `X'8000FF30'` (built by the overlay loader, 48 bytes); word 1, the start address with bit 0 set; word 2, the TCB's doubleword address and the module's bias; word 3, the data area; word 4, 0 (no procedure); word 6, the DCB area. Each area is whole pages, from a page boundary. The words FETCH doesn't read are 0 |
| `TREE` | One 12-word entry: the program's name (up to 7 characters), the data section's size and bias in word 6, the DCBs' in word 10 |
| name + `X'03'` | The data section: every word assembled, code included (as in SLIP), from the page the program starts in, then a 16-word **TCB**, whose word 10 holds the DCB table's address |
| name + `X'07'` | The DCB section, on the next page: the DCB table (word 0, the address of its last word; then each `F:` or `M:` label's name and address; a zero word). The DCBs themselves stay where they were assembled, in the data section |

There is no symbol-table record (type 0), and the module has no overlays. Its key length is 15,
as the UTIL modules' 16-byte key areas suggest. Writing a module replaces any old contents.

## In the translation

`python/uts/fetch.py` translates FETCH's part of the step:
- the checks of `HEAD` and `TREE`, with the A6 codes (`BADHEAD` X'31' to `BADTCB` X'3B',
  `STPNR.txt:432`–`:441`);
- the root's data, procedure and DCB sections read to their addresses;
- `J:START`, the TCB's address in register 0, and `J:DCBLINK`, from the TCB's word 10.

The DCB table is walked as `CAL11M` walks it (`CALPROC.txt:164`–`:190`). Each entry is the DCB's
name, a byte count and up to 7 characters in one or two words, then its address. A zero word
ends the table. The first entry, `M:*`, is the CFU area and isn't a DCB (`TXTCFU`,
`CALPROC.txt:166`; "IS IT M:*", `STPNR.txt:3208`). In SLIP the names' padding holds other
bytes (`M:DO` is `04 D4 7A C4 D6 00 01 EC`), which `CAL11M` never reads.

A program started by name, from TEL (`SLIP.:UTIL`, `RUN SLIP.:UTIL`) or by `GJOB`, is fetched if
it is a load module, and runs on the interpreter ([`interpreter.md`](interpreter.md)).

Not translated:
- memory limits and access codes (`LINKLIMS`), page allocation and cleaning;
- the DCB checker (`DCBCHK`), core libraries, debuggers and the runner;
- LINK-built (X'84') and paged (X'85') modules, and overlays (`M:SEGLD`): they stop with
  `NotTranslated`.

**SLIP's first instruction** is `CAL1,1` with an `M:OPEN` of `M:SI`, followed by two more
`CAL1,1`s. `M:SI` is a device DCB: word 1 holds operational label 9 rather than a file name.
Opening a device DCB is [`devopen.md`](devopen.md): for an on-line user, `CR` can't be had, and SLIP goes to its error routine. On a terminal, an on-line user's
program that reaches untranslated code reports `NOT TRANSLATED:` and TEL takes the terminal back.

## Open questions

- **The tree entry's other words** (4–5, 7, 9) and **`HEAD`'s words 5, 7, 8 and 11** weren't
  traced. In the UTIL modules, word 5 is `X'0131000C'` and word 8 `X'0001C000'`.
- **The symbol table record** (type 0): its entry format wasn't traced, only seen.
- **The DCB table's word 0** is `X'A827'` in SLIP, the address of the zero word that ends the
  table. `CAL11M` starts at word 1. Who reads word 0 wasn't traced.
- **The label in a device DCB's word 1**: SLIP's are numbers (`M:SI` 9, `M:LO` 3, `M:OC` 2,
  `M:DO` 5), except `F:1`, which holds `ME` in EBCDIC. That they index the operational labels
  is a guess, for `OPLO.txt` to settle.
