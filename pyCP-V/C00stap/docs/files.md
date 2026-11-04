# The file system: directories, files and keyed files

How files are laid out on the disc: the account and file directories, the file information table
(FIT), and the three organizations. The main subject is **keyed files**: their master index, the
records it points to, how a key is found, how one is inserted, and the upper-level "pyramid"
rebuilt at close. The modules are large (about 25k lines), and this document describes the
structures and the main algorithms. Most layouts below are taken from what the code *checks* or
*builds*, especially the start-up repair program FIX1, whose job is to validate every one of them.

> Source paths are relative to `c00co/`. The layouts are named in `UTS.txt:448`–`:530` (the CFU,
> index blocks and DCB) and checked in `FIX1.txt` (`VALBUF` `:2103`, `FNDKEY` `:2194`, `FITCHK`
> `:1758`, `CHKCON` `:1944`). Open is `OPNF.txt`, close `CLS.txt`, read `RDF.txt` (keyed lookup
> `SETUPUB`, `:1575`), write `WRTF.txt` (key insertion `INST`, `:600`), and the pyramid `MUL.txt`.
> Granules are allocated by `GRAN.txt`/`GRANSUB.txt` and the ALLOCAT ghost (`ALLYCAT.txt`).

## Overview

```
ACCOUNT DIRECTORY (ACNCFU's FDA; on a private pack at DPADFDA)       index-format chain,
   entry: account (TEXTC, 8 chars) ─► the account's file directory     main + dual copy
        │
FILE DIRECTORY (one per account)                                       index-format chain,
   entry: file name (TEXTC, up to 31) ─► disc address of the FIT       main + dual copy
        │
THE FILE'S FIRST GRANULE: the FIT (name, VLPs: organization, key size, disc addresses)
        │
   consecutive (ORG 1)          keyed (ORG 2)                          random (ORG 3)
   chain of data granules:      master index (level 0): chain of       FIT in its own granule
   control words + records      index blocks, entries in key order     (SREC); data contiguous:
   (FIT shares the first)       key → (data granule, displacement,     first address + count
                                       size, flags)
                                upper levels (the pyramid, TDA):
                                first key of each block below → its address
                                data granules: the records (segments ≤ X'800' bytes)
```

## 1. Units and links

- **A granule is 512 words** (`BUFSIZ` = 2048 bytes, `UTS.txt:484`), the unit of allocation.
  Disc addresses are 24 bits: the device (DCT index or volume) in the high part and a relative
  sector (`LSECTA`, `LDCTX`).
- **Index blocks** (directories and keyed master indexes) are a **whole granule** in C00. `UTS.txt`
  defines `XBUFSIZ` as 1024 bytes ("HALF GRANULE FOR INDEX BLOCKS"), but `WRTF`, `RDF`, `CLS` and
  `OPNF` all redefine it as X'800' (`WRTF.txt:22`). FIX1 still accepts the older half-granule
  blocks, told apart by bit X'4000' of the control word (`FIT08`, `:1786`).
- **Every chained block starts with three words** (`UTS.txt:485`–`:489`):

  | Word | Name | Contents |
  |---|---|---|
  | 0 | `BLINK` | Disc address of the previous block (0 for the first) |
  | 1 | `FLINK` | Disc address of the next block (0 for the last) |
  | 2 | `NAVX` | The control word (below) |

  In a **consecutive** data granule, the control word's right half is NAV, the next free word
  (3–512), and the left half is 0. In an **index** block, the left half is NAV as a byte
  displacement (at least `MIDIS` = 12, at most X'800'). The right half has:
  - X'8000', "FIT PRESENT": this is the file's first block, with the FIT at its end;
  - X'4000', a full granule;
  - the level number in X'1C00';
  - X'100', "added since the upper levels were built" (§5);
  - `SCR`, the size of a key slot, in X'FF'.

  (`VALBUF`, `FIX1.txt:2103`; `COMPLEN`, `WRTF.txt:956`.)
