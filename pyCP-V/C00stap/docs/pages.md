# Memory: the page calls

A user's virtual memory is pages of 512 words, X'50' to X'DF' for the program (`JBUPVP`,
`JEUPVP`). FETCH divides it into areas and records their limits in the JIT. A program asks for
more memory, and gives it back, with the CAL1,8 page calls, which go through the overlay STEPOVR
(`MMOVRTV`, `ALTCP.txt:654`–`:668`) to `MMNR`.

> Source: `MMNR.txt` (the calls, 439 lines), `MM.txt` (`T:GVPI` and `T:RVPI`, `:540`–`:976`;
> `PAGEZAP`, `:414`–`:439`), `JIT.txt` (the limits, `:539`–`:617`; the page constants,
> `:269`–`:298`), `STPNR.txt` (FETCH's limits: `XIT101`, `:1352`–`:1439`; `LINKLIMS`,
> `:1622`–`:1644`; `T:RSTLMS`, `:1145`–`:1156`; `XIT9`, `:1017`–`:1021`).

## 1. The areas and their limits

Each area has a lower and an upper page number, in a doubleword of the JIT. An upper limit
below the lower means the area has no pages (`T:RSTLMS`: lower X'50', upper X'4F').

| JIT word | Limits | Area | Page count (byte of `JB:PCP`) |
|---|---|---|---|
| 270, 271 | `J:BUP`, `J:EUP` | All the user's pages: X'50'–X'DF' | |
| 272, 273 | `J:PLL`, `J:PUL` | Pure procedure | 0, `JB:PCP` |
| 274, 275 | `J:DLL`, `J:DUL` | Data | 1, `JB:PCD` |
| 276, 277 | `J:DDLL`, `J:DDUL` | Dynamic data: the pages a program may get | 2, `JB:PCDD` |
| 278, 279 | `J:CLL`, `J:CUL` | Context (from the JIT page X'46') | 3, `JB:PCC` |
| 280, 281 | `J:DCBLL`, `J:DCBUL` | DCBs | 4, `JB:PCDCB` |
| 285, bytes 0, 1 | `JB:TDP`, `JB:BCP` | The next dynamic page to get (counting up), and the next *common* page (counting down from the top) | |

`JX:CMAP` holds each virtual page's physical page, or `FPMC` (X'20') if the page is free.

**What FETCH sets** (`XIT101`): `LINKLIMS` takes each area from HEAD, the DCBs (HEAD word 6), the
data (word 3) and the procedure (word 4). The lower limit is the high byte of the area's bias
(for the data, the module's bias in word 2, to allow for library data and blank common). The
upper limit is the page of bias + size - 1. An area of size 0 keeps its empty limits. For a
module built by the overlay loader (`OLAYLIM`, HEAD key not X'84'), the dynamic data runs from
the page above the procedure (or the DCBs if there is no procedure, or the data if neither) up
to `J:EUP`, and `JB:TDP` starts at its bottom. `JB:BCP` is X'DF' from the last step's end
(`XIT9`). For a LINK-built module (X'84') the dynamic data runs from above the data to below the DCBs
(or the procedure, if there are no DCBs, or `J:EUP`), `:1396`–`:1414`.

## 2. Getting pages

| Code | Call | Routine | Pages |
|---|---|---|---|
| X'08' | `M:GP n` | `T:GDP` | n pages from `JB:TDP` up |
| X'0C' | `M:GCP n` | `T:GCP` | n pages from `JB:BCP` down |
| X'04' | `M:GVP addr` | `T:GVP` | The one page holding `addr` |

`GAP1` (`MMNR.txt:88`): for each page, `T:GVPM` checks that the call may have it, and `T:GVPI`
maps it. Then:
- **The pointer** (`JB:TDP` or `JB:BCP`) moves past the pages got (`GAP4`), or stops at the page
  that failed.
- **SR1 = the count got, SR2 = the lowest page's address** (`GAP5`: for `M:GCP`, the first page
  less the count plus 1). `M:GVP` returns neither.
- **CC1 is set if not all were got** (`SAD3`/`SAD4`: only CC1 changes).
- The pages are cleaned (`PAGEZAP`).
- If a page was mapped with no physical page free, the user waits for core (`E:NC`).

