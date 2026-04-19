# AP Assembler — Python Implementation

A Python reimplementation of the **Xerox/Telefile Assembly Program (AP)**,
a four-phase assembler originally written for the Xerox Sigma 5–9 computers.
The source being translated is the **Telefile Computer Products** version,
last updated March 1984.

Reference manual:
[903000C\_Sigma5\_AssemblyProgram\_Jun75.pdf](https://bitsavers.org/pdf/sds/sigma/lang/903000C_Sigma5_AssemblyProgram_Jun75.pdf)

---

## Project Status

| Phase | Component | Status | Tests |
|-------|-----------|--------|-------|
| 1 | Lexer / tokenizer (`lexer.py`) | ✅ Complete | 100 |
| 2 | Value types & arithmetic (`value.py`) | ✅ Complete | 57 |
| 2 | Symbol table & control sections (`symbol_table.py`) | ✅ Complete | 31 |
| 2 | Expression evaluator (`expression.py`) | ✅ Complete | 34 |
| 2 | DEF pass (directive processor) | 🔲 Next | — |
| 3 | GEN pass (code generator) | 🔲 Planned | — |
| 3 | Object file writer | 🔲 Planned | — |
| 3 | Listing writer | 🔲 Planned | — |
| 4 | Concordance (cross-reference) | 🔲 Planned | — |

**222 tests passing** across all completed components.

---

## Repository Layout

```
ap_project/                   ← project root (install / run from here)
│
├── pyproject.toml            ← package metadata; pip install -e .
│
├── ap_assembler/             ← the importable Python package
│   ├── __init__.py
│   ├── lexer.py              ← Phase 1: source reader, tokenizer
│   ├── value.py              ← Value types and arithmetic rules
│   ├── symbol_table.py       ← SymbolTable, ControlSection
│   └── expression.py        ← Expression evaluator
│
└── tests/
    ├── __init__.py
    ├── test_lexer.py         ← 100 tests for lexer.py
    └── test_symbol_table.py  ← 122 tests for value/symbol_table/expression
```

---

## Getting Started

```bash
# Install in editable mode (run once)
cd ap_project
pip install -e .

# Run all tests
python -m pytest

# Run a specific test file
python -m pytest tests/test_lexer.py -v

# Use the tokenizer in code
from ap_assembler.lexer import tokenize_text

for stmt in tokenize_text(source_text):
    print(stmt.line_no, stmt.command, stmt.label, stmt.args)
```

---

## Background: The Original Assembler

AP is a **self-hosting, four-phase assembler** — the source code is itself
written in AP assembly language. It targets the 32-bit, EBCDIC,
big-endian Xerox Sigma architecture.

### Original Assembly Pipeline

```
Source text (SI file)
        │
        ▼ Phase 1 — APNCD (Non-Compressed Deck Reader)
Encoded text (X1 file)   ← binary intermediate; one record per source line
        │
        ├──▶ Phase 2 — APDG DEF pass
        │    Reads X1. Builds symbol table. Allocates storage.
        │    Expands procedure (macro) calls.
        │
        ├──▶ Phase 3 — APDG GEN pass
        │    Re-reads X1. Emits object code (BO file).
        │    Writes assembly listing (LO file).
        │
        └──▶ Phase 4 — APCNC
             Reads X1. Produces cross-reference listing.
```

The two-pass structure is essential: forward references (symbols used before
they are defined) are resolved in the GEN pass using the symbol table built
during the DEF pass.

AP's **procedure system** (PROC/PEND/CNAME/FNAME) is significantly more
powerful than traditional assembler macros: procedures can be recursive,
function procedures return values into expressions, and a rich set of
intrinsic functions (`AF`, `CF`, `LF`, `NUM`, `SCOR`, `TCOR`, …) gives
procedures full access to their call-site arguments.

---

## Module Reference

### `lexer.py` — Phase 1 Tokenizer

Reads AP assembly source text and produces a stream of `Statement` objects,
one per logical source line (which may span multiple physical lines via
continuation).

#### Key classes

**`SourceReader`**
Reads physical source lines, strips sequence columns (73–80), and handles
the `;` line-continuation character. A `;` in columns 1–72 that is not
inside a string literal causes the next physical line to be read and
appended to the current logical line.

**`ArgTokenizer`**
Tokenizes the argument field of a single statement into a list of argument
positions (`List[List[Token]]`). Each inner list is one comma-separated
argument. A blank argument position is `[Token(TT.BLANK_ARG, …)]`.

**`Tokenizer`**
Top-level driver. Splits each physical line into label / command / argument
fields and delegates argument tokenization to `ArgTokenizer`.

#### Token types (`TT` enum)

| Category | Types |
|----------|-------|
| Identifiers | `SYMBOL` |
| Integer constants | `INT`, `HEX`, `OCT`, `PKDEC` |
| Float constants | `FX`, `FS`, `FL` |
| String constant | `CHARSTR` |
| Literal markers | `LIT_L` (`L(...)`), `LIT_EQ` (`=expr`) |
| Operators | `PLUS`, `MINUS`, `MULTIPLY`, `DIVIDE`, `COVDIV`, `SCALE`, `AND_OP`, `OR_OP`, `XOR_OP`, `COMPLEMENT`, `EQ_OP`, `NEQ_OP`, `GT_OP`, `GTE_OP`, `LT_OP`, `LTE_OP` |
| Punctuation | `COMMA`, `LPAREN`, `RPAREN` |
| Special | `INDIRECT` (`*addr`), `BLANK_ARG`, `EOL` |

#### Statement fields

```python
@dataclass
class Statement:
    line_no:    int               # source file line number
    update_no:  int               # minor line number (update packets)
    label:      Optional[str]     # label text, None if blank
    command:    Optional[str]     # command / directive name
    args:       List[List[Token]] # tokenised argument positions
    comment:    str               # raw comment text
    source:     str               # original source text
    is_comment: bool              # True for *-comment lines
```

#### Source format rules

- Columns 1–72 are usable; columns 73–80 are sequence numbers (ignored).
- A line whose first character is `*` is a **comment line**.
- The **label field** occupies column 1 up to the first blank or tab. If
  column 1 is blank, the label is absent.
- The **command field** is the first token after the label separator,
  including any modifier (e.g. `RES,4` or `GEN,8,24`).
- The **argument field** occupies the remainder of the line.
- A `;` character (outside a string literal, within columns 1–72) signals
  **line continuation**: the next physical line is appended.

#### Operator precedence (lowest to highest)

```
| ||        OR, XOR
&           AND
= ~= >= <= > <   comparison
+ -         additive
* / //      multiplicative
**          binary shift (scale)
~ unary-    complement, negate
primary     constants, symbols, (expr), L(...), =expr
```

#### Quick example

```python
from ap_assembler.lexer import tokenize_text, TT

source = """\
ALPHA    EQU      5
         DATA     X'1A2B',O'17',-185
AB       LW,1     L(X'5DF')
"""

for stmt in tokenize_text(source):
    if not stmt.is_comment:
        print(f"L={stmt.label!r:10} C={stmt.command!r:10} args={len(stmt.args)}")
```

---

### `value.py` — Value Types and Arithmetic

Every symbol and expression in AP resolves to a `Value`. This module defines
the type hierarchy and the arithmetic rules that govern how values combine.

#### Value kinds (`ValueKind` enum)

| Kind | Meaning |
|------|---------|
| `UNDEFINED` | Symbol used before definition (forward reference) |
| `ABSOLUTE` | Pure integer — no control section association |
| `RELOCATABLE` | Csect-relative address: `int_val` bytes from section base |
| `EXTERNAL` | External symbol (resolved by the linker) |
| `COMPLEX_SUM` | Sum spanning multiple control sections |
| `PKDEC` | Packed-decimal constant body `D'...'` |
| `CHARSTR` | Character-string constant body `C'...'` |
| `FX` | Fixed-point constant body `FX'...'` |
| `FS` | Float-short constant body `FS'...'` |
| `FL` | Float-long constant body `FL'...'` |
| `BLANK` | Explicitly absent argument |

#### Storage convention

**`int_val` is always in bytes** for `ABSOLUTE` and `RELOCATABLE` values.
The `resolution` field (`BYTE`/`HW`/`WORD`/`DW`) records the *natural
addressing unit* of the value but does not scale `int_val`. Address
functions convert between resolutions by dividing:

```
BA(v) → v.int_val unchanged,  resolution = BYTE
HA(v) → v.int_val // 2,       resolution = HW
WA(v) → v.int_val // 4,       resolution = WORD   (default)
DA(v) → v.int_val // 8,       resolution = DW
```

#### Arithmetic rules

| Left | Op | Right | Result |
|------|-----|-------|--------|
| int | `+` | int | int |
| int | `+` | addr | addr (same csect) |
| addr | `+` | int | addr (same csect) |
| addr | `-` | addr (same csect) | int (difference in bytes) |
| addr | `±` | addr (diff csect) | `COMPLEX_SUM` |
| `UNDEFINED` | any | any | `UNDEFINED` (propagates) |

Adding two relocatable addresses in the same section with `+` (not `-`)
produces a `COMPLEX_SUM`. This is legal in AP for certain loader directives.

#### Quick example

```python
from ap_assembler.value import Value, Resolution, apply_address_function

r1 = Value.relocatable(csect=1, byte_offset=20)
r2 = Value.relocatable(csect=1, byte_offset=8)

diff = r1 + ... # use _add_values(r1, r2, sign=-1)
# → Value.absolute(12)   same section → pure integer

ba = apply_address_function('BA', r1)
# → Value.relocatable(1, 20, Resolution.BYTE)

wa = apply_address_function('WA', r1)
# → Value.relocatable(1, 5, Resolution.WORD)   (20 // 4)
```

---

### `symbol_table.py` — Symbol Table and Control Sections

#### `ControlSection`

Tracks one AP control section. Key fields:

| Field | Type | Meaning |
|-------|------|---------|
| `number` | `int` | Section number (0 = ASECT, 1+ = CSECT/DSECT/…) |
| `kind` | `CsectKind` | `ASECT`, `CSECT`, `DSECT`, `PSECT`, `USECT` |
| `exec_lc` | `int` | Execution location counter (`$` / `%`), in bytes |
| `load_lc` | `int` | Load location counter (`$$` / `%%`), in bytes |
| `max_load_lc` | `int` | High-water mark of `load_lc` (section size) |
| `resolution` | `Resolution` | Natural addressing unit for this section |

`advance(nbytes)` moves both counters forward. `align(boundary)` pads to the
next multiple of `boundary` bytes. `ORG` (implemented in the DEF pass) sets
`exec_lc` directly without moving `load_lc`.

#### `SymbolEntry`

One row in the symbol table:

| Field | Meaning |
|-------|---------|
| `name` | Symbol name (always uppercase) |
| `value` | Current `Value` |
| `is_set` | `True` if `SET` (re-definable), `False` if `EQU`/label |
| `is_local` | `True` for `LOCAL`-declared symbols |
| `external_type` | `''`, `'def'`, `'ref'`, or `'sref'` |
| `defined_pass` | 0 = undefined, 1 = DEF pass, 2 = GEN pass |

#### `SymbolTable`

The top-level container. Maintains:

- `_globals` — global symbol dictionary (name → `SymbolEntry`)
- `_locals` — a stack of scope frames for `LOCAL` symbol shadowing
- `_sections` — list of `ControlSection` objects (index = section number)
- `_current` — active section number
- `_pass` — `PASS_DEF` (1) or `PASS_GEN` (2)

Key methods:

```python
sym = SymbolTable()

# Define symbols
sym.define('ALPHA', Value.absolute(5))
sym.define('COUNT', Value.absolute(0), is_set=True)   # SET — redefinable

# Look up
entry = sym.lookup('ALPHA')       # returns SymbolEntry or None
entry = sym.lookup_or_create('X') # creates UNDEFINED entry if missing

# Location counters
sym.advance_lc(8)         # advance current section by 8 bytes
sym.align_lc(4)           # advance to next 4-byte boundary
v = sym.dollar_value()    # current $ as a Value

# Sections
cs = sym.open_section(CsectKind.CSECT, name='CODE')
sym.switch_to_section(1)

# Local scopes (PROC/PEND)
sym.push_local_scope()
sym.define('TMP', val, is_local=True)  # shadows any global TMP
sym.pop_local_scope()                   # TMP disappears

# External linkage
sym.mark_external('M:LO', 'ref')  # appears on REF directive
sym.mark_external('START', 'def') # appears on DEF directive

# Two-pass management
sym.begin_gen_pass()  # resets all LCs; switches pass to PASS_GEN
```

---

### `expression.py` — Expression Evaluator

`ExpressionEvaluator` walks a flat `List[Token]` (one argument position from
`ArgTokenizer`) and returns a `Value`.

The evaluator is a standard recursive-descent parser structured to match AP's
operator precedence: OR → AND → compare → add → multiply → scale → unary →
primary. It handles:

- All numeric constant types (`INT`, `HEX`, `OCT`, `PKDEC`, `CHARSTR`,
  `FX`, `FS`, `FL`)
- Symbol lookup, including `%` (execution LC) and `%%` (load LC)
- All binary and unary operators
- Addressing functions: `BA()`, `HA()`, `WA()`, `DA()`, `ABSVAL()`, `CS()`
- Literal references: `L(expr)` and `=expr` (placeholder for gen-pass
  literal pool; fully resolved in Phase 3)
- Subscripted symbols: `SYMBOL(args)` dispatches to addressing functions or
  records a subscript for the procedure engine
- Procedure intrinsics (`AF`, `CF`, `LF`, `NUM`, etc.) return `UNDEFINED`
  at the top level; they are fully evaluated inside the procedure engine

#### Convenience function

```python
from ap_assembler.expression import evaluate_arg
from ap_assembler.symbol_table import SymbolTable

sym = SymbolTable()
sym.define('BASE', Value.relocatable(1, 100))

# evaluate_arg takes one argument position (List[Token]) and the symbol table
value, errors = evaluate_arg(tokens[0], sym)
```

---

## Design Notes

### Two-pass architecture

The Python implementation preserves the original two-pass structure even
though there is no X1 binary file. The `Tokenizer` produces a list of
`Statement` objects (the Python equivalent of the X1 records). The DEF pass
walks this list once to populate the symbol table; the GEN pass walks it
again to emit object code.

### `int_val` is always bytes

All relocatable offsets and absolute values are stored in bytes internally.
The `resolution` field on a `Value` records the *intrinsic resolution* (the
natural addressing unit used by instructions that reference this symbol) but
does not affect what `int_val` means. Address functions (`BA`, `WA`, etc.)
divide `int_val` to produce coarser-grained addresses:

```
BA: no division (bytes → bytes)
HA: ÷ 2  (bytes → halfwords)
WA: ÷ 4  (bytes → words, the AP default)
DA: ÷ 8  (bytes → doublewords)
```

### 32-bit arithmetic

Python integers are arbitrary-precision. Where the original relied on
hardware 32-bit overflow, we mask explicitly using `_s32()` (signed) and
`_u32()` (unsigned) helpers. This is applied at every arithmetic boundary in
`value.py`.

### Local scope shadowing

`LOCAL` symbols in AP shadow globals with the same name within the scope of a
procedure definition. `define(is_local=True)` always writes into
`_locals[-1]` (the innermost frame), never updating an existing global.
`lookup()` searches local frames from innermost outward before falling back
to globals.

### What is deferred

Components not yet implemented, and where they will live:

| Deferred item | Future module |
|---------------|---------------|
| `DO`/`DO1`/`ELSE`/`FIN`/`GOTO` flow control | `def_pass.py` |
| `PROC`/`PEND`/`CNAME`/`FNAME` + call stack | `procedure.py` |
| `AF`, `CF`, `LF`, `NUM`, `SCOR`, `TCOR`, … | `procedure.py` |
| Literal pool management | `gen_pass.py` |
| Object record emission (BO format) | `object_writer.py` |
| Assembly listing (LO format) | `listing_writer.py` |
| Concordance (cross-reference) | `concordance.py` |

---

## Planned Directory Structure

Once all phases are implemented the package will look like:

```
ap_assembler/
├── __init__.py
├── lexer.py              ✅ Phase 1 tokenizer
├── value.py              ✅ Value types and arithmetic
├── symbol_table.py       ✅ Symbol table and control sections
├── expression.py         ✅ Expression evaluator
│
├── def_pass.py           🔲 Phase 2: DEF pass main loop + directives
├── procedure.py          🔲 Phase 2: Procedure / macro engine
│
├── gen_pass.py           🔲 Phase 3: GEN pass main loop
├── object_writer.py      🔲 Phase 3: Relocatable object (BO) format
├── listing_writer.py     🔲 Phase 3: Assembly listing formatter
│
└── concordance.py        🔲 Phase 4: Cross-reference listing
```

---

## Running the Tests

```bash
cd ap_project
python -m pytest                          # all 222 tests
python -m pytest tests/test_lexer.py      # 100 lexer tests
python -m pytest tests/test_symbol_table.py  # 122 value/symtab/expr tests
python -m pytest -v                       # verbose output
python -m pytest -k "test_hex"            # filter by name
```

### Test coverage summary

**`test_lexer.py`** (100 tests)

| Class | Tests | What it covers |
|-------|-------|----------------|
| `TestCommentLines` | 3 | Star-comment detection |
| `TestLabelField` | 5 | Blank label, symbol labels, special chars |
| `TestCommandField` | 4 | Simple, subfield (`RES,4`), case folding |
| `TestDecimalIntegers` | 4 | Simple, large, zero, multi-arg |
| `TestHexConstants` | 4 | `X'...'` — simple, uppercase, max, multi |
| `TestOctalConstants` | 2 | `O'...'` |
| `TestPackedDecimal` | 4 | `D'...'` — unsigned, ±, large |
| `TestFloatConstants` | 5 | `FX`, `FS`, `FL` — simple, complex, multi |
| `TestCharString` | 5 | `C'...'`, unadorned, embedded `''` |
| `TestSymbols` | 4 | Regular, colon, `$` prefix, `%` |
| `TestOperators` | 14 | All binary operators |
| `TestUnaryOps` | 2 | Unary `−`, unary `+` |
| `TestLiterals` | 4 | `L(...)`, `=expr`, with hex/symbol |
| `TestIndirect` | 2 | `*addr` indirect addressing |
| `TestParens` | 2 | Simple and nested parentheses |
| `TestMultipleArgs` | 3 | Two, five, blank between commas |
| `TestSubscript` | 3 | `AF(1)`, `BA(x)`, nested |
| `TestContinuation` | 2 | `;` continuation across lines |
| `TestFullStatements` | 9 | Round-trip from `testtese.txt` examples |
| `TestArgTokenizer` | 20 | `ArgTokenizer` unit tests |

**`test_symbol_table.py`** (122 tests)

| Class | Tests | What it covers |
|-------|-------|----------------|
| `TestValueConstruction` | 11 | All Value factory methods and predicates |
| `TestValueArithmetic` | 13 | int±int, int±addr, addr±int, addr−addr, complex sum, negate, complement |
| `TestIntBinop` | 14 | All integer operators including AP comparison semantics (true=−1) |
| `TestAddressFunctions` | 8 | `BA`, `HA`, `WA`, `DA`, `ABSVAL` |
| `TestControlSection` | 5 | `advance`, `align`, `current_value`, high-water mark |
| `TestSymbolTable` | 16 | define, lookup, SET, external, LC ops, sections, scopes |
| `TestEvalConstants` | 11 | All constant token types via evaluator |
| `TestEvalArithmetic` | 13 | All operators through the full pipeline |
| `TestEvalSymbols` | 7 | Symbol lookup, `%`, reloc arithmetic |
| `TestEvalAddressFunctions` | 6 | Address functions through the evaluator |
| `TestEvalRoundTrip` | 8 | `testtese.txt` expressions end-to-end |
| `TestSectionIntegration` | 4 | Labels at LC, RES advances, multi-section |