- **Directory blocks** also keep the dual copy's links and their own address in their last words:
  `DDA` (X'1FD'), `DBLINK` (X'1FE') and `DFLINK` (X'1FF') (`FIX1.txt:47`–`:49`).

## 2. Directories

Both directories use the index format: fixed-size entries, in key order, in a chain of blocks,
searched like a keyed file's level 0 (§5). Each is written twice. The **dual copy** has its own
chain (`DFDA` in the CFU, `DBLINK`/`DFLINK` in the blocks), and `WRTF` keeps the two in step
(`INST2E1`).

| Directory | Found from | Key (`SCR`) | Entry (`KEYSIZE`) |
|---|---|---|---|
| Account | `ACNCFU`'s `FDA` (public); `DPADFDA` = X'00010002' on a private pack (`UTS.txt:493`) | the account, TEXTC of 8 characters (9) | 18 bytes: key, the file directory's main address (3 bytes), its dual address (3 bytes), flags, 2 more bytes |
| File (one per account) | the account entry | the file name, TEXTC up to 31 characters (32) | 41 bytes: key, the FIT's disc address (4 bytes), 2 bytes, flags, 2 more bytes |

`ADINIT`/`FDINIT` (`FIX1.txt:6250`) give the sizes. `FNDKEY` (`:2194`) says where the addresses and
the flags byte are. Flags may only use the bits X'07' (`ERR#26`). The other bytes aren't
identified. Before C00, account entries had the file directory's format (`VERS`).

An **open** (`OPNF.txt`) first scans the in-core CFUs for the file already being open (`:505`,
`:618`). If it isn't, it searches the account directory, then the file directory, checks the
password and access accounts (`:571`), reads the FIT, and copies its disc addresses into a new
CFU (`:814`–`:913`).

## 3. The FIT

The **file information table** is in the file's first granule, sharing it with data or index
entries:

| Organization | FIT at word |
|---|---|
| Consecutive | 4 (after the 3-word header) |
| Keyed (full-granule index, C00) | X'1B0' (`NWFITST` = X'200' − `FITSIZE` 80, `WRTF.txt:46`) |
| Keyed, older half-granule index | X'B0' |
| Random | X'1B0' of its own granule (`SREC`) |

(`FITCHK`, `FIX1.txt:1779`–`:1789`.) It starts with the file name as TEXTC, compared with the
directory's, then a list of **VLPs**, variable-length parameter entries. Each has a control word
with a code in byte 0, the words used in X'FF00', the words reserved in X'FF', and a last-entry
flag. The ones FIX1 requires are:

| Code | Holds |
|---|---|
| X'09' | Word 0: the organization (byte 0: 0 or 1 consecutive, 2 keyed, 3 random) and `KEYM`, the maximum key length, so `SCR` = `KEYM`+1. Word 2: the number of synonymous files. At least 3 words |
| X'0C' | The file's disc addresses, as in the CFU (at least 7 words): `FDA` (first), `GAVAL` (a granule available in the cylinder), `TDA` (top of the pyramid, keyed only), `SREC` (the granule available for records), `LDA` (last). For a random file, word 0 is the data's first address and word 1 its granule count |
| X'0D' | Must exist (at least 1 word) |

The codes match the OPEN parameters that set them. X'09' and X'0C' are the "file dependent" and
disc-address parameters. Only these three are checked; the others weren't read.

## 4. Consecutive files

A chain of data granules, the first one holding the FIT. Records start at word 3, each segment
behind a **control word**. FIX1 reads the control word with `INT`, as flags in bits 0–3, the
word index of the previous control word, and a byte count (`CHKCON`, `:1944`). There are three
kinds:

| Segment | Control word | Next control word |
|---|---|---|
| Blocked | byte count, back pointer, flags (first appearance of the record) | (count + 7)/4 words on |
| Unblocked (a record of a granule or more) | flag CC1, and the disc address of the granule that holds it | the next word |
| Backspace control | all flags clear | the next word |

So a consecutive file can be read backwards (the back pointers and backspace words). The NAV in
word 2 says where the granule's data ends.

