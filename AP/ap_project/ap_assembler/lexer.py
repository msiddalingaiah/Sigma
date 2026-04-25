"""
ap_assembler/lexer.py - Phase 1 Lexer and Tokenizer for the Xerox/Telefile
Assembly Program (AP).

Reads AP assembly source text and produces a stream of Statement objects,
each representing one logical source line broken into its four fields:
label, command, arguments, and comment.

Based on APNCD (Non-Compressed Deck Reader) from the Telefile AP assembler,
March 1984.

Source line format (80-column card image):
  - Columns  1-72 : usable source text
  - Column  72    : if ';', this line continues on the next
  - Columns 73-80 : sequence numbers (ignored during assembly)
  - A line whose first non-blank character (col 1) is '*' is a comment.

Field boundaries:
  - Label   : col 1 up to the first blank/tab (or blank if col 1 is blank)
  - Command : first token after the label separator
  - Argument: everything after the command separator, up to col 72
  - Comment : unstructured text in the argument field after a blank

Within the argument field the tokenizer recognises:
  - Symbols      : 1-63 alphanumeric chars (A-Z 0-9 $ @ # : _), ≥1 alpha
  - Integer      : decimal digit string
  - X'...'       : hexadecimal constant
  - O'...'       : octal constant
  - D'...'       : packed decimal constant
  - FX'...'      : fixed-point decimal constant
  - FS'...'      : floating-point short (32-bit) constant
  - FL'...'      : floating-point long (64-bit) constant
  - C'...' / '...' : character-string constant (EBCDIC, 4 chars per word)
  - L(expr)      : literal (address of the assembled constant value)
  - =expr        : literal (alternate form)
  - Operators    : + - * / // ** | || & ~ = ~= >= <= > <
  - Punctuation  : , ( )
  - Indirect     : * prefix before an address expression
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Iterator, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Token types
# ---------------------------------------------------------------------------

class TT(Enum):
    """Token types produced by the argument-field tokenizer."""

    # --- Identifiers --------------------------------------------------------
    SYMBOL      = auto()   # alphanumeric symbol name

    # --- Numeric / constant literals ----------------------------------------
    INT         = auto()   # decimal integer   e.g. 42  2147483647
    HEX         = auto()   # X'...'            e.g. X'1A2B'
    OCT         = auto()   # O'...'            e.g. O'777'
    PKDEC       = auto()   # D'...'            e.g. D'+99'
    FX          = auto()   # FX'...'           e.g. FX'3.75B4'
    FS          = auto()   # FS'...'           e.g. FS'5.5E-3'
    FL          = auto()   # FL'...'           e.g. FL'1.0'
    CHARSTR     = auto()   # C'...' or '...'   e.g. 'ABCD'

    # --- Prefix markers for literal expressions -----------------------------
    LIT_L       = auto()   # L( ... )  — address of assembled value
    LIT_EQ      = auto()   # = expr    — address of assembled value (alt)

    # --- Operators (lowest to highest precedence) ---------------------------
    OR_OP       = auto()   # |   logical OR
    XOR_OP      = auto()   # ||  logical XOR
    AND_OP      = auto()   # &   logical AND
    EQ_OP       = auto()   # =   equality test
    NEQ_OP      = auto()   # ~=  not equal
    GTE_OP      = auto()   # >=
    LTE_OP      = auto()   # <=
    GT_OP       = auto()   # >
    LT_OP       = auto()   # <
    PLUS        = auto()   # +   (binary or unary)
    MINUS       = auto()   # -   (binary or unary)
    DIVIDE      = auto()   # /
    COVDIV      = auto()   # //  covered quotient (div, round toward zero)
    MULTIPLY    = auto()   # *   (binary)
    SCALE       = auto()   # **  binary shift
    COMPLEMENT  = auto()   # ~   bitwise complement (unary)

    # --- Punctuation --------------------------------------------------------
    COMMA       = auto()   # ,
    LPAREN      = auto()   # (
    RPAREN      = auto()   # )
    INDIRECT    = auto()   # *addr — indirect addressing mode

    # --- Structural markers -------------------------------------------------
    BLANK_ARG   = auto()   # explicitly absent argument (blank between commas)
    EOL         = auto()   # end of logical line


# ---------------------------------------------------------------------------
# Token and Statement dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Token:
    """A single token from the argument field (or label/command field)."""
    type:  TT
    value: object          # str for SYMBOL/CHARSTR; int for INT/HEX/OCT;
                           # bytes for PKDEC; float for FS/FL/FX; None otherwise
    raw:   str             # exact source text that produced this token
    line:  int             # 1-based major source line number
    col:   int             # 0-based column of the first character

    def __repr__(self) -> str:
        if self.value is None:
            return f"Token({self.type.name}, line={self.line}, col={self.col})"
        return f"Token({self.type.name}, {self.value!r}, line={self.line}, col={self.col})"


@dataclass
class Statement:
    """One logical AP source statement (may span several physical lines)."""
    line_no:    int              # major line number (source file line)
    update_no:  int              # minor line number (non-zero for update inserts)
    label:      Optional[str]    # label text (None = blank label field)
    command:    Optional[str]    # command / directive name (None = comment/blank)
    args:       List[List[Token]]# tokenised argument field: one list per comma-
                                 # separated argument position.  A single-element
                                 # list containing BLANK_ARG means that position
                                 # was explicitly blank.
    comment:    str              # raw comment text (after argument field)
    source:     str              # joined source text of all physical lines
    is_comment: bool             # True for whole-line comment (*...)


# ---------------------------------------------------------------------------
# Character-class helpers  (mirrors CONVTBL in APNCD)
# ---------------------------------------------------------------------------

# AP symbol characters: letters, digits, $, @, #, : (colon), _ (break char)
# Note: % is included in _ALPHA so symbols like %OR%, %IF%, P# retain their
# full name.  Standalone % and %% (location counters) are handled in
# _parse_primary before the alpha branch fires.
_ALPHA = frozenset('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz$@#:_%')
_DIGIT = frozenset('0123456789')
_ALNUM = _ALPHA | _DIGIT
_HEX   = frozenset('0123456789ABCDEFabcdef')
_OCT   = frozenset('01234567')

def _is_alpha(c: str) -> bool:
    return c in _ALPHA

def _is_digit(c: str) -> bool:
    return c in _DIGIT

def _is_alnum(c: str) -> bool:
    return c in _ALNUM

def _is_hex(c: str) -> bool:
    return c in _HEX

def _is_oct(c: str) -> bool:
    return c in _OCT


# ---------------------------------------------------------------------------
# SourceReader  (READCARD + CHAR in APNCD)
# ---------------------------------------------------------------------------

class SourceReader:
    """
    Reads physical source lines, strips sequence columns (73-80), handles
    line continuation (';' in col 1-72), and presents a flat character stream
    to the tokenizer.

    The reader also tracks the current major/minor line number so that each
    character consumed can be attributed to a position in the source file.
    """

    USABLE_COLS = 72   # columns 1-72 are usable; 73-80 are sequence numbers

    def __init__(self, lines: List[str], filename: str = '<source>'):
        # Normalise: strip CR/LF, pad/trim to usable width
        self._raw_lines: List[str] = [
            line.rstrip('\r\n') for line in lines
        ]
        self._filename  = filename
        self._phys_idx  = 0      # index into _raw_lines
        self._col       = 0      # current column within the current logical line
        self._in_string = False  # True when inside a character-string literal
        self._line_no   = 0      # current major (physical) line number (1-based)
        self._update_no = 0      # minor (update) line number

        # _buf : the characters of the current logical line (post-continuation)
        self._buf: str = ''

        self._advance_physical()

    # ------------------------------------------------------------------
    # Internal: advance to the next physical line and strip seq numbers
    # ------------------------------------------------------------------

    def _advance_physical(self) -> bool:
        """Load the next physical line into _buf. Returns False at EOF."""
        while self._phys_idx < len(self._raw_lines):
            raw = self._raw_lines[self._phys_idx]
            self._phys_idx += 1
            self._line_no += 1
            # Truncate to usable columns; the original used LASTIN=72 (0-based 71)
            usable = raw[:self.USABLE_COLS]
            # Pad to exactly USABLE_COLS so column accesses don't raise IndexError
            self._buf = usable.ljust(self.USABLE_COLS)
            self._col = 0
            return True
        # EOF
        self._buf = ''
        return False

    # ------------------------------------------------------------------
    # Public interface: get the next character
    # ------------------------------------------------------------------

    def peek(self) -> str:
        """Return the next character without consuming it ('' at end)."""
        if self._col < len(self._buf):
            return self._buf[self._col]
        return ''

    def get(self) -> str:
        """
        Return the next character and advance the position.

        Handles the ';' continuation character exactly as APNCD does:
          - When ';' is encountered and we are NOT inside a string literal,
            the remainder of the current physical line is discarded and the
            next physical line is read.  The first non-blank character of the
            continuation line is returned as the next character.
          - When ';' appears at or past column 72, or inside a string, it is
            treated as a literal ';'.
        """
        if self._col >= len(self._buf):
            return '\0'      # signals end-of-logical-line to the caller

        ch = self._buf[self._col]
        self._col += 1

        # Continuation handling (mirrors CHAR routine in APNCD)
        if ch == ';' and not self._in_string:
            # Is there more content on this line (within usable cols)?
            if self._col < self.USABLE_COLS:
                # It's a genuine continuation marker; skip to the next line
                if not self._advance_physical():
                    return '\0'
                # Skip leading blanks on the continuation line (col 1 must be
                # blank or tab; '*' lines are treated as comments and skipped)
                while True:
                    if self._col >= len(self._buf):
                        break
                    c = self._buf[self._col]
                    if c == '*':
                        # Whole-line comment: skip entire physical line
                        if not self._advance_physical():
                            return '\0'
                        continue
                    if c in (' ', '\t'):
                        self._col += 1
                        continue
                    break
                if self._col >= len(self._buf):
                    return ' '
                return self.get()   # recursive: get the first real char
            else:
                # ';' at or past col 72 — treat as space (end of usable area)
                return ' '

        return ch

    def get_line_no(self) -> int:
        """Current major (physical) line number (1-based)."""
        return self._line_no

    def get_col(self) -> int:
        """Current column (0-based) in the logical line."""
        return self._col - 1   # -1 because we already advanced past the char

    def set_in_string(self, flag: bool) -> None:
        """Tell the reader whether we are currently inside a string literal."""
        self._in_string = flag

    def at_eol(self) -> bool:
        """True if there are no more usable characters on the current line."""
        return self._col >= self.USABLE_COLS

    def at_eof(self) -> bool:
        """True if all physical lines have been consumed."""
        return self._phys_idx >= len(self._raw_lines) and self.at_eol()

    def current_line_text(self) -> str:
        """The full text of the current physical line (for error messages)."""
        return self._buf

    def skip_to_eol(self) -> None:
        """Discard the rest of the current logical line."""
        self._col = self.USABLE_COLS


# ---------------------------------------------------------------------------
# Argument-field tokenizer
# ---------------------------------------------------------------------------

class ArgTokenizer:
    """
    Tokenizes the argument field of a single AP source statement.

    The argument field has already been extracted as a plain string by the
    time this class is called.  The tokenizer returns a list of argument
    lists: ``[[tok, tok, ...], [tok, tok, ...], ...]`` where each inner list
    corresponds to one comma-separated position in the argument field.

    A blank position is represented as ``[Token(BLANK_ARG, ...)]``.

    The tokenizer is intentionally forgiving: unknown characters are returned
    as SYMBOL tokens so that error reporting can happen in a later phase.
    """

    def __init__(self, text: str, line_no: int, start_col: int):
        self._text    = text        # raw argument-field text
        self._pos     = 0           # current position within text
        self._line_no = line_no
        self._start_col = start_col # column of text[0] in the source line

    # ------------------------------------------------------------------
    # Character-level helpers
    # ------------------------------------------------------------------

    def _col(self) -> int:
        return self._start_col + self._pos

    def _peek(self, offset: int = 0) -> str:
        idx = self._pos + offset
        return self._text[idx] if idx < len(self._text) else ''

    def _get(self) -> str:
        ch = self._peek()
        self._pos += 1
        return ch

    def _skip_blanks(self) -> None:
        while self._peek() in (' ', '\t'):
            self._pos += 1

    def _at_end(self) -> bool:
        return self._pos >= len(self._text)

    def _remaining(self) -> str:
        return self._text[self._pos:]

    # ------------------------------------------------------------------
    # Token constructors
    # ------------------------------------------------------------------

    def _tok(self, tt: TT, value: object, raw: str) -> Token:
        return Token(tt, value, raw, self._line_no, self._col() - len(raw))

    # ------------------------------------------------------------------
    # Constant parsers
    # ------------------------------------------------------------------

    def _read_quoted(self, start_col: int) -> str:
        """
        Read characters up to the closing single quote, treating '' as an
        escaped quote.  The opening quote has already been consumed.
        Returns the raw content (not including surrounding quotes).
        """
        result = []
        while not self._at_end():
            ch = self._get()
            if ch == "'":
                if self._peek() == "'":
                    # Escaped quote: two consecutive '' → one '
                    self._get()
                    result.append("'")
                else:
                    break   # end of string
            else:
                result.append(ch)
        return ''.join(result)

    def _parse_hex_const(self) -> Token:
        """Parse X'hexdigits' — called after 'X' and "'" have been consumed."""
        col = self._col()
        digits = []
        while self._peek() in _HEX:
            digits.append(self._get())
        if self._peek() == "'":
            self._get()   # closing quote
        raw = "X'" + ''.join(digits) + "'"
        value = int(''.join(digits), 16) if digits else 0
        return Token(TT.HEX, value, raw, self._line_no, col - 2)

    def _parse_oct_const(self) -> Token:
        """Parse O'octdigits' — called after 'O' and "'" have been consumed."""
        col = self._col()
        digits = []
        while self._peek() in _OCT:
            digits.append(self._get())
        if self._peek() == "'":
            self._get()
        raw = "O'" + ''.join(digits) + "'"
        value = int(''.join(digits), 8) if digits else 0
        return Token(TT.OCT, value, raw, self._line_no, col - 2)

    def _parse_pkdec_const(self) -> Token:
        """
        Parse D'[+-]digits' — packed decimal constant.
        Returns a Token whose value is the raw string of signed digits (the
        actual BCD packing is done in the code-generator phase).
        """
        col = self._col()
        sign = ''
        if self._peek() in ('+', '-'):
            sign = self._get()
        digits = []
        while self._peek() in _DIGIT:
            digits.append(self._get())
        if self._peek() == "'":
            self._get()
        raw = "D'" + sign + ''.join(digits) + "'"
        value = sign + ''.join(digits)
        return Token(TT.PKDEC, value, raw, self._line_no, col - 2)

    def _parse_float_body(self) -> str:
        """
        Parse the body of a FX/FS/FL constant (everything inside the quotes).
        Returns the raw content string.
        """
        content = []
        while not self._at_end() and self._peek() != "'":
            content.append(self._get())
        if self._peek() == "'":
            self._get()
        return ''.join(content)

    def _parse_char_const(self) -> Token:
        """
        Parse C'...' or '...' character string.
        Returns a Token whose value is the Python string of characters.
        (Encoding to packed 4-chars/word EBCDIC words is done in code-gen.)
        """
        col = self._col()
        content = self._read_quoted(col)
        raw = "'" + content.replace("'", "''") + "'"
        return Token(TT.CHARSTR, content, raw, self._line_no, col - 1)

    def _parse_decimal_int(self, first_digit: str) -> Token:
        """Parse a decimal integer. first_digit is already consumed."""
        col = self._col()
        digits = [first_digit]
        while self._peek() in _DIGIT:
            digits.append(self._get())
        raw = ''.join(digits)
        value = int(raw)
        return Token(TT.INT, value, raw, self._line_no, col - 1)

    def _parse_symbol(self, first_char: str) -> Token:
        """
        Parse a symbol starting with first_char (already consumed).
        Symbols may be up to 63 characters long.
        """
        col = self._col()
        chars = [first_char]
        while len(chars) < 63 and _is_alnum(self._peek()):
            chars.append(self._get())
        name = ''.join(chars).upper()
        return Token(TT.SYMBOL, name, name, self._line_no, col - 1)

    # ------------------------------------------------------------------
    # Top-level argument-list parser
    # ------------------------------------------------------------------

    def tokenize(self) -> List[List[Token]]:
        """
        Parse the entire argument field and return a list of argument lists.

        Each element of the outer list corresponds to one comma-separated
        argument position.  Each inner list is a flat list of tokens for that
        argument's expression.  A blank (absent) argument position is
        represented by ``[Token(BLANK_ARG, None, '', ...)]``.
        """
        self._skip_blanks()
        if self._at_end():
            return []   # completely empty argument field

        result: List[List[Token]] = []
        while True:
            arg_tokens = self._parse_one_arg()
            result.append(arg_tokens)
            self._skip_blanks()
            if self._at_end():
                break
            if self._peek() == ',':
                self._get()   # consume comma
                self._skip_blanks()
                # If nothing follows, the trailing comma creates a blank arg
                if self._at_end():
                    result.append([self._tok(TT.BLANK_ARG, None, '')])
            else:
                # Unexpected character after argument — stop (rest is comment)
                break

        return result

    def _parse_one_arg(self) -> List[Token]:
        """
        Parse one argument position (the tokens between commas at the top
        level of the argument field).

        Handles:
          * blank argument  →  [BLANK_ARG]
          * *expr           →  [INDIRECT] + expr_tokens
          * =expr           →  [LIT_EQ] + expr_tokens
          * expr            →  expr_tokens
        """
        self._skip_blanks()
        if self._at_end() or self._peek() == ',':
            return [Token(TT.BLANK_ARG, None, '', self._line_no, self._col())]

        tokens: List[Token] = []

        # Indirect-address prefix: *expression  (but not ** scale operator)
        if self._peek() == '*':
            next2 = self._peek(1)
            if next2 not in ('*', ' ', '\t', ',', '\0', ''):
                col = self._col()
                self._get()   # consume *
                tokens.append(Token(TT.INDIRECT, None, '*', self._line_no, col))
                tokens.extend(self._parse_expr())
                return tokens

        # Literal prefix:  =expression
        if self._peek() == '=':
            col = self._col()
            self._get()   # consume =
            tokens.append(Token(TT.LIT_EQ, None, '=', self._line_no, col))
            tokens.extend(self._parse_expr())
            return tokens

        tokens.extend(self._parse_expr())
        return tokens

    # ------------------------------------------------------------------
    # Expression parser  (recursive-descent, mirrors FA1..FA5 grammar)
    # ------------------------------------------------------------------

    def _parse_expr(self) -> List[Token]:
        """
        Parse a full expression: OR-level (lowest precedence).
        Returns a flat infix token list; precedence is preserved by nesting
        later phases can evaluate left-to-right with the standard rules.
        """
        return self._parse_or()

    def _parse_or(self) -> List[Token]:
        """Handles |  and  ||  (OR / XOR)."""
        tokens = self._parse_and()
        while True:
            self._skip_blanks()
            ch = self._peek()
            if ch == '|':
                col = self._col()
                self._get()
                if self._peek() == '|':
                    self._get()
                    tokens.append(Token(TT.XOR_OP, None, '||', self._line_no, col))
                else:
                    tokens.append(Token(TT.OR_OP, None, '|', self._line_no, col))
                tokens.extend(self._parse_and())
            else:
                break
        return tokens

    def _parse_and(self) -> List[Token]:
        """Handles &  (AND)."""
        tokens = self._parse_compare()
        while True:
            self._skip_blanks()
            if self._peek() == '&':
                col = self._col()
                self._get()
                tokens.append(Token(TT.AND_OP, None, '&', self._line_no, col))
                tokens.extend(self._parse_compare())
            else:
                break
        return tokens

    def _parse_compare(self) -> List[Token]:
        """Handles =  ~=  >=  <=  >  <  (comparison operators)."""
        tokens = self._parse_add()
        while True:
            self._skip_blanks()
            ch  = self._peek()
            ch2 = self._peek(1)
            col = self._col()

            # ~= or J= (EBCDIC NOT sign, sometimes appears as J)
            if ch == '~' and ch2 == '=':
                self._get(); self._get()
                tokens.append(Token(TT.NEQ_OP, None, '~=', self._line_no, col))
                tokens.extend(self._parse_add())
            elif ch == '>' and ch2 == '=':
                self._get(); self._get()
                tokens.append(Token(TT.GTE_OP, None, '>=', self._line_no, col))
                tokens.extend(self._parse_add())
            elif ch == '<' and ch2 == '=':
                self._get(); self._get()
                tokens.append(Token(TT.LTE_OP, None, '<=', self._line_no, col))
                tokens.extend(self._parse_add())
            elif ch == '>' and ch2 not in ('=',):
                self._get()
                tokens.append(Token(TT.GT_OP, None, '>', self._line_no, col))
                tokens.extend(self._parse_add())
            elif ch == '<' and ch2 not in ('=',):
                self._get()
                tokens.append(Token(TT.LT_OP, None, '<', self._line_no, col))
                tokens.extend(self._parse_add())
            # NOTE: bare '=' is also the assignment / literal prefix operator.
            # In expression context (not at the start of an arg), treat it as
            # equality test only when it is NOT the first token of the arg.
            # This is handled by _parse_one_arg consuming '=' as LIT_EQ first.
            elif ch == '=' and ch2 not in ("'",):
                self._get()
                tokens.append(Token(TT.EQ_OP, None, '=', self._line_no, col))
                tokens.extend(self._parse_add())
            else:
                break
        return tokens

    def _parse_add(self) -> List[Token]:
        """Handles +  -  (additive operators)."""
        tokens = self._parse_mul()
        while True:
            self._skip_blanks()
            ch  = self._peek()
            col = self._col()
            if ch == '+':
                self._get()
                tokens.append(Token(TT.PLUS, None, '+', self._line_no, col))
                tokens.extend(self._parse_mul())
            elif ch == '-':
                self._get()
                tokens.append(Token(TT.MINUS, None, '-', self._line_no, col))
                tokens.extend(self._parse_mul())
            else:
                break
        return tokens

    def _parse_mul(self) -> List[Token]:
        """Handles *  //  /  **  (multiplicative operators)."""
        tokens = self._parse_unary()
        while True:
            self._skip_blanks()
            ch  = self._peek()
            ch2 = self._peek(1)
            col = self._col()
            if ch == '*' and ch2 == '*':
                self._get(); self._get()
                tokens.append(Token(TT.SCALE, None, '**', self._line_no, col))
                tokens.extend(self._parse_unary())
            elif ch == '*':
                self._get()
                tokens.append(Token(TT.MULTIPLY, None, '*', self._line_no, col))
                tokens.extend(self._parse_unary())
            elif ch == '/' and ch2 == '/':
                self._get(); self._get()
                tokens.append(Token(TT.COVDIV, None, '//', self._line_no, col))
                tokens.extend(self._parse_unary())
            elif ch == '/':
                self._get()
                tokens.append(Token(TT.DIVIDE, None, '/', self._line_no, col))
                tokens.extend(self._parse_unary())
            else:
                break
        return tokens

    def _parse_unary(self) -> List[Token]:
        """Handles unary -  ~  +  prefixes, then primary."""
        self._skip_blanks()
        ch  = self._peek()
        col = self._col()
        if ch == '-':
            self._get()
            tokens = [Token(TT.MINUS, None, '-', self._line_no, col)]
            tokens.extend(self._parse_unary())
            return tokens
        if ch == '~':
            self._get()
            tokens = [Token(TT.COMPLEMENT, None, '~', self._line_no, col)]
            tokens.extend(self._parse_unary())
            return tokens
        if ch == '+':
            self._get()
            tokens = [Token(TT.PLUS, None, '+', self._line_no, col)]
            tokens.extend(self._parse_unary())
            return tokens
        return self._parse_primary()

    def _parse_primary(self) -> List[Token]:
        """
        Handles:
          integer   decimal integer
          X'...'    hex constant
          O'...'    octal constant
          D'...'    packed decimal
          FX'...'   fixed-point
          FS'...'   float short
          FL'...'   float long
          C'...'    character string
          '...'     character string (no C prefix)
          L(expr)   literal
          SYMBOL    identifier (possibly subscripted: SYMBOL(gf))
          (expr)    parenthesised sub-expression
        """
        self._skip_blanks()
        ch  = self._peek()
        ch2 = self._peek(1)
        col = self._col()

        if ch == '(':
            # Parenthesised sub-expression or parenthesised list literal.
            # Collect all comma-separated expressions so that (a,b,c) produces
            # [LPAREN, a-tokens, COMMA, b-tokens, COMMA, c-tokens, RPAREN].
            # A single expression (a) is still a plain grouped sub-expression.
            self._get()
            tokens = [Token(TT.LPAREN, None, '(', self._line_no, col)]
            tokens.extend(self._parse_expr())
            self._skip_blanks()
            while self._peek() == ',':
                comma_col = self._col()
                self._get()   # consume ','
                tokens.append(Token(TT.COMMA, None, ',', self._line_no, comma_col))
                tokens.extend(self._parse_expr())
                self._skip_blanks()
            if self._peek() == ')':
                self._get()
                tokens.append(Token(TT.RPAREN, None, ')', self._line_no, self._col() - 1))
            return tokens

        if _is_digit(ch):
            first = self._get()
            return [self._parse_decimal_int(first)]

        if ch == "'":
            # Unadorned character string: 'text'
            self._get()   # consume opening quote
            return [self._parse_char_const()]

        if _is_alpha(ch):
            # Could be: symbol, X'/O'/D'/FX'/FS'/FL'/FP'/C', or 'L'
            # Read the symbol first to see what we have
            sym_tok = self._parse_symbol(self._get())
            name    = sym_tok.value
            upper   = name.upper()

            self._skip_blanks()

            # Numeric-constant prefix letters
            if upper == 'X' and self._peek() == "'":
                self._get()   # consume opening quote
                return [self._parse_hex_const()]

            if upper == 'O' and self._peek() == "'":
                self._get()
                return [self._parse_oct_const()]

            if upper == 'D' and self._peek() == "'":
                self._get()
                return [self._parse_pkdec_const()]

            if upper in ('C',) and self._peek() == "'":
                self._get()
                return [self._parse_char_const()]

            if upper == 'FX' and self._peek() == "'":
                self._get()
                body = self._parse_float_body()
                raw  = f"FX'{body}'"
                return [Token(TT.FX, body, raw, self._line_no, col)]

            if upper == 'FS' and self._peek() == "'":
                self._get()
                body = self._parse_float_body()
                raw  = f"FS'{body}'"
                return [Token(TT.FS, body, raw, self._line_no, col)]

            if upper == 'FL' and self._peek() == "'":
                self._get()
                body = self._parse_float_body()
                raw  = f"FL'{body}'"
                return [Token(TT.FL, body, raw, self._line_no, col)]

            # 'F' followed by 'X'/'S'/'L' and a quote?
            if upper == 'F' and self._peek() in ('X', 'S', 'L', 'x', 's', 'l'):
                sub = self._peek().upper()
                self._get()   # consume X/S/L
                if self._peek() == "'":
                    self._get()
                    body = self._parse_float_body()
                    raw  = f"F{sub}'{body}'"
                    tt   = {'X': TT.FX, 'S': TT.FS, 'L': TT.FL}[sub]
                    return [Token(tt, body, raw, self._line_no, col)]

            # 'L' followed by '(' → literal L(expr)
            if upper == 'L' and self._peek() == '(':
                lit_col = col
                self._get()   # consume '('
                tokens = [Token(TT.LIT_L, None, 'L(', self._line_no, lit_col)]
                tokens.extend(self._parse_expr())
                self._skip_blanks()
                if self._peek() == ')':
                    self._get()
                    tokens.append(Token(TT.RPAREN, None, ')', self._line_no, self._col() - 1))
                return tokens

            # Regular symbol — check for subscript: SYMBOL(gf)
            tokens = [sym_tok]
            if self._peek() == '(':
                # Subscripted symbol: consume the ( and parse the subscript list
                self._get()
                tokens.append(Token(TT.LPAREN, None, '(', self._line_no, self._col() - 1))
                # Parse a comma-separated list of arguments (the subscript)
                sub_args = self._parse_subscript_args()
                for sub_tok in sub_args:
                    tokens.append(sub_tok)
                if self._peek() == ')':
                    self._get()
                    tokens.append(Token(TT.RPAREN, None, ')', self._line_no, self._col() - 1))
            return tokens

        # Fallback: return a single-character SYMBOL for unrecognised input
        if ch and ch not in (',', ')', '\0'):
            self._get()
            return [Token(TT.SYMBOL, ch, ch, self._line_no, col)]

        return []

    def _parse_subscript_args(self) -> List[Token]:
        """
        Parse a comma-separated list of expressions inside a subscript
        SYMBOL(a, b, c) — used for intrinsic functions like AF(1), BA(X), etc.
        Returns a flat list of tokens including commas between args.
        """
        tokens: List[Token] = []
        while True:
            self._skip_blanks()
            if self._at_end() or self._peek() == ')':
                break
            tokens.extend(self._parse_expr())
            self._skip_blanks()
            if self._peek() == ',':
                col = self._col()
                self._get()
                tokens.append(Token(TT.COMMA, None, ',', self._line_no, col))
            else:
                break
        return tokens


