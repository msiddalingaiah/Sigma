# The file system: directories, files and keyed files

How files are laid out on the disc: the account and file directories, the file information table
(FIT), and the three organizations. The main subjects are **keyed files** (their master index, the
records it points to, how a key is found, how one is inserted, and the upper-level "pyramid"
rebuilt at close) and **consecutive files** (their segments, and how they are written, read and
cut short). The modules are large (about 25k lines), and this document describes the
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

  In a **consecutive** data granule, the control word's right half is NAV, the word for the next
  segment control word, and the left half holds only the "unblocked segments" and "full" flags
  (§4). In an **index** block, the left half is NAV as a byte
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
| Consecutive | 4, as the data of a dummy segment whose control word is word 3 (§4) |
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

A chain of data granules holding records one after another. It is written at the end and read
forward or backward, and a record can be any length. Write is `SEQ0` in `WRTF.txt` (`:273`–`:505`).
Read is `SEQ0` in `RDF.txt` (`:3136`–`:3268`), with the positioning routines `SEQPOS` (`:3017`),
`SEQFRD` (forward one segment, `:2896`), `SEQBCK` (backward, `:2958`) and `SEQREAD` (read a granule,
`:2845`). Deleting records and cutting the file short are in `DLT.txt` (`:169`, `:477`–`:640`).
FIX1 checks every granule with `CHKCON` (`FIX1.txt:1944`). The DCB's `ORG` field tells the read
and write entries which code to use: X'20' is keyed, X'10' random, and neither consecutive
(`RDF.txt:2419`–`:2422`, `WRTF.txt:194`–`:196`).

### Granules

Every granule has the 3-word header of §1. Word 2, the **granule control word**, has:

| Bits | Contents |
|---|---|
| X'80000000' | The granule has unblocked segments (set by `WRTF.txt:425`) |
| X'40000000' | Full (`:495`–`:496`) |
| X'3FFF0000' | Must be 0. That is how OPEN and `SEQPOS` tell a consecutive granule from an index block (`OPNF.txt:1780`, `RDF.txt:3079`), and `SEQREAD` also wants NAV from 3 to 512 (`MASKS+30`, `:2884`–`:2892`) |
| X'FFFF' | **NAV**: the word where the next segment control word goes |

The word at NAV is never empty: it already holds the **back pointer** for the next control word,
the index of the last control word written (`SEQ3C`, `WRTF.txt:498`–`:501`, "FOR BACKUP"). When a
segment ends at the end of the granule, NAV stays on that segment's control word and the full
flag is set instead (`SEQ3E`, `:493`–`:497`).

A **new granule** (`SEQ1C`, `:292`–`:304`) gets BLINK = the previous granule and FLINK = 0, word 3 =
0, and NAV = 3. The previous granule's FLINK is set to it before that granule is written
(`SEQ1F2`, `:325`–`:327`). The CFU's `LDA` follows the last granule (`:343`).

**The first granule holds the FIT.** A new consecutive file gets its first granule from `ENTERO2`
(`WRTF.txt:521`, "PHONY FIT") at create, before any record is written. It comes through `LINE308`
with a zero record size, so FDA = LDA = that granule and TDA, the record count, is 0
(`:285`–`:291`). Then:

| Word | Contents |
|---|---|
| 3 | X'01400000' (`=FX'80B13'`, `:298`): a segment control word with a count of 320 bytes, the FIT's 80 words, and no flags. The comment says it "LOOKS LIKE DEL'D REC", so reading skips it |
| 4–83 | The FIT. CLOSE builds it there (`CLS.txt:2273`, "ASSUME CONSEC"), and OPEN reads it there (`OPNF.txt:1746`) |
| 84 | 3, the back pointer, and NAV = 84 (`FITSIZE`+4, `:300`–`:304`) |

### Segment control words

A record is one or more **segments**, each behind a control word. Read with `INT` (the
assumption of [`recovery.md`](recovery.md) §6), the flags are bits 0–3 (the condition code), and
the rest splits into bits 4–15 and 16–31:

| Kind | Bits 0–3 | Bits 4–15 | Bits 16–31 | Next control word |
|---|---|---|---|---|
| **Blocked**: the data follows in this granule | flags | byte count | back pointer | 1 + (count + 3)/4 words on |
| **Unblocked**: the data is a granule of its own | X'8' + flags | bits 4–7: length − 2033 (0–15); bits 8–31: the data granule's disc address | (address) | the next word |
| **Backspace control** | 0 | 0 | back pointer | the next word |

The flags are:
- **X'8'**, unblocked (`Y8`);
- **X'4'**, the first segment of a record. FIX1 calls it FAK, "first appearance of key"
  (`FIX1.txt:1970`), and the writer sets it on a record's first segment only (`WRTF.txt:368`–`:374`);
- **X'2'**, continued: more segments of this record follow (`Y2`, `:455`; `Y28`, `:408`);
- **X'1'**, special backspace: a backspace control word comes just before this unblocked one
  (`SEQ2G`, `:395`).