## 5. Keyed files

### Structure

**The master index (level 0)** is a chain of index blocks starting at the file's first granule
(`FDA`), whose tail is the FIT. Entries are fixed size, `KEYSIZE` = `SCR`+13 bytes, and kept in
key order:

| Bytes | Contents |
|---|---|
| 0 | Key length (TEXTC count); 0 = a deleted entry; X'80' = a continuation (not the record's first segment) |
| 1 … `SCR`−1 | The key, padded (only the key's own length is moved, "TO PREVENT PASSWORD FROM ENDING UP IN MI GRANULE", `WRTF.txt:1706`) |
| `SCR`, +2 | The segment's byte displacement in its data granule, and its original size (halfwords; the segment must lie inside the granule, X'800') |
| `SCR`+4 … +7 | Disc address of the data granule |
| `SCR`+8, +9 | The segment's current size (at most the original) |
| `SCR`+10 (`IMT`−3) | Flags: X'04' **FAK**, first appearance of the key (the record's first segment); X'01', more segments follow (`IMG2`, `WRTF.txt:1739`); X'02', end of file (`EOFMITST`, `RDF.txt:1539`) |
| `SCR`+11, +12 | Not identified |

(`FNDMI` and `FNDDA`, `FIX1.txt:2334`, `:2240`.) A record that doesn't fit one granule's free
space is several **segments**, each with its own entry under the same key. The first has FAK, and
the rest are continuations. Data granules hold the records' bytes. `SREC` in the CFU is the
granule where new records go.

**The pyramid** (the upper levels) is optional. `TDA` points at its top. An upper-level entry is
`SCR`+4 bytes: a key, the **first** key of a block on the level below, and that block's 4-byte disc
address. The level number is in each block's control word, and the top level is at most three
blocks, chained across.

### Finding a key (`SETUPUB`, `RDF.txt:1575`)

1. Try the index block already in the DCB's index buffer (`BUFF2`): compare with its last active
   key, then its first (`SETUPHT`, `SETUPLT`). A key inside that range is searched for there.
2. Otherwise, if there's a pyramid, start at the top (`MLCHK`), walking the top level with `BLINK`
   or `FLINK` until the key is inside a block's range. In each upper block, do a **binary search**
   (at most 9 halvings, `MLSET03A`), take the entry's disc address, and read the block below.
   `KEYVERIF` checks that the block reached starts with the key the entry promised. A level with
   the wrong number, a bad link or a failed check logs error 75-07 and falls back to level 0 from
   `FDA`.
3. **Level 0** (`LOCCODEUB`, `RDF.txt:1252`): a search through the block and on along `FLINK`. Too many level-0
   reads (more than `LRDL0`) marks the index **congested**, which sets slides to X'FF' (below) and
   TYC X'B'.
4. **The record**: the entry's data address, displacement and size give the segment. The data
   granule is read into the blocking buffer (`BUFF1`) and moved to the user, with the
   continuations following.

A key that isn't there leaves the position where it would go, for a write. At the end of the
file, a read gets TYC 7 (end of file).

### Inserting a key (`INST`, `WRTF.txt:600`)

1. Find the insertion point after any deleted entries, reading on along `FLINK` if needed.
2. If the block has room, slide the following entries down by one entry and put the new one in.
   **Room** (`COMPLEN`, `WRTF.txt:956`) means the new NAV stays within X'7FF', or X'6BF' in the
   FIT's block, less the DCB's spare bytes (102 by default). So every insert leaves that much free
   in a block.
3. **If it's full**, either move the block's **last** entry to the front of the next block (read
   into `BUFF3`, with a link check), or, if that one is full too or there is none, **chain in a
   new block** after this one (`INSTN`: a new granule from `GETIGRAN`, with `BLINK`/`FLINK`, and
   the dual links for a directory).
4. **The pyramid restriction** (`MULCHK`): while upper levels exist, a block that an upper-level
   entry points at must keep its first key. So an insert at the front of such a block goes into
   the previous block or a new one instead. Blocks chained in since the build carry X'100' and are
   free of this.
5. Each new block counts a **slide** in the CFU (`WRTF.txt:1508`). Past the DCB's `LSLIDES`, the
   count is pinned at X'FF' "SO THAT HIGHER LEVEL REBUILT AT CLOSE".

### Building the pyramid (`MUL.txt`, from `CLSFILD`, `CLS.txt:1424`)

At close, if the keyed file was written and its slides passed `LSLIDES`, the MULOV overlay (entry
0) rebuilds the upper levels:

1. Granules of the old pyramid are reused ("obsolete structure", the O bit).
2. **Level 1**: for each level-0 block, its first key goes into a new level-1 block, with X'80'
   added to the count if it's a continuation, followed by the block's disc address (`MOVEAKEY`).
   Deleted first keys are slid out of the level-0 block first. Level-0 blocks marked X'100' are
   cleared and rewritten.
3. **More levels**: while the level just built has more than 3 blocks, build the next one from it.
   With exactly 3, the **middle** block becomes `TDA`; otherwise `TDA` is the level's first block.
4. Without granules, the pyramid is dropped (`TDA` = 0, TYC X'C', "partial higher level index
   built").

The DCB's pyramid parameters are in word 19 (`WRDL0`): `LSLIDES` and `LRDL0`, and a byte of spare
space. Their defaults are "254 SLIDES, 2 CONSEC, 102 BYTES SPARE" (`DFRDL0`, `OPNF.txt:1841`), and
OPEN's X'09' parameter can set them (`OPN.txt:312`).

## 6. Random files

The FIT has a granule of its own (`SREC` points at it). The data is contiguous, a first address
and a count (the X'0C' VLP), allocated by cylinder where possible (`ALLOCATE RANDOM FILE`,
`GRAN.txt:249`). A random read or write names a granule number (the block number, the FPT's
parameter 8, [`rdwr.md`](rdwr.md) §2).

## 7. In core: the CFU and the DCB

**The CFU** ("current file usage", `UTS.txt:448`) is one per open file, shared by the DCBs that
have it open:

| Word | Contents |
|---|---|
| 0 (`NOU`) | Number of users; bytes: function (`BAFUNM`), slides (`BASLIDES`, byte 3); flags (bit 15 private) |
| 1 (`FDA`) | First disc address |
| 2 (`CDAM`) | Current master-index block |
| 3 (`GAVAL`) | Granule available in the cylinder |
| 4 (`SCFU`) | Secondary CFU (open both in and out) |
| 5 (`TDA`) | Top of the pyramid (consecutive: the record count) |
| 6 (`SREC`) | Granule for records |
| 7 (`LDA`/`FSP`) | Last disc address / free sector pool |
| 9, 11 | The account and the file name |

The low-core CFUs `ACNCFU` and `FILCFU` are the directories', and so is `BGRCFU`, the background
granule pool's. **The DCB** keeps the CFU address (word 1), the key buffer (`KBUF`) and key address
(`KAD`), and the buffer indexes (`BUFX`). Those are the blocking buffer window `BUFF1` (X'9400')
and the index buffer `BUFF2` (X'9600'), mapped per CAL ([`cal.md`](cal.md) §3).

## 8. Granules (outline)

`GRAN`/`GRANSUB` hand out and take back granules from per-device stacks. When a stack runs out
they call "the CAT", the **ALLOCAT** ghost, which refills them from the **allocation tables
(HGP)**. Those are a bit map per volume, by granule or by cylinder (`ATCYLBIT`; `VTOC` on private
packs, `UTS.txt:497`–`:510`). `ALLYCAT.txt` is ALLOCAT's resident part. The first one started at
boot is in [`keyin.md`](keyin.md) §4. FIX1's "HGP reconstruction" (`HGPRFLAG`) rebuilds the tables
by walking every file (§§2–6) and allocating what it finds (`ALLOCG`).

## What a first translation would need

| Piece | Source | Notes |
|---|---|---|
| A disc of granules | — | Python lists of 512 words, disc addresses as numbers |
| Index blocks and entries | §1, §5 | Byte-exact, so FIX1's checks could be translated against them |
| Level-0 search and insert | `LOCCODEUB`, `INST`, `COMPLEN`, `INSTN` | With block splits and `FLINK` |
| Pyramid search | `SETUPUB`, `MLCHK`, `MLSET03A` | The binary search on upper levels |
| Pyramid build | `MUL.txt` | At close, from the slides count |
| Directories | §2 | Account and file directory in the index format; dual copies optional |
| FIT and CFU | §3, §7 | The X'09' and X'0C' VLPs |
| Granule allocation | `GRAN`, ALLOCAT | A free list per disc at first |
| CALs | OPEN, CLOSE, READ/WRITE by key | Through `cal.py`; `ISEQUB`/`IOSFILE` dispatch ([`rdwr.md`](rdwr.md) §2) |

The Python translation of keyed files is `python/uts/files.py`. It covers the byte-exact blocks
and entries, the room check, insertion with block overflow and the pyramid restriction, data
placement (packed, split and unblocked segments), the search with the pyramid and its fallback,
the level-0 read count, the pyramid build at close, and FIX1's checks. It also covers:
- **the directories**, in the entry formats of §2, with `COMPLEN`'s directory room rule;
- **OPEN and CLOSE** (`FileSystem`): the CFU scan, the directory search, the FIT read, and a new
  file entered in its directory at close;
- **the CALs** through `python/uts/cal.py`: `M:OPEN` (overlay OPEN entry 0), `M:CLOSE` (CLOSE
  entry 2), `M:DELREC` (CLOSE entry 4), and `M:READ`/`M:WRITE` on a file DCB (`ISEQUB`,
  `IOSFILE`). This includes the keyed and next-record reads, the NEWKEY/ONEWKEY rules and the
  default OPEN.

Keys and names are EBCDIC on the disc (Python's `cp037`), so they sort as on the real system.
Digits come after letters, and specials such as `:` before them.

## Open questions

- **Unidentified entry bytes**: two in each directory entry, and the last two of a master-index
  entry.
- **`INT` again**: the consecutive control-word fields are as FIX1 reads them with `INT`
  ([`recovery.md`](recovery.md) §6).
- **Half-granule index blocks** (resolved for C00): the modules that build and read them assemble
  with full granules. Half granules are an older format FIX1 still accepts.
- **The spare bytes** (resolved): `COMPLEN` keeps them free in every index block on insert. How
  MUL's own room check (`COMP`) treats them wasn't traced. "2 CONSEC" (`LRDL0`) is the limit on
  level-0 reads in one search.
- **The account entry's flags byte**: FIX1 reads it right after the two 3-byte addresses (byte
  15, `FNDDA`), while RDF's `FNDKY` reads the account directory's flags at `IMT`−1 (byte 17).
  The translation follows RDF, the code that runs on every OPEN.
- **Write and read codes**:
  - X'16' for NEWKEY on an existing key, X'13' for writing a missing key without NEWKEY or
    ONEWKEY, X'17' for no key, X'15' for an operation error (`RDF.txt:376`–`:384`,
    `WRTF.txt:201`–`:270`);
  - X'43' for a key not found (`KEYER3`), X'06' for end of file.

  How OPEN reports its own errors (`OPNF`) wasn't read in detail; X'03' ("no such file", as FIX1
  handles it) is used.
- **Who sets the end-of-file flag** (X'02') on an entry wasn't found, only where it's tested and
  reset.
- **Not read:**
  - OPEN in detail (passwords, synonyms, expiration, `OPNF` `:571`–`:1363`);
  - CLOSE's FIT update;
  - the consecutive and random read/write code;
  - deletion (`DLT`, `PURGE`);
  - the dual-copy recovery reads;
  - ALLOCAT and the HGP formats;
  - FIX1's repairs;
  - `FRES` (file restore).