# ---------------------------------------------------------------------------
# Statement-level tokenizer  (the main Phase-1 entry point)
# ---------------------------------------------------------------------------

class Tokenizer:
    """
    Splits a sequence of AP assembly source lines into Statement objects.

    This is the Python equivalent of the DRIVER routine in APNCD, which drove
    a syntax-table-based parser over the source character stream.  Here we
    use a more direct approach appropriate for Python:

      1. Read one physical line.
      2. If col 1 is '*', emit a comment Statement.
      3. Otherwise split into label / command / argument fields.
      4. Use ArgTokenizer to tokenize the argument field.
      5. Handle line continuation (';') via SourceReader.

    The tokenizer preserves the source line text for diagnostic purposes.
    """

    def __init__(self, lines: List[str], filename: str = '<source>'):
        self._reader   = SourceReader(lines, filename)
        self._filename = filename

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def statements(self) -> Iterator[Statement]:
        """Yield Statement objects, one per logical source line."""
        while not self._reader.at_eof():
            stmt = self._read_statement()
            if stmt is not None:
                yield stmt

    # ------------------------------------------------------------------
    # Statement reader
    # ------------------------------------------------------------------

    def _read_statement(self) -> Optional[Statement]:
        """
        Read one logical source line (possibly spanning multiple physical lines
        via continuation) and parse it into a Statement.
        """
        line_no = self._reader.get_line_no()
        buf     = self._reader.current_line_text()

        # --- Comment line: first char is '*' --------------------------------
        if buf and buf[0] == '*':
            comment_text = buf.rstrip()
            self._reader.skip_to_eol()
            self._reader._advance_physical()
            return Statement(
                line_no    = line_no,
                update_no  = 0,
                label      = None,
                command    = None,
                args       = [],
                comment    = comment_text,
                source     = comment_text,
                is_comment = True,
            )

        # --- Blank line -------------------------------------------------------
        if not buf.strip():
            self._reader.skip_to_eol()
            self._reader._advance_physical()
            return None   # skip truly blank lines

        # --- Normal statement: parse the physical line -----------------------
        # We work directly from the buffered line (before any continuation)
        # for the label and command fields, then hand the argument text
        # (which may span continuations) to ArgTokenizer.

        source_lines = [buf]

        # 1. Label field: columns 1-n up to the first blank or tab
        label, cmd_start = self._parse_label(buf)

        # 2. Command field: the next symbol after the label separator
        cmd_text, arg_start = self._parse_command(buf, cmd_start)

        # 3. Argument field: everything from arg_start to col 72
        #    This may involve continuation lines.
        arg_text, extra_lines = self._collect_arg_field(buf, arg_start)
        source_lines.extend(extra_lines)

        # Advance the reader past everything we consumed
        self._reader.skip_to_eol()
        self._reader._advance_physical()

        # 4. Tokenize the argument field
        stripped_arg = arg_text.rstrip()
        arg_lists: List[List[Token]] = []
        if stripped_arg:
            at = ArgTokenizer(stripped_arg, line_no, arg_start)
            arg_lists = at.tokenize()

        return Statement(
            line_no    = line_no,
            update_no  = 0,
            label      = label,
            command    = cmd_text if cmd_text else None,
            args       = arg_lists,
            comment    = '',
            source     = '\n'.join(source_lines),
            is_comment = False,
        )

    # ------------------------------------------------------------------
    # Field parsers
    # ------------------------------------------------------------------

    def _parse_label(self, buf: str) -> Tuple[Optional[str], int]:
        """
        Parse the label field from buf.

        Returns (label_text_or_None, index_of_first_char_after_label).

        AP label rules (from BLNKLBL in APNCD):
          - If col 1 is blank, the label is blank (no label).
          - If col 1 is non-blank, the label runs to the first blank/tab.
          - Label max length is effectively 63 alphanumeric chars.
        """
        if not buf or buf[0] in (' ', '\t'):
            # Blank label: find where the non-blank starts
            i = 0
            while i < len(buf) and buf[i] in (' ', '\t'):
                i += 1
            return None, i

        # Non-blank label
        i = 0
        while i < len(buf) and buf[i] not in (' ', '\t'):
            i += 1
        label = buf[:i].upper()
        return label, i

    def _parse_command(self, buf: str, start: int) -> Tuple[Optional[str], int]:
        """
        Parse the command field from buf starting at index start.

        Returns (command_text_or_None, index_of_first_char_after_command).

        The command is a symbol (optionally followed by a modifier after ',').
        Examples:  DATA   RES,4   COM,8,24
        """
        i = start
        # Skip blanks/tab separating label from command
        while i < len(buf) and buf[i] in (' ', '\t'):
            i += 1

        if i >= len(buf):
            return None, i

        # Read the command token (up to blank, tab, or end of usable area)
        j = i
        while j < len(buf) and buf[j] not in (' ', '\t'):
            j += 1
        cmd = buf[i:j].upper()
        return cmd if cmd else None, j

    def _collect_arg_field(self, buf: str, start: int) -> Tuple[str, List[str]]:
        """
        Extract the argument field text, handling line continuation.

        The argument field starts at index `start` and runs to the end of the
        usable area (column 72).  If the last usable character before the
        comment area is ';', the next physical line is a continuation.

        Returns (arg_text, list_of_extra_physical_lines).
        """
        # Skip blanks between command and argument
        i = start
        while i < len(buf) and buf[i] in (' ', '\t'):
            i += 1

        parts: List[str] = []
        extra: List[str] = []

        # Grab argument portion of the first line
        # (strip trailing blanks; if last meaningful char is ';' → continuation)
        line_arg = buf[i:SourceReader.USABLE_COLS]

        while True:
            stripped = line_arg.rstrip()
            if stripped.endswith(';'):
                # Line continuation: collect the rest from the next physical line
                parts.append(stripped[:-1])   # drop the ';'
                # Peek at the next line
                if self._reader._phys_idx < len(self._reader._raw_lines):
                    next_raw = self._reader._raw_lines[self._reader._phys_idx]
                    self._reader._phys_idx += 1
                    self._reader._line_no  += 1
                    next_buf = next_raw[:SourceReader.USABLE_COLS].ljust(SourceReader.USABLE_COLS)
                    extra.append(next_buf)
                    # Find where the continued argument starts (skip leading blanks)
                    k = 0
                    while k < len(next_buf) and next_buf[k] in (' ', '\t'):
                        k += 1
                    line_arg = next_buf[k:]
                else:
                    break   # EOF — stop
            else:
                parts.append(stripped)
                break

        return ' '.join(parts), extra


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def tokenize_file(filename: str) -> Iterator[Statement]:
    """
    Open an AP assembly source file and yield Statement objects.

    >>> for stmt in tokenize_file('mysource.txt'):
    ...     print(stmt.line_no, stmt.command, stmt.label)
    """
    with open(filename, 'r', encoding='ascii', errors='replace') as fh:
        lines = fh.readlines()
    tok = Tokenizer(lines, filename)
    yield from tok.statements()


def tokenize_text(text: str, filename: str = '<string>') -> Iterator[Statement]:
    """
    Tokenize AP assembly source from a string.

    >>> stmts = list(tokenize_text(source_text))
    """
    lines = text.splitlines(keepends=True)
    tok = Tokenizer(lines, filename)
    yield from tok.statements()
