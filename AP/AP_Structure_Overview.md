# Xerox/Telefile Assembly Program (AP) — Source Structure & Python Translation Guide

**Source:** Telefile Computer Products, Inc. — March 1984  
**Target machine:** Xerox Sigma 5–9 (32-bit, EBCDIC, big-endian)  
**Total source:** ~25,600 lines across 14 files, written in AP assembly language (self-hosting)

---

## 1. High-Level Architecture

The AP assembler is a **four-phase, multi-overlay assembler**. Its overall execution pipeline, as driven by `APROOT`, is:

```
APCCI  →  APINIT  →  APNCD  →  APDG (DEF pass)  →  APDG (GEN pass)  →  APEND  →  [APCNC]
  │           │          │             │                    │                │            │
Control    Init &     Phase 1:      Phase 2:           Phase 3:          Phase 3:     Phase 4:
 cards    updates    Encode        Build sym           Generate          End/sum      Cross-ref
                     source        table               object            mary         listing
                     → X1 file     → X1 file           → BO file
```

The key insight is that the assembler **does not process source line by line in one pass**. Instead:

1. **Source is encoded** into an internal binary "encoded text" (X1) format.
2. The encoded text is **read twice** (DEF pass, then GEN pass) by the main assembler kernel.
3. Procedures (macros) may cause the encoded text to be re-read at different positions — this is how macro expansion works.

---

## 2. File / Module Inventory

| File | Module | Lines | Role |
|------|--------|-------|------|
| `aproott.txt` | **APROOT** | 1,246 | Root segment: entry point, global data, I/O wrappers, overlay loader |
| `apccitt.txt` | **APCCI** | 2,019 | Control card interpreter: parses AP option flags (BA, BO, CI, CO, etc.) |
| `apinit.txt` | **APINIT** | 987 | Initialization, update-card (+card) sorting and application |
| `apncdtt.txt` | **APNCD** | 4,031 | Phase 1: Non-compressed deck reader — tokenizes/encodes source to X1 |
| `apdgcom.txt` | **APDGCOM** | 2,028 | Shared assembly routines: code generation, expression output, error handling |
| `apdgctt.txt` | **APDG** | 8,045 | Core assembler engine: directive processors, symbol table, expression evaluator, procedure engine |
| `apdgint.txt` | **APDGINT** | 771 | DEF/GEN pass initialization and finalization |
| `appartt.txt` | **APPART** | 671 | Particularization: machine-specific instruction format handling |
| `apendnt.txt` | **APEND** | 1,060 | Phase 3 end: error summaries, symbol table dump, literal pool output |
| `apcnctt.txt` | **APCNC** | 1,922 | Phase 4: Concordance (alphabetical cross-reference listing) |
| `apcditt.txt` | **APCD** | 1,273 | Compressed deck input handler (alternate to APNCD) |
| `ap-ilnotese.txt` | **AP%IL** | 481 | SYSTEM macro library: defines CALL, EXIT, IF/FI, ABORT, branch procedures |
| `ap-dgnotese.txt` | **AP%DG** | 753 | SYSTEM macro library: numeric IDs for all directives, intrinsic functions, field names |
| `testtese.txt` | **TEST** | 382 | Test suite exercising directives and constant types |

---

## 3. Phase-by-Phase Description

### Phase 1 — Source Encoding (APNCD / APCD)

**Entry point:** `NCDR`

**Input:** Source text from the SI (source input) file — 80-column EBCDIC card images.

**Output:** The X1 "encoded text" file — a compact binary representation of each source statement.

**What it does:**

- Reads each source line character by character.
- Splits the line into **four fields**: Label, Command, Argument, Comment.
- The command field is looked up in the **symbol table** (which at this point contains the built-in directive and mnemonic names). If found, its symbol number is stored; otherwise an "unknown" token is stored.
- Symbols in the label and argument fields are similarly encoded as symbol-table references or literal text.
- The entire encoded statement is written to the X1 buffer/file as a variable-length binary record.
- Syntactic errors (malformed symbols, illegal characters) are flagged here.
- The `SYSTEM` directive is processed in Phase 1 — SYSTEM files are read and encoded inline, building a single unified encoded stream.
- The `LOCAL` / `OPEN` / `CLOSE` directives for symbol scoping are also handled here.

**Python analog:** A **lexer + tokenizer** that converts text source into an AST-like token stream stored as a list of statement records.

---

### Phase 2 — Definition Pass (APDG DEF pass)

**Entry points:** `DGINIT` (init), `DEFGEN` (main loop), `ENDDEF` (finalization)

**Input:** The X1 encoded text file (rewound).