A record of **2033 bytes or more** (`BUFSIZ`−15) is written unblocked, and anything shorter is
blocked. The length code in bits 4–7 is the length less 2033 (`SEQ2C`, `:413`–`:416`; read back
by `RDF.txt:3177`–`:3185`), so an unblocked segment is 2033 to 2048 bytes. A longer record has
unblocked segments of 2048 bytes (code 15, with C set) until less than a granule is left. The rest
is then written as an unblocked or a blocked segment, by its own length.

An unblocked control word can't hold a back pointer, because the disc address takes its place.
So reading backward steps over it by one word (`SEQBCK3`, `RDF.txt:2995`–`:2998`), and it must
follow another unblocked control word or a backspace control word. When the segment before it was
blocked, the writer leaves the back-pointer word at NAV as a **backspace control word**. It puts
the unblocked one in the next word with the X'1' flag (`SEQ2H`, `WRTF.txt:383`–`:396`). The first
segment in a granule needs none. If the backspace word is the granule's last, the unblocked control
word goes to a new granule (`:389`–`:394`, kept on the stack until `:379`–`:381`).

### Position and record count

| Where | What |
|---|---|
| CFU `TDA` | The number of records (`WRTF.txt:291`, `:373`). It is saved in the FIT's X'0C' VLP like the other CFU addresses |
| DCB `DCBCDAM` | The current granule |
| DCB `CMD`'s halfword `HACMD` | The current word in it; 0 is the beginning of the file (`SEQPA`, `RDF.txt:3050`–`:3057`) |
| DCB word 14 (`W14`) | The current record number |
| DCB word 19 (`W19`) | Records still to skip (positioning). While writing, the first-segment flag |

`SEQPOS` (`RDF.txt:3017`) starts most operations. It reads the current granule if it isn't in the
buffer and checks its links and control word, rereading up to 4 times (`SEQPOS1`–`SEQPOS8`). Then it
moves forward or backward segment by segment to a segment with the X'4' flag, the start of a record
(`SEQPOS3`, `:3118`–`:3122`). Segments without the flag are skipped: the FIT's, a record's later
segments, and deleted records.

### Writing (`SEQ0`, `WRTF.txt:273`)

1. **Position** with `SEQPOS`. If the file has no granules yet, start with a first granule, FIT
   room and all (`:279`–`:304`).
2. **Not at the end** (`W14` ≠ `TDA`): first **delete forward** from here (`DLTSEG` entry 3, below),
   then position again (`SEQ01`, `:346`–`:353`). Writing in the middle of a file cuts it short
   there.
3. **A record of size 0** writes nothing (`SEQ1B1`, `:357`–`:360`).
4. **The first segment** gets the X'4' flag, and `TDA` and `W14` go up by one (`SEQ2A`,
   `:367`–`:374`).
5. **Room**: with NAV below 511 there is room. With NAV at 511, only an unblocked control word fits
   (`SEQ1G`, `:362`–`:366`). When the granule is full, a new one is chained on (`SEQ1F`).
6. **A blocked segment** (`SEQ3A`, `:446`–`:505`): the data goes in from the word after the control
   word. If it runs past the granule's end, the segment is cut there with the C flag, and the rest
   continues in a new granule. The count goes into bits 4–15 and is added to the back pointer
   already in the word (`AWM,4 *14`). NAV moves past the data, and the new NAV word gets the back
   pointer.
7. **An unblocked segment** (`SEQ2F`, `:398`–`:428`): a data granule of its own (`GETDGRAN`), its
   disc address in the control word, and the data written straight to it from the user's buffer
   (`IMAGE2`).
8. **Repeat** while bytes are left (`SEQ2E`, `:430`–`:439`).

### Reading (`SEQ0`, `RDF.txt:3136`)

1. **Position** with `SEQPOS` (EOP = read).
2. **End of file**: reading forward with `W14` ≥ `TDA` gives TYC 7, code X'06' (`SEQ02`, `:3162`–`:3166`;
   `EOFMITST1`, `:1571`). Reading backward at the start gives TYC 4, beginning of file, code X'04'
   (`SEQ00`, `:3143`–`:3147`). An empty file gives the same.
3. **Each segment** (`SEQ1`, `:3172`): a blocked one is copied from the granule buffer, as much as
   the user's buffer still takes (`SEQ3`, `:3198`–`:3231`). An unblocked one is read from its granule
   straight into the user's buffer (`PVREADTP`, `:3177`–`:3189`). A blocked segment of count 0 is
   passed over (`:3199`–`:3201`). While the C flag is set, the next segment follows (`SEQ5`).
4. **A record longer than the buffer**: the buffer is filled, and the read ends with TYC 2,
   lost data, code X'07' (`SEQ6`, `:3245`). The rest of the record is skipped.
5. **After the record**, `W14` goes up by one and the position is saved in the DCB (`SEQR`, `:3264`).
   Reading backward instead returns to the record's start (`:3256`–`:3262`), so the next backward
   read gets the record before it.

### Deleting

- **A record** (`M:DELREC`, `DLT.txt:169`–`:190`): position on the record just read (backing up one,
  unless reading backward), clear its X'4' flag (`AND` with `NB31TO0+31` = X'BFFFFFFF',
  `TABLES.txt:178`), and take one off `TDA`. The data stays in place. Reads skip it from then on.
