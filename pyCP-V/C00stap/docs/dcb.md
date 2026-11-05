# The DCB in memory

A **data control block** is a block of words in the user's program, built by the `M:DCB`
procedure, that a CAL names in its FPT's word 0. The monitor reads and writes its fields in
place, at fixed word offsets with fixed bit positions. This document gives the layout the
file CALs use, so that a program run by the interpreter ([`interpreter.md`](interpreter.md)) can
do file I/O with its own DCBs.

> Sources: the field names and word numbers are `UTS.txt:525`–`:621`. Bit positions come from how
> the code tests and stores each field (cited per field). The `M:DCB` procedure itself isn't in
> this source set. The procedure that assembles the **system DCBs** (`M:C`, `M:OC`, `M:SI`, `M:LO`,
> ..., `UTS.txt:687`–`:782`) builds the same layout, and the same monitor code reads both.

## The words

| Word | Field | Bits | Contents | Source |
|---|---|---|---|---|
| 0 | size | 0–7 | The DCB's length in words, VLPs included (`SZ`) | `UTS.txt:735` |
| 0 | `FCD` | X'00200000' | **Open** | `IORT.txt:251`–`:252`, `:1099`–`:1101` |
| 0 | `WAT` | X'00100400' | The WAIT flag (where the FPT's flag lands, [`rdwr.md`](rdwr.md) open questions) | `IORT.txt:487`–`:489` |
| 0 | `EGV` | X'1000' | The TYC has been checked | `IORT.txt:758`–`:761` |
| 0 | `USR` | X'4000' | Not the user's own file ([`files.md`](files.md) §10) | `OBSE.txt:299`–`:304` |
| 0 | `BTD` | X'30' | The byte displacement (0–3) | `IORT.txt:444`–`:446`, `:533`–`:535` |
| 0 | `ASN` | X'F' | The assignment: 1 a file, 2 labeled tape, 3 a device, X'A' ANS tape | `IORT.txt:896`–`:898`, `UTS.txt:430` |
| 1 | `FUN` | bits 11–14 | The function: 1 IN, 2 OUT, 3 INOUT, 4 UPDATE, 8 OUTIN | `GETFUN`, `IORT.txt:182`–`:187`; `OBSE.txt:142`–`:146` |
| 1 | label / `CFU` / `DSI` | bits 15–31 | Before OPEN, the operation label (2 characters, bits 16–31). Once open, the CFU's address (a file) or the DCT index (a device) | `UTS.txt:736`; `CLS.txt:1454`–`:1456` |
| 2 | `NRA` | 0–7 | Retries (3) | `UTS.txt:737` |
| 2 | `TYC` | bits 8–14 | The completion type ([`rdwr.md`](rdwr.md) §7) | `GETTYC`, `IORT.txt:863`–`:865`; `SETTYC`, `:755`–`:757` |
| 2 | `BUF` | bits 15–31 | The buffer's word address | `IORT.txt:531`, `:773` |
| 3 | `RSZ` | bits 0–14 | The record size in bytes (the default for a CAL without one) | `SAVRSZ`, `IORT.txt:192`; `UTS.txt:738` |
| 3 | `ERA` | bits 15–31 | An error address | `UTS.txt:554` |
| 4 | `ARS` | bits 0–14 | The actual record size of the last transfer | `SAVARS`, `IORT.txt:195` |
| 4 | `ABA` | bits 15–31 | An abnormal address | `UTS.txt:556` |
| 5 | `ORG` | X'30' | The organization: 0 consecutive, X'10' random, X'20' keyed | `IORT.txt:413`–`:415`, [`files.md`](files.md) §4 |
| 6 | `FLP` | bits 15–31 | The word address of the VLP list | `UTS.txt:741`–`:755`; `OBSE.txt:118` |
| 10 | `KBUF` | bits 15–31 | The key buffer's word address | `UTS.txt:746`, `:775`–`:780` |
| 12 | `KEYM` | byte 0 | The maximum key length (keyed files) | `BAKEYM`, `UTS.txt:643` |
| 13 | `RWS` | | The size of the current request | `UTS.txt:591` |
| 18 | `KAD` | | The current request's key address | `UTS.txt:604` |
| 20 | `RSTORE` | | A new random file's size in granules ([`files.md`](files.md) §6) | `OPNF.txt:1061`; `GRAND.txt:61` |
| 21 | `DCBCDAM` | | The current granule (consecutive files) | `UTS.txt:621` |

Words 7–9, 11, 14–19 and 21 hold the monitor's working state for an open file: the queue
buffer, the blocking buffers, `CMD`, `BCDA`, `SCR` and the rest. A program doesn't touch them.

## The VLP list

At `FLP` is a list of **variable-length parameters** in the FIT's format ([`files.md`](files.md)
§3): a control word, then its data words.