**Output:** The **symbol table** (in memory), with every symbol assigned a value, type, and control-section number.

**What it does:**

- Reads encoded statements sequentially.
- For each statement, processes **directives that define symbols**: `EQU`, `SET`, `ORG`, `LOC`, `CSECT`, `DSECT`, `ASECT`, `PSECT`, `USECT`, `RES`, `DATA`, `TEXT`, `GEN`, `COM`, `S:SIN`, etc.
- Maintains **location counters** (one per control section) as each data-generating directive advances them.
- Processes **procedure definitions** (`PROC`/`PEND`): records the position in the X1 file where the procedure body starts, but does not expand them.
- When a **procedure call** is encountered, the assembler saves its current X1 file position, seeks to the stored procedure body position, and "expands" the procedure by processing it as if it were inline source — this is the macro expansion mechanism.
- `DO`/`DO1`/`ELSE`/`FIN`/`GOTO` conditional and iteration directives are evaluated here, controlling which portions of the encoded text are processed.
- At the end, every symbol's address/value is known (or flagged as a forward reference to be resolved in the GEN pass).

**Python analog:** A **symbol table builder** that walks the token stream, handles control flow (`DO`/`FIN`), expands macros (procedures), and computes all symbol values and storage assignments.

---

### Phase 3 — Generation Pass (APDG GEN pass + APEND)

**Entry points:** `DGINIT` (re-init), `DEFGEN` (same main loop, different mode), `ENDGEN`, then `DGEND`

**Input:** X1 encoded text file (rewound again); the now-complete symbol table.

**Output:**
- **BO file** — binary object module (relocatable object code) in Xerox loader format.
- **LO file** — listing output (printed assembly listing with addresses, hex values, source).
- **DO file** — diagnostic output (error messages).

**What it does:**

- Walks the encoded text stream again, this time generating actual binary code/data for each statement.
- `GENERATE` / `GENERATE1` / `GENERATE2` (in APDGCOM): assemble multi-field instructions by merging expression values into the appropriate bit fields of a word.
- `BEDIT` (in APDGCOM): builds and flushes BO records (the relocatable object format).
- `ACON` (in APDGCOM): emits address constant items for the loader (for relocatable references).
- `PRINT` / `PRINTC` (in APDGCOM): formats and writes listing lines.
- `ERR` (in APDGCOM): formats and writes error messages to DO and LO.
- All the same directive processors and procedure expansion logic runs again, but now producing output instead of just building the symbol table.
- **APEND** runs at the end of the GEN pass: writes the literal pool, emits the end record to the BO file, prints error and symbol summary tables.

**Python analog:** A **code generator** that re-walks the token stream/AST, emitting object bytes and listing lines, using the symbol table built in Phase 2.

---

### Phase 4 — Concordance (APCNC)

**Entry point:** `CONCORD`

**Input:** X1 encoded text file; symbol table.

**Output:** LO file — alphabetically sorted cross-reference listing.

**What it does:** Collects all symbol references (with line numbers), sorts them, and prints them. Largely independent of the main assembler logic.

**Python analog:** A simple **post-processing pass** over the token stream and symbol table.

---

## 4. Key Data Structures

### Symbol Table (in APDG/APDGCOM)

The symbol table is a **hash table** stored in the dynamic memory area (`SYMT`/`SYMT base`). Each symbol entry contains:

- **Name:** packed EBCDIC characters
- **Type:** one of: Undefined, Integer constant, Special integer, Address (absolute), Address (relocatable), External reference, Forward reference, List/procedure name, Local symbol, etc.
- **Value:** 32-bit (or 64-bit for double-precision) value
- **Control section number:** which CSECT this symbol belongs to
- **Resolution:** byte (BA), halfword (HA), word (WA), or doubleword (DA)
- **Attributes:** defined/undefined, public (DEF), external (REF), local, etc.

**Encoded item format:** Symbol values are passed around in a compact 1-or-2-word "item" format that packs type, value, control section, and resolution into bit fields.

### Encoded Text (X1) Format

Each encoded source statement is a variable-length binary record containing:

- A header word with statement type, line number, error flags
- The encoded label field (symbol number or blank)
- The encoded command field (symbol number or directive number)
- The encoded argument field — a sequence of encoded "items" (symbol refs, constants, operators, commas, etc.)

### Location Counters

Two location counters per control section:
- **Execution LC** (`$` / `DLRVAL`): the "load address" — where code/data will be when executed.
- **Load LC** (`$$`): the "assembly address" — position within the object module.