- **Delete forward** (`DLTSEG` entry 3, `SEQ2`, `DLT.txt:479`): from the current position, release
  every later granule, including the data granules of unblocked segments, found by walking the
  control words (`SEQ5`–`SEQ7`). Then cut the current granule at the position (`SEQ8A`–`SEQ83`):
  - a blocked control word there loses its left half (flags and count), leaving just its back
    pointer;
  - an unblocked one becomes a pointer to the word before it;
  - in the granule control word, NAV becomes the cut, and the full flag (bits 1–3) is cleared under
    the mask X'8FFF0000';
  - FLINK becomes 0.

  `TDA` becomes the current record number, and `LDA` the current granule (`SEQ92`, `:626`–`:628`).
- **The whole file** (`SEQ3`, `:488`): the same from the beginning of the file, and FDA = LDA = 0,
  TDA = 0.

Granules go back through `RELRBGD`. The cylinder pool kept in `GAVAL` while releasing (`SEQ41`–`SEQ43`)
belongs to granule allocation (§8).

### FIX1's check (`CHKCON`, `FIX1.txt:1944`)

FIX1 walks the control words from word 3, keeping the previous control word's index (starting at 0)
and the previous segment's kind (starting as "backspace control"):

| Control word | Rule | Error |
|---|---|---|
| Blocked, or flags 0 with a count ("deleted blocked segment") | back pointer = the previous control word | ERR#41 |
| Backspace control (flags 0, count 0) | previous segment blocked, back pointer = the previous control word | ERR#44 |
| Unblocked | previous segment not blocked; the X'1' flag set exactly when the previous segment was backspace control; a valid disc address | ERR#42, ERR#43 |
| The walk's end | it must land on NAV. In a full granule it may go past NAV only if NAV is the last control word | ERR#40 |

It counts the records in the granule by the X'4' flags.

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
   `FDA`. On the step down to level 0, an entry marked as a **continuation key** (X'80' in its
   count, set by `MOVEAKEY` when a block starts with a record's later segments) that isn't first in
   its block makes the search **back up one entry** (`MLSET00`, `RDF.txt:1794`–`:1803`). The record's
   first entry, the one a read needs, is at the end of the block before.
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

A random file is a contiguous run of granules, read and written by granule number. Its FIT has a
granule of its own, and the CFU's `TDA` holds the number of granules (`CDAM SET TDA`,
`CLS.txt:1731`–`:1732`).