| Byte of the control word | Contents |
|---|---|
| 0 | The code |
| 1 | The last-entry flag (the procedure stores 1, `UTS.txt:769`–`:774`) |
| 2 | Words used |
| 3 | Words reserved |

The system DCB procedure reserves these codes (`UTS.txt:694`–`:727`):

| Code | Holds | Words |
|---|---|---|
| 1 | The file name, TEXTC | 8 |
| 2 | The account | 2 |
| 3 | The password | 2 |
| 4 | The expiration date | 2 |
| 5, 6 | Read and write accounts | 16 each |
| 7, 8 | Input and output serial numbers (tapes) | 3 each |
| 11 | A synonym's name | 8 |
| 14 | Execute accounts | 16 |
| 15 | The execute vehicle | 3 |

OPEN finds them with `LOCCODEA` and `LOCCODEB` (`OBSE.txt:109`, `:118`), and CLOSE copies the
protection ones into a new FIT ([`files.md`](files.md) §10). A DCB without a name (code 1) is a
device DCB, such as `M:C` and `M:OC` (`UTS.txt:710`–`:711`).

## In the translation

`cal.py` keeps a DCB as a Python object (`sched.Dcb`), registered at an address
(`cal.add_dcb`). The system DCBs and the `cpv` library's DCBs stay that way. A DCB in a user's
memory, one an interpreted program assembled, is read through **`cal.MemDcb`**:
- **the fields above** are properties that read and write the words in place, so the program
  sees `FCD`, `TYC`, `ARS` and the rest change as on the machine;
- **the name, account, password and account lists** are read from the VLPs;
- **what has no place in this model's memory** (the CFU object, a consecutive file's position,
  the request's key, the last operation) is kept beside it, by address.

File DCBs (`ASN` 1) and device DCBs (`ASN` 3) in memory are handled. A device DCB is opened
by its operational label or name ([`devopen.md`](devopen.md)): on the terminal (COC), the
console, or the null device. Other assignments raise `NotTranslated`.

**The DCB table.** A CAL's DCB must also be in the user's DCB table, `J:DCBLINK`: `CAL11M`
aborts the user with X'AF', "ILLEGAL-DCB", otherwise (`CALPROC.txt:156`; `cal.py` `cal11`). CP-V's
loader builds that table from the load module's DCBs. Here an assembled image carries a DCB
table, its labels that begin `F:` or `M:` (`python/uts/asm.py`). The loader stand-in
(`interp.program`) enters them in `J:DCBLINK` (`cal.dcbs`).

**Text.** Memory holds characters as Latin-1 for now ([`interpreter.md`](interpreter.md), open
questions), while the file system keeps names and protection in EBCDIC. So a protection VLP read
from memory is converted to EBCDIC before OPEN compares it.

Tests: `python/tests/test_interp.py`:
- a program opens its own DCB OUT, writes three records, closes, sets `FUN` to IN in place,
  reopens, and reads to the end of the file through its abnormal address;
- the DCB's fields (`FCD`, `TYC`, `ARS`) are left in memory;
- a missing file goes to the error address with X'03' in R10.

## Open questions

- **The `M:DCB` procedure** (the user's) wasn't found in this source set. Its layout is taken to
  be the system DCBs'.
- **Bit 15 of word 1**, between `FUN` and the label: the system procedure sets it (`GEN,15,1,16`,
  `UTS.txt:736`). Its meaning wasn't found.
- **`WAT`** is two bits apart, as [`rdwr.md`](rdwr.md) already notes.
- **The FPT's VLPs.** `M:OPEN` can also carry the name, account and other VLPs in its FPT (`FPARAM`,
  word 11), which OPEN moves into the DCB. That move (`MSRMOVE`, `OBSE.txt:165`) isn't translated.
  A program names its file in the DCB.