`T:GVPM` (`:315`): for `M:GP` and `M:GCP` the page must be within the dynamic data
(`GVP1`). For `M:GVP` it may be between `JB:TDP` and `JB:BCP`, or above the procedure up to
`J:EUP`, or in the data. Anything else is refused, except that a processor with JIT access (`SJAC`)
may get its special buffer pages (`GVP9`).

`T:GVPI` (`MM.txt:540`) refuses a page that is already mapped (`GVPO`). It checks the user's
size against the limits (`T:TOTESZ`: the core-limit and swap-size checks), allocates swap granules
and the command list's entries, takes a physical page (`T:GPP`), maps it in `JX:CMAP`, counts it in
the page count of its area (`GVP6`) and in `UB:PCT`, and sets the access codes.

**A real-time user** locked in core is aborted (`RTCHK`).

## 3. Freeing pages

| Code | Call | Routine | Pages |
|---|---|---|---|
| X'09' | `M:FP n` | `T:FDP` | n pages from the top of the dynamic data down |
| X'0D' | `M:FCP n` | `T:FCP` | n pages from the bottom of the common up |
| X'05' | `M:FVP addr` | `T:FVP` | The page holding `addr` |

`RAP1` (`MMNR.txt:183`) starts one page past the pointer (`JB:TDP` - 1, `JB:BCP` + 1). For each
page:
- A free page, or one outside `J:BUP`–`J:EUP`, goes straight to `RVP0`. A page `JB:LMAP` marks
  as mapped by `M:CVM` (1) is unmapped there. An APWP page (2) is never released.
- `RVP0`: **`M:FVP`** may not release a page of the procedure or the DCBs. Outside the user's
  pages only a processor's special buffers qualify (`RAP9`). **`M:FP`** and **`M:FCP`** may only
  release pages of the dynamic data.
- `T:RVPI` (`MM.txt:855`) refuses a page that isn't mapped. It frees the physical page and the
  swap granule, and decrements the area's page count (`RVP6`).

Then the pointer is set to the last page released, or one before the page that failed (`RAP4`).
**SR1 is the count released, for `M:FVP` too** (`RAP5`). CC1 is set if not all were released.

## 4. `M:GL`

`T:GL` (`MMNR.txt:240`), code X'0B': **SR1 = the first word of the common pages got, SR2 = the
last word of the dynamic data's upper page**. With no common pages (`JB:BCP` = `J:DDUL`), SR1
is that last word too.

## 5. Not read here

`M:CVM` (`T:SAD`, X'07', mapping a physical page into a virtual one, privilege X'80') and
`M:SMPRT` (`T:SMP`, X'0A', access codes) were read only as far as `MMNR.txt`.

## In the translation

`python/uts/cal.py`: `get_pages`, `free_pages`, `t_gl`, with `_gvpm`, `_gvpi` and `_rvp`. The
limits and pointers are in the JIT page itself (`jit.py`, words 270–285), and `JX:CMAP` is a set
of mapped pages per user (`cal.cmap`). `fetch.linklims` sets the limits at FETCH (`fetch.pages`:
the program's pages, mapped).

Departures and simplifications:
- **Memory isn't paged.** The interpreter reads and writes any address. Mapping a page only
  records it: a program that uses a page it never got isn't stopped.
- **`T:GVPI` and `T:RVPI`** keep only the checks a program can see (the page free or in use) and
  the page counts (the area's count and `UB:PCT`). The size limits (`T:TOTESZ`), the swap
  granules and command list, the physical pages and their chain (so no wait for core, `E:NC`),
  and the access codes aren't modeled.
- **`PAGEZAP`**: a page is cleaned when it is got and when it is released (its words are removed,
  so they read as 0). CP-V cleans a page it gives out, depending on a privilege test whose operand
  is unclear (below).
- **`JB:LMAP`**, the `M:CVM` and APWP pages, the special buffer pages (`SJAC`: not translated),
  and `RTCHK` aren't modeled. `M:CVM` and `M:SMPRT` stop as not translated.
- **FETCH**: the access codes and page counts (`T:SNAC`) aren't set, and LINK-built modules
  aren't loaded.

## Open questions

- **`PAGEZAP`'s test** (`MM.txt:427`–`:429`) loads `JB:PRIV` into R11 but compares R3 with
  `GZPRIV`. Which pages CP-V leaves uncleaned isn't settled.
