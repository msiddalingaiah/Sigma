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

## In the translation

`python/uts/devopen.py` translates the label and name resolution, with P2OPL's default tables,
and `cal.py` the OPEN:
- `CalProcessor.device_open`: `MSROPN`'s parameters (the error and abnormal addresses, buffer,
  record size, device option, byte displacement), then the resolution;
- a **default OPEN**: a read or write on a closed device DCB in memory opens it first
  (`MSRRDWTA`; `msrrdwt1`).

An assignment ends up as one of:
- `ME`: COC, the user's terminal (`cocio`);
- `TY`: the console, through IOQ;
- `NO`: the null device, where a write does nothing.

Not translated:
- logical devices (`C1`, `L1`, `P1`: symbiont streams, COOP): they stop with `NotTranslated`;
- device allocation (RAT, DCTs): opening on a device type (`CR`, `LP`, …) fails as for a user who
  may not have one, X'49' subcode 2;
- a site's `:OPLB` cards, the `L` bit, the line number in `M:UC`, and DCBs that already hold a
  type and DCT index.

**SLIP** opens `M:SI` with the device option `CR` (its FPT at `X'A1DE'`). For an on-line user,
that fails with X'49'. SLIP's error routine at `X'A0F0'` then opens `F:3` (`ME`), reads a record
keyed by the error code, and prints it with `M:PRINT`, which a default OPEN sends to `M:LL`, the
terminal. Then it ends. On a real system `F:3` is presumably assigned to an error-message file.
SLIP is a card utility: its control card says `CARD TO DISK`, `VERIFY` or `COPY TO TAPE`. To run it
on-line, TEL assigns `M:SI` to a file (`!SLIP fid`, `TEL.txt:648`–`:660`), which is the next step.

## Open questions

- **The label range**: `OPD1` compares the label with `OV:SIZ` (`:94`), taken here as 18, the
  operational labels without the pseudo-entries.
- **`OH:NM`'s further entries**: the table also holds `SH:OPNM` and `SH:LNM` names (logical
  device names, `KRD6`). Only the labels and the device pseudo-entries are modeled.
- **The FUN a device sets**: `OPENDEV` sets the DCB's function from the device's DCT3 bits
  (`NONTAPE`, `:373`–`:383`). The DCB's own function is kept here.
