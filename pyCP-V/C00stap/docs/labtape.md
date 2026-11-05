# Labeled tapes

The monitor writes files to tape with **labeled-tape I/O**: sentinels mark the reel and each file,
and the records are packed into fixed-size blocks with their keys. Account saves and software
distributions came this way. This document covers the format as far as is needed to read such a
tape back. It was checked against two real tape images: AP's SYSGEN tape (reel `APCA`, 29
files) and a utilities tape (reel `UTIL`, 16 files, three of them load modules).

> Source: `LBLT.txt` (the writer), `OPNL.txt` (open, the sentinels), `IORT.txt`. Comments of the
> form `:NNN` point at `LBLT.txt` unless another file is named. The reader is
> `python/uts/labtape.py`.

## 1. The image

A tape image is in simh's `.tap` format, which is the host's container, not CP-V's. Each tape
record is framed by its length (4 bytes, little-endian) before and after it. A zero length is a
**tape mark**, and `X'FFFFFFFF'` is the end of the medium.

## 2. The sentinels

The reel starts with two label records, then each file comes between sentinels, with tape
marks between the parts:

```
:LBL reel   :ACN account   TM
:BOF name   TM   data blocks ...   TM   :EOF   TM
:BOF name   TM   ...
```

- `:LBL` holds the reel's serial (`APCA`, `UTIL`). The text is `:LBL` in `OPNTP.txt:465`.
- `:ACN` holds the account the files belong to (`:SYSGEN`, `:UTIL`), then a date in EBCDIC
  (`0718  75`, `0308  82`). `OPNL` references it as `:ACN` (`OPNL.txt:102`–`:103`).
- `:BOF` begins a file. Its name is a byte count at byte 8 and the name after it, for example
  `05 APCCI`. OPNL looks for `:BOF` (`CBOF`, `OPNL.txt:104`–`:105`, `:279`) and moves the name
  into the DCB (`:345`–`:363`).
- `:EOF` ends a file (`CEOF`, `OPNL.txt:106`).

Bytes 4–7 of `:BOF` and the 8 bytes after `:EOF`'s tag weren't traced.

## 3. Blocks

A file's data is a series of **blocks** of `BUFSIZ` bytes, 2048 on both tapes. Each block
starts with a word:

| Halfword | Holds |
|---|---|
| 0 | `PBD`, the previous block's size: 0 for a file's first block, `X'0800'` after a full block, `X'FFFF'` after an unblocked record (`CLSTP.txt:305`, `OPNL.txt:244`–`:245`) |
| 1 | The number of entries in the block (`INITBLK`, `:671`–`:679`; `BCDA`, `:351`–`:353`) |

Then come the entries, each word-aligned:

```
key area | size word | data (padded to a word)
```

- **The key area** is the DCB's key buffer, copied whole: `GETKEYSB` moves `BASCR` bytes from
  `KBUF` (`IORT.txt:1216`–`:1220`), and LBLT rounds the key and size word up to words (`:366`–`:368`). It holds the
  key as a byte count and the key. After a short key come whatever bytes the buffer held before.
  On the UTIL tape, the load modules' 16-byte key areas carry `D:SLUPDA` after the key, from
  the file name `JCL:LOAD:SLUPDATE`. The area's size isn't written on the tape. It is 4 bytes for
  3-byte keys, 16 for the load modules.
- **The size word** (`SVSIZ`, `:652`–`:669`): the low 3 bytes are the size of the data in this
  entry, and byte 0 holds flags:

  | Flag | Meaning |
  |---|---|
  | `X'01'` | First piece of a record (`NLR`, positioned "AS FIRST SEGMENT FLAG", `:661`–`:667`) |
  | `X'02'` | More of this record follows: the entry is shorter than the record (`:655`–`:656`) |
  | `X'04'` | The data isn't in the block: it is the **next tape record**, written unblocked (`OR,R2 Y04`, `:438`) |

  So a whole record is 1 and a record split across blocks is 3 then 0, under the same key. A
  record longer than a block goes out as an entry flagged 5 and a block of its own, then the
  data as a tape record (`WRTL1`, `:409`–`:458`). On these tapes that happens to load module sections.
- **Keys** must ascend (`COMKEY`, `:460`–`:464`). A file written without keys gets
  **sequential keys**: 3 bytes, 0, 1, 2, … (`SKEY`, `:685`; `WRTL12`, "INCREASE SEQUENTIAL KEY",
  `:476`–`:477`). That is how a consecutive file goes to tape.

## In the translation

`python/uts/labtape.py` reads an image (`read_tape`): the reel, the account, and each file's
records, with pieces joined and unblocked records taken in. The key area is found by trying sizes
until the file parses. `restore` puts the files into the file system, in the tape's account. A
file with sequential keys becomes a **consecutive** file, any other a **keyed** file. That is a
host-side stand-in for copying the tape to disc (PCL or `FRES`), not a translation.

```powershell
python -m uts --replies 06/15/76 13:45 N --restore ..\c00si\sw-lib-utility-pgm-util.tap --terminals 2
```

From a terminal, `COPY SLIP.:UTIL TO ME(X)` then shows a load module's records
([`online.md`](online.md)).

## Open questions

- **`:BOF` and `:EOF`'s other bytes**: bytes 4–7 of `:BOF` (`01 00 08 08` on both tapes) and
  the 8 bytes after `:EOF`'s tag weren't traced, nor `:EOR`, which appears once on the UTIL tape.
- **The key area's size**: it comes from `BASCR`, which wasn't traced to the DCB's key length.
  The reader infers it.
- **ANS tapes**: the `HDR1`/`EOV` path (`OPNL.txt:277`, `LBLT.txt:557`–`:631`) isn't followed.
