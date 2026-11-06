# Overlays: the tree and `M:SEGLD`

A large program is built by the overlay loader as a **tree of segments**: a root that is always
in memory, and segments that share memory with their siblings and are read in from the load module
when the program asks for them, with **`M:SEGLD`** (CAL1,8 X'01'). EDIT, BASIC, FORT, SORT, AP
and LOADER are all built this way.

> Source: `SEGLD.txt` (`SEGLD`, 516 lines), `ALTCP.txt` (`MSEGLD`, `:1051`–`:1095`),
> `STPNR.txt` (FETCH: `M:SGLD`, `:1480`–`:1499`; `J:TREE`, `:1524`–`:1529`; `ABN2`, `:3538`),
> `S$OVRLYR.txt` (`S:OVRLY`, the program's own call), `T$OV.txt` (`SEGLD#`, `:572`).

## 1. The tree

The `TREE` record is word 0, the tree's size in words, then an 11-word entry per segment, the
root first (`TTESIZE`). FETCH puts the tree in memory too, as the first words of the procedure
section, and `J:TREE` points at it: `J:PLL`'s page (`:1527`–`:1529`). An entry:

| Word | Holds |
|---|---|
| 0–2 | The segment's name, TEXTC |
| 3 | Bit 0: in memory now. Bit 1: was in memory when this `M:SEGLD` began. Right half: the parent's link |
| 4 | Left half: the first child's link. Right half: the next sibling's |
| 5 | The data section: size and bias, in doublewords |
| 7 | The procedure section |
| 9 | The DCB section (the root's) |
| 10 | The debugger's patch table (`MODLOP`) |

A **link** is the entry's tree offset less 1, so the root (offset 1) is link 0. A parent link of 0
ends the walk up. The real trees agree (EDIT's: the root `BO:EDITRT` with children `EDITOV` and
`EDITDI`, siblings; SORT's: 12 segments three levels deep). An overlay's section of size 0 still has
its bias, the address where it would start.

A segment's records have the same keys as the root's: the name and a type byte, 3 data, 5
procedure (FETCH's `LMKEY`).

## 2. FETCH

For a tree of more than 12 words (`:1482`–`:1485`), the program must have a DCB **`M:SGLD`**: B6-00
otherwise (`ABN2`), and B6-0C if there is no room after it for 10 words. FETCH copies `M:XX`'s 10
VLP words (from its word 22: the load module's name, account and password) to `M:SGLD`'s word 22,
where its FLP points. So `M:SGLD` opens the program's own load module. Only the root is read.

## 3. `M:SEGLD`

`MSEGLD` (`ALTCP.txt:1051`) takes the address of the segment's name from FPT word 1 (which may be
indirect, or a register, `J:BASE`). For an unshared program it goes to `SEGLD` in MISOV with
`J:DCBLINK`. A shared processor's overlays are found in `P:NAME` (`PB:LNK`, `T:PROCOV`).

`SEGLD` (`SEGLD.txt:62`):
1. **Finds `M:SGLD`** in the DCB name table. Without it, it returns to the CAL + 1 doing
   nothing (`MSEGLDEX`).
2. **Opens it**, if it isn't open, with its own FPT `OPN` (`:507`): ASN file, keyed, IN.
3. **Checks the tree** is in the user's pages above `J:PLL` (`BADTREE` otherwise).
4. **Shifts the flags** (`MEMLOP`): bit 0 to bit 1 for every entry, the rest of the left half
   cleared. Now bit 1 means "in memory before this call".
5. **Finds the segment** by its TEXTC name, from the second entry on (`KEYLOOP`). Not found:
   abort.
6. **If it was in memory** (`NXTBRNCH`): marks it, and its first child, and that child's first
   child, while they too were in memory. The last one's parent is the deepest segment that stays.
   Otherwise the requested segment is.
7. **Sets the memory** (`CHKSEG`, `MEMSET0`): for the data and the procedure areas, the pages from
   the area's lower limit up to the end of that segment's section are got (`T:GNVPI`), and those
   above it released up to the area's upper limit (`T:RVPI`). An end outside the area is BIGD (3)
   or BIGP (4).
8. **Reads the path** (`CHKSEG1`): from the segment up to the root, each segment's bit 0 is set,
   and one not in memory before has its data and procedure records read to their addresses
   (`RDSEG`). A section must lie in its area and below the pages just got (BADBUF, 5). A record
   longer than the section is cut (X'07' ignored). The walk stops at a parent link of 0, so the
   root is never read again.
9. **Returns** to the CAL + 1, with `PPSWAP` set for the swapper. Delta and its breakpoints
   (`DELTAGO`, `MODLOP`) are handled on the way out.

Errors abort with X'B1' and a subcode (`ABORTIT`, `:502`–`:505`): 0 a read or OPEN error or no
such segment, 1 `TREEBAD`, 2 `CIRCTREE` (more steps than segments), 3 `BIGD`, 4 `BIGP`, 5 `BADB`,
6 no page, 7 a page from `M:CVM`, 8 too many paged segments.

The program calls `M:SEGLD` through the library routine `S:OVRLY` (`S$OVRLYR.txt`): it finds the
segment's entry from `J:TREE`, and skips the CAL if the entry's bit 0 (the in-memory flag) is
already set.

## In the translation

`python/uts/fetch.py`: overlaid modules are read (the root only), `init_sgld` copies `M:XX`'s VLPs,
and `pages` maps only the root's sections. `jit.build` fills `M:XX`'s name and account VLPs.
`python/uts/cal.py`: `msegld`, `segld`, `_memset0`, `_rdseg`. The test builds a small overlaid
module (`tests/test_overlays.py`).

Not modeled:
- **Shared processors' overlays** (`PB:LNK`, `T:PROCOV`), and `RTCHK`.
- **Paged modules** (X'85'): a missing record goes straight to the error, not to the paged keys
  (`RD4`).
- **Delta** (`DELTAGO`) and the debugger's patch table (`MODLOP`), and the debug page
  (`J:ASSIGN` X'60000').
- **`JB:LMAP`**: the tree's pages are checked against the pages mapped (`cal.cmap`).
- **The room check** for `M:SGLD`'s VLPs (B6-0C).

## What the overlaid processors do now

| Processor | |
|---|---|
| EDIT | Its banner and `*` prompt. Commands are read and understood: `BUILD fid` creates the file, then goes back to command mode instead of prompting for lines (not yet understood). `EDIT fid` stops at `M:PRECORD`. `END` returns to TEL |
| SORT | `M:SEGLD` reads `BO:RTPRE`. `TELEFILE SORT`, then its parameter errors, then the debugger CAL (CAL1,3) |
| AP | `M:SEGLD` reads `BO:APCCI`. AP reads `M:SI` from the terminal and stops at `M:GDDL` (CAL1,8 X'1B') |
| FORT | `TELEFILE EXTENDED FORTRAN-IV`, then garbage |
| BASIC | Stops at `M:RFILE` (`MSRTFILE`) |
| LOADER | Stops at `M:STIMER` |

## Open questions

- **EDIT's BUILD**: after creating and reopening the file it returns to command mode; why isn't
  known. Values the translation supplies (the `M:TS` bytes, a DCB field) are the suspects.