Both are maintained in the `DLRVAL` / `DLRCS` / `DLRRS` (value / control section / resolution) variables.

### Procedure Level Table (PLT)

When a procedure is called, a **Procedure Level Table** (PLT) entry is pushed onto a stack. It records:
- The saved X1 file position (to return to after expansion)
- The procedure's argument list
- The local symbol scope (LOCAL symbols declared within the procedure)
- DO-loop nesting depth
- SYSTEM nesting level

This is how AP supports recursive procedure calls.

### Expression Table (EVT/ECT)

Expressions are evaluated into an **expression table** — a list of items representing the expression tree in RPN order. The `SCAN` routine builds this table; `GENERATE`/`BEDIT` consume it.

---

## 5. Key Routines in APDG

| Routine | Purpose |
|---------|---------|
| `DEFGEN` | Main assembler loop — drives both DEF and GEN passes |
| `SCAN` | Expression evaluator — tokenizes and evaluates argument field expressions |
| `CMNDASN` | Command assignment — dispatches to directive or instruction processor |
| `DEFINE2` | Defines a symbol in the symbol table |
| `LITSRCH` | Looks up or creates a literal table entry |
| `BLDPLT` | Builds a procedure level table (procedure call setup) |
| `LOADXW` | Loads an encoded text word from the X1 buffer |
| `NXTRECRD` | Advances to next encoded text record |
| `LENGTH` | Calculates length of a symbol's storage |
| `LINE%FLDS` | Parses/formats listing line fields |
| `GETPLOC1` | Gets the PLT entry for the current procedure level |
| `SUBVAL` | Subtracts a value from an expression table entry |
| `MAXLOC` | Updates maximum location counter |
| `OLDCSECT` | Saves current control section state |
| `SETDLRS` | Restores a control section state |

Key routines in **APDGCOM**:

