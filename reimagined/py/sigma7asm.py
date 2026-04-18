#!/usr/bin/env python3
"""
SDS/Xerox Sigma 7 Assembler
Output: $readmemh compatible hex file (word addressed)

Instruction formats:
  Memory-reference:  OP  R, X, addr[,I]   (I=1 for indirect)
  Immediate:         OP  R, imm
  Branch:            BCR R, addr[,X]
  No-operand:        LCFI

Directives:
  ORG  expr          set location counter (word address)
  DC   expr          define constant word
  DS   n             define storage (n words, zero filled)
  EQU  name, expr    define symbol
  END                end of source

Expressions:
  Decimal:    42, -1
  Hex:        0x1A
  Symbol:     LABEL
  BA(expr):   byte address of word address (expr << 2)
  Arithmetic: expr + expr, expr - expr (simple left-to-right)
"""

import re
import sys
import argparse

# ---------------------------------------------------------------------------
# Opcodes
# ---------------------------------------------------------------------------
OPCODES = {
    # Immediate (fa_imm)
    'LCFI': (0x02, 'imm'),
    'AI':   (0x20, 'imm'),
    'CI':   (0x21, 'imm'),
    'LI':   (0x22, 'imm'),
    # Memory-reference word
    'AW':   (0x30, 'mem'),
    'CW':   (0x31, 'mem'),
    'LW':   (0x32, 'mem'),
    'STW':  (0x35, 'mem'),
    'SW':   (0x38, 'mem'),
    # Memory-reference halfword
    'AH':   (0x50, 'mem'),
    'CH':   (0x51, 'mem'),
    'LH':   (0x52, 'mem'),
    'STH':  (0x55, 'mem'),
    'SH':   (0x58, 'mem'),
    # Logical
    'EOR':  (0x48, 'mem'),
    'OR':   (0x49, 'mem'),
    'AND':  (0x4B, 'mem'),
    # Memory-reference byte
    'LB':   (0x72, 'mem'),
    'STB':  (0x75, 'mem'),
    # Branch
    'BCR':  (0x68, 'branch'),
    'BCS':  (0x69, 'branch'),
    'BAL':  (0x6A, 'branch'),
    # Shift
    'S':    (0x25, 'mem'),
    # Push-down stack (doubleword-addressed)
    'PLW':  (0x08, 'mem'),
    'PSW':  (0x09, 'mem'),
    # Direct I/O
    'RD':   (0x6C, 'mem'),
    'WD':   (0x6D, 'mem'),
}

# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------
def tokenise(line):
    """Strip comments, split on whitespace/commas (preserving quoted strings)."""
    line = re.sub(r';.*', '', line)
    if line.strip().startswith('*'):
        return []
    # Tokenise respecting quoted strings
    tokens = []
    pattern = re.compile(r"""'[^']*'|"[^"]*"|[^\s,]+""")
    for m in pattern.finditer(line):
        tokens.append(m.group())
    return tokens

# ---------------------------------------------------------------------------
# Expression evaluator
# ---------------------------------------------------------------------------
def eval_expr(expr, symbols, loc):
    """Evaluate an expression: number, symbol, BA(expr), or simple arithmetic."""
    expr = expr.strip()

    # BA(expr) — byte address of word address
    m = re.fullmatch(r'BA\((.+)\)', expr, re.IGNORECASE)
    if m:
        return eval_expr(m.group(1), symbols, loc) << 2

    # Current location counter
    if expr == '*':
        return loc

    # Hex literal
    if re.fullmatch(r'0[xX][0-9a-fA-F]+', expr):
        return int(expr, 16)

    # Decimal literal (including negative)
    if re.fullmatch(r'-?[0-9]+', expr):
        return int(expr)

    # Simple binary arithmetic (left-to-right, + and - only)
    # Split on + or - not at the start
    m = re.search(r'(?<=.)([+\-])', expr)
    if m:
        left  = eval_expr(expr[:m.start(1)], symbols, loc)
        op    = m.group(1)
        right = eval_expr(expr[m.end(1):], symbols, loc)
        return left + right if op == '+' else left - right

    # Symbol
    if expr in symbols:
        return symbols[expr]

    raise ValueError(f"Unknown symbol or expression: {expr!r}")

# ---------------------------------------------------------------------------
# Instruction encoder
# ---------------------------------------------------------------------------
def encode_mem(opcode, r, x, addr, i):
    """Encode a memory-reference instruction."""
    r    = r    & 0x0F
    x    = x    & 0x07
    addr = addr & 0x1FFFF
    i    = i    & 0x01
    return (i << 31) | (opcode << 24) | (r << 20) | (x << 17) | addr