- **Create** (`OPNF.txt:1043`, `GRAND.txt:55`): the size, in granules, comes from the DCB's
  `RSTORE` (the OPEN parameter). Zero is allowed only for a scratch file. The account's disc limit
  is checked (`J:JIT`'s `TMDCRM`, `:85`–`:86`, error X'57'). `GRANDPUB` (`:102`) then:
  1. takes one granule for the FIT, from the pack stack, else the RAD stack, else a cylinder. It
     goes into the CFU's `SREC`. A scratch file has none;
  2. asks ALLOCAT for the run with `GNBG` (`HG52`, `:117`), device type by device type. The first
     address becomes the CFU's `FDA`, and the count its size (`SETOPND`, `OPNF.txt:1053`–`:1058`).
- **Read and write** (`RWRAND`, `WRTF.txt:1928`). The key buffer (`KBUF`) holds a word, the
  relative granule number, given as the FPT's key ([`rdwr.md`](rdwr.md) §2). A request:
  1. starts at that granule. A number past the end of the file is code X'42', with nothing moved
     (`ERR01`, `:2081`);
  2. moves `RWS` bytes, but no more than is left in the file (`:1947`–`:1957`), straight between the
     disc and the user's buffer, in transfers of at most 32 sectors that don't cross a track except
     at the end of a cylinder (`RWR22A`–`RWR25`, `:2011`–`:2045`);
  3. then adds the granules moved, rounded up, to the key word, so the next request continues
     there (`RWRDUN`, `:2062`). A request of size 0 adds 1 (`:1939`–`:1941`).

  The actual record size (`ARS`) is the bytes moved. Fewer than asked for (the end of the file)
  ends with the code in `E5744` (`:2075`, `GEN,7,25 X'44',X'57'`).
- **Release** (`RELRAND`, `CLS.txt:1729`): with REL at close, the run goes back with `RNBG`, a
  message to ALLOCAT. A file allocated by cylinder goes back cylinder by cylinder (`RRR0`).

Random files can't have synonyms (`OPNF.txt:1033`–`:1036`). Whether the FIT granule (`SREC`) is
released with the run wasn't found.

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

## 8. Granule allocation

Granules are handed out at three levels:

```
file code (GETDGRAN, GETIGRAN, RELRBG) ─► GRAN: GBG / RBG          resident, fast
                                            │  a stack of free disc addresses per device type
                                            │  (HGPSTK), filled and emptied by ...
                                            ▼
                                       ALLOCAT (ALLYCAT.txt)        a ghost, started on demand
                                            │  ... the allocation tables:
                                            ▼
                                       the HGP bit maps (GRANSUB.txt)   one per device, 1 = free
```

### The bit maps (HGP, `GRANSUB.txt`)

Each disc device has an **HGP**: a 7-word header (layout in `GRANSUB.txt:222`–`:242`) and bit maps
in which a set bit is a free granule. They are chained from `HGP` (word 0).

| Word | Contents |
|---|---|
| 0 | The next HGP |
| 1 | DCT index, flags (X'8000': allocated by cylinder; X'4000': a private pack), and the granules per cylinder (`NGC`) |
| 2 | The next HGP of the same type, in the circular chains `HGPTYPE` (RAD, pack, symbiont, cylinder, mixed) |
| 3 | Where the last single-bit get stopped (the bit and word), so the next search continues there |
| 4 | The lengths in words of the two maps, PER and PFA |
| 5, 6 | For PER and for PFA: the map's displacement, and the area's first sector. Bit 0 of either word set means that map is empty |

A device has two areas, PER and PFA. The symbiont routines use PER and may take PFA granules
when it runs out (`GRANSUB.txt:372`–`:378`). Files come from PFA. The source doesn't spell out
either name.

- **One granule** (`CMNGG`, `:87`; `GETBIT`, `:258`): continue from where the last search stopped
  (word 3), find the next set bit, clear it, and remember the place (`GBIT5`, `:296`). The disc
  address is the area's first sector plus two sectors a bit (`DISKADDR`, `:314`). An empty map gets
  its empty flag (`SETEMPTY`, `:347`), and the search goes on to the next device of the type, then to
  the next type (`NXTTYPE`).
- **N contiguous granules** (`CMNGNG`, `:105`), for random files: search from the end of the map
  backward for a run of N set bits, and clear them. For cylinders the run may continue on the
  previous device.
- **Release** (`CMNRG`, `:362`; `CMNRNG` for N): find the bit for the address, after checking that
  it really is a granule (or cylinder) boundary in the right area. Set it and clear the map's empty
  flag. A bit that is **already set** is a **dual allocation**: an error record is logged
  (`LOGDUAL`, `:465`), and the release goes on.

### The stacks (`HGPSTK.txt`, `GRAN.txt`)

`HGPSTK` holds four circular stacks of free disc addresses: RAD, pack, symbiont (PER) and cylinder.
Each has 128 slots (the cylinder stack has 8) and these fields, as half-words:

| Field | RAD, pack, PER | Cylinders | Meaning |
|---|---|---|---|
| `TOP` | | | The next slot to push into; a pop takes the slot below it |
| `BOTTOM` | | | The lowest slot in use. Empty when `TOP` = `BOTTOM` |
| `TEMPBOT` | | | Where ALLOCAT's fill reaches, or where its emptying starts |
| `WORDCNT`, `ADJSTCNT` | | | The count, and ALLOCAT's pending change to it |
| `LOLEVEL`, `HILEVEL` | 40, 80 | 3, 5 | ALLOCAT fills up to `HILEVEL` from at or below `LOLEVEL`, and empties down to `LOLEVEL` from above `HILEVEL` |
| `LOTHRSH`, `HITHRSH` | 16, 100 | 2, 6 | A user's get or release that leaves the count at or past one of these calls ALLOCAT |
| `BUFLAGS` | | | X'8000' the HGP is empty, X'4000' just emptied, X'2000' just filled, X'0001' ALLOCAT is working on it |

The file code calls **`GBG`** and **`RBG`** (`GRAN.txt:95`–`:117`). The device type picks the stack: RAD
X'07' is 0, pack X'0B' is 1.

- **Get** (`GETGRAN`, `:193`): pop the slot below `TOP`. With the stack empty, a monitor call gets 0
  (`RELX`), and so does a user if the HGP is empty too. Any other user **waits**: it is blocked with
  `E:QFAC` after ALLOCAT is started (`REG4CAT`, `REGUSER`, `:202`, `:301`), and tries again when it
  runs.
- **Release** (`:144`–`:186`): push the address at `TOP` (`ROOM`). With no room (`TOP` = `TEMPBOT`),
  the address goes to ALLOCAT as a message instead (`NORELROM`, code X'10001').
- **Thresholds** (`CHKTHRSH`, `:230`): after either, a count at or above `HITHRSH`, or at or below
  `LOTHRSH` while the HGP isn't empty, **starts ALLOCAT** (`THRESH`: `T:GJOBSTRT 'ALLOCAT'`, `:337`).

Requests that ALLOCAT has to answer go through `COMBUF`, eight two-word message buffers on a free
chain (`CBFHD`) and ALLOCAT's chain (`CBAHD`) (`QUEMSG`, `:319`):
- **`GNBG`/`GNCYL`** (`:252`): N granules or cylinders for a random file. The user waits on `E:QFAC`
  until ALLOCAT has put the answer in the buffer.
- **`RNBG`** (`:281`): release N.
- **`GSBP`** (`:292`): a pair of granules on different devices, for directories.

### ALLOCAT (`ALLYCAT.txt`)

The ghost is started at boot (keyin.md §4) and at recovery. **`ALLOINIT`** (`:77`) shrinks itself,
saves the file system's pointers, and counts the free bits of every HGP into `AGRAVAIL`/`GRAVAIL`
while building the `HGPTYPE` chains (`HGPCNT`, `:134`). Then it sleeps (`WAIT`).

Each time it runs (`ALLOCAT`, `:253`):
1. **Messages** (`ENDYET`, `:273`): each `COMBUF` message on its chain goes through `COMVEC`
   (`:620`): `GETN` (`CMNGNG`, the answer left in the buffer, `:425`), `RELN` (`:442`), `GSBP` (`:461`),
   `RELBUF` (a page of addresses), `QUIESCE` (empty every stack into the maps, `:310`), `FILLPER` (all
   of PER free again), `AVR`, and `COUNTBITS`.
2. **The stacks** (`ADJBUFS`, `:330`), each one not already flagged:
   - at or below `LOLEVEL`: **fill** to `HILEVEL` (`FILL`, `:389`). `TEMPBOT` moves down by the number
     wanted, and granules from the maps (`CMNGG`) go in below `BOTTOM`, counted in `ADJSTCNT`. The
     flag is "just filled". If the maps run out, `TEMPBOT` is where the fill stopped and the flag
     is "empty and just filled" (X'A000');
   - above `HILEVEL`: **empty** down to `LOLEVEL`. `BOTTOM` moves up by the excess, and the slots
     from `TEMPBOT` up are released into the maps (`CMNRG`), each taken off `ADJSTCNT` before its
     release ("WE LOSE ONE GRANULE INSTEAD OF TRYING TO RELEASE A RELEASED GRANULE LATER", `:364`).
     The flag is "just emptied".
3. **Done** (`NOMORE`, `:675`): start FILL first if `GRANMIN`/`GRANRESET` ask for it, then sleep (`WAIT`,
   `:686`), with `ALLOOUT` set.

**Users see the new stack only later.** While ALLOCAT works, `BOTTOM` and `WORDCNT` are unchanged,
so a user's get still finds the stack empty. When the swapper takes ALLOCAT out of memory, it
reports `E:UQFAC` (`SWAPPER.txt:612`–`:620`). `STUQFAC` (`SCHED.txt:1707`, [`scheduler.md`](scheduler.md)
§6) then sets `BOTTOM` from `TEMPBOT` (after a fill) or `TEMPBOT` from `BOTTOM` (after emptying), adds
`ADJSTCNT` to `WORDCNT`, and clears the flags. Its `T:REL1` lets the users blocked on `E:QFAC` go on.

FIX1's "HGP reconstruction" (`HGPRFLAG`) rebuilds the maps by walking every file (§§2–6) and
allocating what it finds (`ALLOCG`).

## 9. Deleting a file

A program deletes a file by **closing it with the release option**. `M:CLOSE`'s first optional
parameter is the disposition, taken with `CHKBIT1` (`IORT.txt:1532`, the first presence bit):
1 is REL and 2 is SAVE (`CLS.txt:1452`, `:1507`, `:1997`). `CLSFIL` (`CLS.txt:1443`) then does the
following.

1. **No release** if another user has the file open (`:1505`–`:1506`), if it is shared
   (`:1509`–`:1511`), or if it is random and shared (`CL1`, `:1553`–`:1556`). The close is then an
   ordinary one.
2. **The CFU's release bit** (`Y1`) is set (`CLSFIL5`, `:1519`–`:1521`).
3. **Opened OUT or OUTIN**: the file isn't in its directory yet, because a new file is entered at
   close (`CLSFIL4`, `:1996`). So only its granules go (`:1523`–`:1525`, to `CLSFIL2`).
4. **Opened IN**: only a user with privilege X'C0' or more may delete a file that the DCB marks as
   someone else's (`USR` X'4000'). For anyone else, the release is dropped (`CLSFIL2M`). Either way
   the function becomes UPDATE, "FOR RECOVERY" (`:1528`–`:1535`).
5. **Opened IN or UPDATE**: the file's directory entry is found again (`FINDFIL1`, `:1559`) and
   deleted (`DELF`, at `CL6A`, `:1613`). A file with synonyms loses every entry that has the same
   FIT address (`:1568`–`:1609`).
6. **`CLSFIL2`** (`:1626`) writes out the FIT and clears the CFU's name ("CLOBBER THE NAME SO FILE CAN
   BE OPENED DURING RELEASE", `:1664`–`:1666`). Then it releases the granules: `RELRAND` for a random
   file, `REL` in `DLT.txt` for the others (`:1667`–`:1672`).

### Removing the directory entry (`DELF`, `DLT.txt:314`; `DEL1`, `:343`)

`DELF` reads the file-directory block that holds the entry (`DELO`, from the CFU's position,
`:324`–`:331`) and goes on to `DEL1`. `DEL1` doesn't mark the entry deleted. It **slides the
entries after it up** over it, and NAV goes down by one entry (`DEL31`, `DEL3`, `:367`–`:374`). A
block left empty stays in the chain, with its first word cleared ("BLITZ 1ST ENTRY", `:378`).

Deleting a record from a keyed file (`DEL`, `:195`) uses the same `DEL1` slide, with one exception:
an entry that is first in its block stays, as a null entry with a key count of 0 (`DEL16`,
`:360`–`:366`). The code that would delete an account's file directory once it is empty (`DELFD`)
is assembled out (`DO 0`, `:272`). So deletes in the account directory, and of a whole file
directory, are ignored (`:257`–`:261`).

### Releasing the granules (`REL`, `DLT.txt:665`)

- **A consecutive file** goes to `SEQ3`, the whole-file delete of §4 (`:668`–`:674`, "NEW
  CONSECUTIVE").
- **A keyed file** goes in three steps:
  1. The upper levels go first, through `MUL` entry 1, when the CFU's O bit says there are any
     (`:690`–`:698`).
  2. Then each master-index block in turn (`RELFILUB3`, `:705`). Every entry whose segment starts
     its data granule, at displacement 0, releases that granule (`REL9`, `:762`), and then the block
     itself is released (`REL29`, `:732`). Null entries are walked too, so a deleted record's data
     granule goes with the rest.
  3. Last comes the free-sector pool (`FSP`, `:797`–`:833`).

The disc addresses are collected in a buffer (`RELBUF`: 508 a block, chained on the disc when it
fills) and released at the end (`RELFILUB5`–`RGAIBBO`, `:834`–`:885`). `RELRBG` (`:915`) gives each
granule or cylinder back to the allocation tables, and corrects the account's disc-space count
(`PRDCRM` for permanent files, `TMDCRM` for temporary ones).

## 10. OPEN's checks

When a file of the name exists, OPEN checks that the user may have it (`SECCHK`, called at `OP3`,
`OPNF.txt:566`–`:576`). A few other rules apply when it doesn't exist, or when it is replaced.

### Whose file it is (`CHKFLACN`, `OBSE.txt:190`)

The DCB must have a file name (VLP X'01', not empty, shorter than `FNEMAX`) and room for an account
(VLP X'02'). Without an account the user's own (`J:JIT`'s `ACCN`) is put in. When the account
differs from the user's, the DCB's `USR` bit, X'4000', says "**not the user's own file**"
(`CHKFLACN1`, `CHKFLACN2`, `:293`–`:304`).

### The FIT's protection

CLOSE copies these from the DCB's VLPs into a new FIT (`CLS.txt:2288`–`:2335`):

| VLP | Holds |
|---|---|
| X'03' | The password, 2 words |
| X'06' | Write accounts |
| X'05' | Read accounts |
| X'14' | Execute accounts |
| X'15' | The execute vehicle: the name of the processor through which execute access is given |

An account list has 2-word entries: an account, or the words `NONE` or `ALL` (`OBSE.txt:70`–`:71`).
A list that doesn't fit in the FIT is cut short an entry at a time (`FIL3`, `6C2`).

### The check (`SECCHK`, `OBSE.txt:310`)

1. **Privilege X'C0' or more** opens anything (`:312`–`:315`).
2. **A password** (X'03' in the FIT):
   - **present but empty:** only a user in the `:SYS` account gets in, and then as if the file
     were its own (`SEC3` clears `USR`). Anyone else is refused (`SECCHK0`, `:316`–`:327`);
   - **a password:** the DCB's X'03' must hold the same two words, or the open is refused
     (`SECCHK05`, `:328`–`:334`).
3. **The user's own file** may be opened for anything (`SECCHK1`, `:335`–`:338`).
4. **Write accounts** (X'06'): the user's account, or `ALL`, opens the file for anything, as if it
   were the user's own (`SECCHK2`, `SECCHK3`, `:342`–`:357`). `NONE`, no match, or no list goes on
   to step 5.
5. **Anything but IN is refused** at this point (`SECCHK4`, `:406`–`:409`). For IN, the read
   accounts (X'05') decide:
   - **no read accounts and no execute accounts:** the file is open to anyone (`SEC0`, `:365`–`:367`);
   - **no read accounts but execute accounts:** step 6;
   - **read accounts:** the user's account or `ALL` gives read access. `NONE` or no match goes to
     step 6.
6. **Execute accounts** (X'14'):
   - **no list, or `NONE`:** refused;
   - **the user's account or `ALL`:** access only through the vehicle (X'15'). The program
     running (`M:XX`'s name in `MXFPL`) must have the vehicle's name and come from `:SYS`
     (`SEC99`, `:378`–`:394`). The DCB then gets "special access" (X'100', `SEC97`);
   - **no vehicle in the FIT:** only a fetch (`J:STAR`) gets special access (`SEC98`, `:402`–`:404`).

A refusal is **`OPENER03`, code X'14'** (`OBSE.txt:212`–`:213`). A refused password also wipes the FIT
out of the DCB's buffer (`CLRFIB`, `:415`).

`CLM` compares an entry with `NONE` and `ALL` at once: CC3/CC4 against the first word, CC1/CC2
against the second (simh, `sigma_cpu.c:1215`–`:1222`). That matches the comments ("NO ACCESS" for
`NONE`, "GIVE ACCESS" for `ALL`, `:370`–`:373`).

### Other rules (`OPNF.txt`)

- **No such file, or no such account**: IN gets **X'03'** (`OP1`, `OPENER`, `:1303`–`:1305`, `:1353`).
  Output creates the file. In another user's account, only a user with privilege X'C0' may create
  it; anyone else gets X'14' (`OP71`, `:1319`–`:1325`).
- **Replacing a file** (output over one that exists): random against keyed or consecutive is refused
  with X'14', and so is a change of organization on a private pack. Keyed and consecutive may
  replace each other (`:545`–`:563`).
- **Names beginning X'01'**, the special files, need privilege X'C0' and IN or INOUT
  (`OPNFIL1`, `:474`–`:481`).

### Synonyms

A **synonym** is a second directory entry for a file, naming the same FIT. It is made by opening
UPDATE a file that doesn't exist, with the DCB's X'0B' VLP naming the existing file (`OP2`,
`:1280`–`:1300`). OPEN then finds that file (`FINDFIL2`), marks the DCB "new synonym" (`DESC`
X'004'), and opens its FIT. The FIT's X'09' VLP counts the synonyms in word 2 (§3). Deleting the
file removes every directory entry with the same FIT address (§9).
- **Not allowed for random files** (`:1033`–`:1036`).
- **OPEN NEXT** stepping onto a synonym builds a pseudo FIT and ends with error 08 (`:311`–`:330`).
- **Not traced:** how CLOSE enters the synonym, and how the count is kept.

### Expiration

A file's expiration date (VLP X'04') is set by CLOSE (`DOEXPDAT`, `CLS.txt:481`):
- the DCB's date, if it is within the maximum period;
- otherwise, for a new OUT file, the user's default, else 14 days;
- for an INOUT file past its date, now plus an hour.

OPEN doesn't check it, and what acts on it wasn't traced.

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
| Consecutive granules and segments | §4, `SEQ0` (`WRTF`) | Byte-exact: the FIT segment, blocked, unblocked and backspace control words, NAV and its back pointer |
| Consecutive read and position | `SEQ0`, `SEQPOS`, `SEQFRD`, `SEQBCK` (`RDF`) | Forward reads, end of file and lost data; backward reads |
| Consecutive delete | `DLT.txt` `SEQ0`, `SEQ2`–`SEQ9` | `M:DELREC`, and the delete forward that a write in mid-file does |
| Consecutive check | `CHKCON` | The FIX1 check, including the start-of-granule question (Open questions) |
| Deleting a file | `CLSFIL` with REL, `DELF`/`DEL1`, `REL` | The directory entry slid out, then the granules: `SEQ3` for consecutive files, the master index walk for keyed ones |
| Granule allocation | `GRAN`, `GRANSUB`, ALLOCAT, `HGPSTK`, `STUQFAC` | One device's bit map and the pack stack, ALLOCAT's fill and emptying, and the commit |
| Random files | `GRAND`, `RWRAND`, `RELRAND` | The run from `CMNGNG`, reads and writes by granule number, release with `RNBG` |
| OPEN's checks | `CHKFLACN`, `SECCHK`, `OP71`, CLOSE's FIT build | The protection VLPs, the opener's account and privilege |
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

**Consecutive files** are `files.ConsecutiveFile`, byte-exact as in §4:
- the first granule with the FIT segment;
- blocked, unblocked and continued segments, and backspace control words;
- NAV and its back pointer, and the full flag;
- forward reads with end of file and lost data;
- the cut at the position when a write comes before the end of the file (delete forward);
- `M:DELREC`, and `CHKCON`, translated as read.

**Granules** (§8) come from `files.Disc`, which works as GRAN does:
- `Hgp`: the bit map, with `GETBIT`'s search from where the last get stopped, `CMNGNG`'s run
  from the end, and dual allocations logged on release;
- `Stack`: the pack stack of `HGPSTK`, the same object as the scheduler's buffer 1, so the
  scheduler's `STUQFAC` commits it;
- `get` and `release` (`GBG`, `RBG`) with the room check and the thresholds that start ALLOCAT;
- `allocat` (`ADJBUFS`) and `commit` (`STUQFAC`).

ALLOCAT is a real ghost (`python/uts/ghosts.py`): a threshold wakes it with `T:GJOBSTRT`, it adjusts
the stack and reports `E:UQFAC`. There are two departures:
- **A user who would wait on `E:QFAC`** for an empty stack instead has ALLOCAT's fill and the
  commit done at once, because the file code can't be suspended in the middle of a CAL.
- **`E:UQFAC` comes from ALLOCAT** as it goes to sleep, not from the swapper (`SWAPPER.txt:619`),
  which isn't translated.

Not modeled: PER, cylinders, other devices and their type chains, `COMBUF`'s messages (answered
at once), `GSBP`'s directory pairs, and the `GRAVAIL` counts.

**Random files** (§6) are `files.RandomFile`, through `rwrand` in `cal.py` and
`cpv.open(..., org="random", size=n)`.

**Deleting** (§9) is `FileSystem.close(cfu, release=True)`, from `M:CLOSE` with REL:
- the directory entry slid out (`DEL1`), unless the file was never entered;
- then `release()`: `SEQ3` for consecutive files, `REL`'s walk for keyed ones.

Deleting a keyed record follows `DEL`: control keys at displacement 0 stay null, full granules
are released at once with the double-release guard, and other entries are slid out. The pyramid
build keeps null first keys as `MOVEAKEY` does.

**OPEN's checks** (§10) are `files.secchk`, made by `FileSystem.open` when it is given the
opener (`files.Opener`: account, privilege, running program), as `cal.py` always does:
- a refusal is X'14';
- creating a file in another account below privilege X'C0' is refused (`OP71`);
- a new file's protection VLPs go into its FIT in CLOSE's order, the lists cut to the room;
- CLOSE drops a release of another account's file opened IN below X'C0'.

Synonyms are not translated.

`FileSystem.open` tells the organizations apart by the first granule, as OPEN does, and the CALs
go to `seq_read`/`seq_write` in `cal.py` when the DCB's `ORG` is consecutive. Not translated:
backward reads, the positioning CALs (`M:PFIL`, `M:PRECORD`), read-ahead and private-pack volume
switching.

Keys and names are EBCDIC on the disc (Python's `cp037`), so they sort as on the real system.
Digits come after letters, and specials such as `:` before them.

## Open questions

- **Unidentified entry bytes**: two in each directory entry, and the last two of a master-index
  entry.
- **`INT` again** (resolved): the consecutive control-word fields are as FIX1, `SEQPOS` and the
  read code take them apart with `INT`, whose definition simh's simulator confirms
  ([`interpreter.md`](interpreter.md) §1). The writer builds the same layout with ordinary
  shifts (`SLD,12 16`, `WRTF.txt:458`).
- **`CHKCON` against the writer and the cut.** As read, FIX1 rejects three layouts that the
  monitor's own code produces. Random testing of the translation found only these:
  - **An unblocked segment at word 3.** `CHKCON` starts each granule as if a backspace control
    word came before (`LI,R5 1`, `FIX1.txt:1947`), so it wants the X'1' flag there. The writer puts
    none (`SEQ2B`, `WRTF.txt:377`–`:382`). The result is ERR#42.
  - **After a cut at an unblocked segment.** Delete forward turns its control word into a pointer
    to the word before it (`DLT.txt:582`–`:584`). The next unblocked segment then gets no X'1' flag,
    because the writer sees its predecessor next to it (ERR#42 when that predecessor is a backspace
    word). A blocked one takes that pointer as its back pointer (ERR#41, because `CONBKSPC` never
    makes a backspace word the "previous control word").
  - **Reading is unaffected.** Records read back correctly in every case, and backward reads follow
    the pointers.

  Either the reading of `CHKCON` (the X'1' flag and backspace words) or of the writer and `DLT`
  is wrong somewhere. The translation follows the source as read on both sides.
- **Positioning CALs** (`M:PFIL`, `M:PRECORD`) set `W19` and the direction. `M:PRECORD` on a
  consecutive file is translated (POS.txt `PRECORD2`, `SEQ2`–`SEQ9`, `:516`–`:546`). The new
  record number is `W14` ± N, kept between 0 and `TDA`. Records not skipped go into `CDA` and the
  ARS, and `SETBOFEOF` (`:590`) sets TYC 7 (forward) or 4 (back). CP-V leaves the skip in `W19`
  until the next read's `SEQPOS`. The model reads from the start of the file up to the record
  (`ConsecutiveFile.seek_record`). AP uses this to go back over its scratch files. `M:PFIL` isn't
  translated.
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
- **The continuation-key backup** (`MLSET00`): it is skipped if the search "already backed up",
  a flag in `SR3`'s byte 0, but every way out of the binary search seems to set that flag
  (`MLSET5M1`). The translation backs up when the search key equals the continuation key, which
  is the case it exists for. Without the backup, such a record can't be found once the pyramid is
  built; random testing found this in the earlier translation.
- **OPEN's checks**:
  - **`CLM` and the two words** (resolved): `CLM` sets CC3/CC4 from the first word and CC1/CC2
    from the second (simh, `sigma_cpu.c:1215`–`:1222`), so `NONE` and `ALL` go as the comments
    say (`OBSE.txt:370`–`:373`).
  - **A file already open.** Whether the CFU-scan path (`SCANCFU3D`, `CHKSHARE`, `OPNF.txt:623`,
    `:962`) reaches `SECCHK` wasn't traced. The translation checks every open.
  - **A ghost's privilege** isn't set anywhere read so far. The translation gives ghosts 0.
  - **Synonyms**: how CLOSE enters one, and how the count in X'09' is kept, wasn't found.
- **Random files**:
  - **The short-transfer code.** `RWRAND` ends a request cut short by the end of the file with
    `E5744`, `GEN,7,25 X'44',X'57'` (`WRTF.txt:2087`). The translation takes X'44' as the code; how
    that word lines up with `MSR01EXIT`'s code byte wasn't traced.
  - **The FIT's granule.** OPEN finds a random file's FIT by the X'8000' flag (`OPNF.txt:1747`–
    `:1752`), but what else that granule's header holds wasn't found. The translation writes the
    flags of an empty index block.
  - **Releasing that granule.** `RELRAND` gives back the run; no release of the FIT's granule was
    found. The translation releases it too.
- **Who sets the end-of-file flag** (X'02') on an entry wasn't found, only where it's tested and
  reset.
- **Not read:**
  - OPEN's other paths in detail: shared files, OPEN NEXT, file extension, test files, `*` files;
  - CLOSE's FIT update;
  - for consecutive files, private-pack volume switching (`SWXV`,
    `PVQ20`), the read-ahead (`T:RACONSEC`), and backward reads in detail;
  - `PURGE` (the ghost or processor that removes files in bulk), and the free-sector pool;
  - private packs, cylinder allocation and `GSBP`'s directory pairs in detail;
  - the dual-copy recovery reads;
  - FIX1's repairs;
  - `FRES` (file restore).