| Routine | Purpose |
|---------|---------|
| `GENERATE` | Main code generation — merges field values into instruction word |
| `BEDIT` | Assembles a word into BO record buffer; handles relocatable fields |
| `ACON` | Outputs a loader address constant item |
| `ERR` | Error message output |
| `EDIT` | Edit (format) an expression value for listing |
| `PRINT` | Write a listing line |
| `DFNFLD` | Define a field — processes `GEN`/`COM` field specifications |
| `EXPEND` | Extends an expression in the expression table |
| `CHCKTRUNC` | Checks for truncation (value won't fit in bit field) |

---

## 6. The Procedure (Macro) System

AP's procedures are significantly more powerful than traditional assembler macros. Key features:

- **CNAME procedures** generate statements (command macros).
- **FNAME procedures** return values (function macros, called within expressions).
- Procedures may be **recursive**.
- **Intrinsic functions** (`AF`, `CF`, `LF`, `AFA`, `NAME`, `NUM`, `SCOR`, `TCOR`, `S:UFV`, `S:KEYS`, etc.) give procedures access to their arguments and the assembly environment.
- `DO`/`DO1`/`ELSE`/`FIN`/`GOTO` provide assembly-time control flow within procedures.
- Procedures can call other procedures to arbitrary depth (limited by the PLT stack).

In the source, `AP%IL` and `AP%DG` are **SYSTEM files** that define the "standard library" of procedures — things like `CALL`, `EXIT`, `IF`/`FI`, `BC` (branch on condition), `BFZ`/`BFNZ`, etc. These are themselves written in AP assembly language.

---

## 7. I/O Files

| Internal Name | Role |
|--------------|------|
| `M:SI` / `F:STD` | Source input (SI = card reader / terminal; STD = standard definition file) |
| `M:CI` | Compressed source input |
| `F:X1` | Encoded text (X1) file — intermediate between Phase 1 and Phases 2/3/4 |
| `F:X2` | Update (+card) sort work file |
| `F:X3` | Compressed source work file |
| `F:X5` | Concordance overflow file (keyed/random) |
| `M:BO` | Binary object output |
| `M:CO` | Compressed source output |
| `M:LO` | Listing output |
| `M:DO` | Diagnostic output |
| `M:GO` | GO (load-and-go) object output |
| `M:SO` | Symbolic debugging output |

---

## 8. Python Translation Strategy

The goal is a Python implementation that **replicates the assembler's behavior** for a modern context (likely targeting object code analysis/generation, or a simulator). Recommended structure:

### Package Layout

```
ap_assembler/
│
├── __main__.py            # CLI entry point
├── options.py             # AP option flags (BA, BO, CI, CO, DC, LO, ...)
│
├── phase1/
│   ├── lexer.py           # Character-level scanner (APNCD)
│   ├── tokenizer.py       # Field splitter — label/command/arg/comment
│   ├── encoder.py         # Converts tokens to encoded statement records
│   └── source_reader.py   # SI file reader, SYSTEM file inclusion
│
├── phase2/
│   ├── symbol_table.py    # Symbol table (hash map of SymbolEntry objects)
│   ├── def_pass.py        # DEF pass main loop (DEFGEN in DEF mode)
│   ├── location_counter.py # LC management per control section
│   └── procedure_engine.py # Procedure stack, PLT, argument binding
│
├── phase3/
│   ├── gen_pass.py        # GEN pass main loop (DEFGEN in GEN mode)
│   ├── code_generator.py  # GENERATE/BEDIT — instruction word assembly
│   ├── object_writer.py   # BO file format writer
│   └── listing_writer.py  # LO file formatter (PRINT/ERR routines)
│
├── phase4/
│   └── concordance.py     # Cross-reference listing (APCNC)
│
├── directives/
│   ├── base.py            # Directive base class
│   ├── section.py         # CSECT, DSECT, ASECT, PSECT, USECT, SSECT
│   ├── storage.py         # RES, DATA, TEXT, TEXTC, GEN, COM, S:SIN
│   ├── symbol_ops.py      # EQU, SET, LOCAL, OPEN, CLOSE, DEF, REF, SREF
│   ├── control.py         # DO, DO1, ELSE, FIN, GOTO, END, SYSTEM
│   ├── location.py        # ORG, LOC, BOUND
│   ├── listing.py         # SPACE, PAGE, TITLE, LIST, PCC, PSR, PSYS, DISP
│   ├── procedure.py       # PROC, PEND, CNAME, FNAME
│   └── error_dir.py       # ERROR directive
│
├── expressions/
│   ├── evaluator.py       # SCAN — expression parser and evaluator
│   ├── items.py           # Item types (integer, address, external, sum, ...)
│   └── functions.py       # Intrinsic functions (AF, CF, LF, NUM, SCOR, ...)
│
├── constants.py           # Constant type parsers (X, O, D, FX, FS, FL, C)
└── errors.py              # Error codes and message formatting
```

### Translation Priorities

**Phase 1 (start here):** The lexer and tokenizer are the most self-contained piece. Rather than implementing a binary X1 format, use Python objects (dataclasses or named tuples) as the intermediate representation.

**Symbol table:** Implement as a Python dict with `SymbolEntry` dataclasses. The two-pass structure means you'll need to distinguish "defined in DEF pass" from "forward reference resolved later."

**Expression evaluator (`SCAN`):** This is the most complex single routine — it handles arithmetic, logical, and relational operators, parenthesized sub-expressions, literals, address functions (BA/HA/WA/DA), and intrinsic function calls. Implement as a recursive-descent or Pratt parser.

**Procedure engine:** Implement as a call stack of `ProcedureFrame` objects. Each frame holds the bound arguments, the iterator state for DO loops, and a pointer back into the token stream for the procedure body.

**Code generation:** For a Python implementation, the "BO file" can be a list of `ObjectRecord` objects. If you're targeting a simulator, you can emit bytes directly. The tricky part is the relocatable address system — you'll need to track which words contain relocatable references and what their control sections are.

### Key Simplifications for Python

1. **No EBCDIC:** The original uses EBCDIC throughout. In Python, work in plain ASCII/Unicode and add an EBCDIC codec only if you need binary compatibility with actual Sigma object files.

2. **No overlay management:** The original loads overlays from disk due to 1980s memory constraints. In Python all code is always in memory.

3. **No X1 binary file:** Use Python lists/iterators of statement objects instead.

4. **32-bit arithmetic:** Python integers are arbitrary precision, so you'll need to explicitly mask to 32 bits where the original relied on hardware overflow. Use `value & 0xFFFFFFFF` and sign-extend where needed.

5. **The two-pass structure is still needed:** Even in Python, you must make two passes over the statement list — one to build the symbol table, one to generate code. Forward references require this.

---

## 9. Suggested Starting Point

Begin with a small but complete vertical slice:

1. Parse a simple source file (label, opcode, operands, comment) into statement records.
2. Implement `EQU`, `SET`, `DATA`, `RES`, `CSECT`, `ORG`, `END` directives.
3. Implement the expression evaluator for integer arithmetic and symbol references.
4. Implement the two-pass structure (DEF then GEN).
5. Output a simple hex listing.

Once that works end-to-end, add: `TEXT`/`TEXTC`, `BOUND`, `DO`/`FIN`, then the procedure system, then instruction encoding via `GEN`/`COM`/`S:SIN`.