def encode_imm(opcode, r, imm):
    """Encode an immediate instruction."""
    r   = r   & 0x0F
    imm = imm & 0xFFFFF
    return (opcode << 24) | (r << 20) | imm

# ---------------------------------------------------------------------------
# Parse operand fields
# ---------------------------------------------------------------------------
def parse_r(tok):
    """Parse register field: R0-R15 or 0-15."""
    tok = tok.upper().lstrip('R')
    return int(tok)

def parse_operands_mem(operands, symbols, loc):
    """Parse memory-reference operands: R [X] addr [I]"""
    parts = list(operands)
    r = parse_r(parts[0])
    x = 0
    i = 0

    rest = parts[1:]

    # Check for trailing indirect flag
    if rest and rest[-1].upper() in ('1', 'I'):
        i = 1
        rest = rest[:-1]

    if len(rest) == 1:
        addr = eval_expr(rest[0], symbols, loc)
    elif len(rest) == 2:
        # X, addr or addr, X — X is a small integer or Rn
        try:
            x    = int(rest[0].lstrip('Rr'))
            addr = eval_expr(rest[1], symbols, loc)
        except (ValueError, KeyError):
            addr = eval_expr(rest[0], symbols, loc)
            x    = int(rest[1].lstrip('Rr'))
    else:
        addr = 0

    return r, x, addr, i

def parse_operands_imm(operands, symbols, loc):
    """Parse immediate operands: R imm"""
    parts = list(operands)
    r   = parse_r(parts[0])
    imm = eval_expr(parts[1], symbols, loc)
    return r, imm

def parse_operands_branch(operands, symbols, loc):
    """Parse branch operands: R addr [X]"""
    parts = list(operands)
    r    = parse_r(parts[0])
    addr = eval_expr(parts[1], symbols, loc)
    x    = int(parts[2].lstrip('Rr')) if len(parts) > 2 else 0
    return r, x, addr

# ---------------------------------------------------------------------------
# Assembler passes
# ---------------------------------------------------------------------------
def assemble(lines):
    symbols = {}
    # Two passes
    for pass_num in range(1, 3):
        loc     = 0
        output  = []   # list of (word_addr, word_value)

        for lineno, raw_line in enumerate(lines, 1):
            tokens = tokenise(raw_line)
            if not tokens:
                continue

            # Label detection
            label   = None
            DIRECTIVES = {'ORG','DC','DS','DB','EQU','END'}
            if tokens[0].endswith(':'):
                label = tokens[0][:-1].upper()
                tokens = tokens[1:]
            elif tokens[0].upper() not in OPCODES and \
                 tokens[0].upper() not in DIRECTIVES:
                # Label without colon (not an opcode or directive)
                label = tokens[0].upper()
                tokens = tokens[1:]

            if label and pass_num == 1:
                symbols[label] = loc

            if not tokens:
                continue

            mnemonic = tokens[0].upper()
            operands = tokens[1:]

            # Directives
            if mnemonic == 'END':
                break

            elif mnemonic == 'ORG':
                loc = eval_expr(operands[0], symbols, loc)
                continue

            elif mnemonic == 'EQU':
                # Support: label EQU value  OR  EQU name value
                if label:
                    name = label
                    val_expr = operands[0]
                else:
                    name = operands[0].upper()
                    val_expr = operands[1]
                try:
                    val = eval_expr(val_expr, symbols, loc)
                except:
                    val = 0
                if pass_num == 1:
                    symbols[name] = val
                continue

            elif mnemonic == 'DC':
                val = (eval_expr(operands[0], symbols, loc) & 0xFFFFFFFF) if pass_num == 2 else 0
                if pass_num == 2:
                    output.append((loc, val))
                loc += 1
                continue

            elif mnemonic == 'DB':
                # Define bytes — pack into words, zero-pad to word boundary
                # Operands: string literal 'text' (no auto-null) or byte values
                raw = ' '.join(operands)
                bytes_list = []
                if raw.startswith("'") or raw.startswith('"'):
                    # String literal — process Python-style escape sequences
                    delim = raw[0]
                    text  = raw[1:raw.rindex(delim)]
                    # Decode escape sequences
                    text = text.replace('\\r', '\r').replace('\\n', '\n') \
                               .replace('\\t', '\t').replace('\\0', '\0') \
                               .replace('\\\\', '\\')
                    bytes_list = [ord(c) for c in text]  # no auto-null
                else:
                    # Space-separated byte values
                    for op in operands:
                        bytes_list.append(eval_expr(op, symbols, loc) if pass_num == 2 else 0)
                # Zero-pad to word boundary
                while len(bytes_list) % 4 != 0:
                    bytes_list.append(0)
                # Pack into words (big-endian)
                for wi in range(0, len(bytes_list), 4):
                    word = ((bytes_list[wi]   & 0xFF) << 24 |
                            (bytes_list[wi+1] & 0xFF) << 16 |
                            (bytes_list[wi+2] & 0xFF) << 8  |
                            (bytes_list[wi+3] & 0xFF))
                    if pass_num == 2:
                        output.append((loc, word))
                    loc += 1
                continue

            elif mnemonic == 'DS':
                count = eval_expr(operands[0], symbols, loc)
                if pass_num == 2:
                    for i in range(count):
                        output.append((loc + i, 0))
                loc += count
                continue

            # Instructions
            if mnemonic not in OPCODES:
                raise SyntaxError(f"Line {lineno}: Unknown mnemonic {mnemonic!r}")

            opcode, fmt = OPCODES[mnemonic]

            if fmt == 'imm':
                if mnemonic == 'LCFI':
                    r, imm = 0, 0
                    if operands:
                        r   = parse_r(operands[0])
                        if len(operands) > 1:
                            imm = eval_expr(operands[1], symbols, loc) if pass_num == 2 else 0
                else:
                    if pass_num == 2:
                        r, imm = parse_operands_imm(operands, symbols, loc)
                    else:
                        r, imm = parse_r(operands[0]), 0
                word = encode_imm(opcode, r, imm)

            elif fmt == 'branch':
                if pass_num == 2:
                    r, x, addr = parse_operands_branch(operands, symbols, loc)
                else:
                    r, x, addr = parse_r(operands[0]), 0, 0
                word = encode_mem(opcode, r, x, addr, 0)

            else:  # mem
                if pass_num == 2:
                    r, x, addr, i = parse_operands_mem(operands, symbols, loc)
                else:
                    r, x, addr, i = parse_r(operands[0]), 0, 0, 0
                word = encode_mem(opcode, r, x, addr, i)

            if pass_num == 2:
                output.append((loc, word))
            loc += 1

    return output, symbols

# ---------------------------------------------------------------------------
# Output writer
# ---------------------------------------------------------------------------
def write_memh(output, outfile):
    """Write $readmemh format: @addr then hex words."""
    prev_addr = None
    with open(outfile, 'w') as f:
        for addr, word in sorted(output):
            if addr != prev_addr:
                f.write(f'@{addr:05X}\n')
            f.write(f'{word:08X}\n')
            prev_addr = addr + 1

def write_listing(output, symbols, lines, outfile):
    """Write a human-readable listing."""
    addr_to_word = dict(output)
    sym_by_addr  = {}
    for name, addr in symbols.items():
        sym_by_addr.setdefault(addr, []).append(name)

    with open(outfile, 'w') as f:
        f.write(f"{'Addr':>6}  {'Word':>8}  {'Label':<12} Source\n")
        f.write('-' * 60 + '\n')
        loc = 0
        for raw_line in lines:
            tokens = tokenise(raw_line)
            # Print address and word for instruction/data lines
            f.write(f'{raw_line.rstrip()}\n')

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description='Sigma 7 Assembler')
    parser.add_argument('input',             help='Assembly source file')
    parser.add_argument('-o', '--output',    help='Output hex file', default=None)
    parser.add_argument('-l', '--listing',   help='Listing file',    default=None)
    parser.add_argument('-s', '--symbols',   action='store_true',    help='Print symbol table')
    args = parser.parse_args()

    with open(args.input) as f:
        lines = f.readlines()

    try:
        output, symbols = assemble(lines)
    except (ValueError, SyntaxError) as e:
        print(f'Error: {e}', file=sys.stderr)
        sys.exit(1)

    # Default output filename
    outfile = args.output or args.input.rsplit('.', 1)[0] + '.hex'
    write_memh(output, outfile)
    print(f'Assembled {len(output)} words → {outfile}')

    if args.symbols:
        print('\nSymbol table:')
        for name, addr in sorted(symbols.items()):
            print(f'  {name:<20} = {addr:05X}')

    if args.listing:
        write_listing(output, symbols, lines, args.listing)

if __name__ == '__main__':
    main()