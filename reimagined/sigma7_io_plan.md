# SDS/Xerox Sigma 7 — Minimal I/O and Monitor Plan

## Overview

This document describes the plan for implementing a minimal I/O subsystem and
monitor program for the Sigma 7 RTL implementation. The goal is a working
interactive system capable of running on both Icarus Verilog simulation and a
Lattice ICE40 FPGA.

---

## I/O Architecture

### RD and WD Instructions

The Sigma 7 supports direct I/O via the RD (Read Direct, opcode 0x6C) and WD
(Write Direct, opcode 0x6D) instructions. These use the standard
memory-reference addressing mode (direct, indexed, indirect) to specify a
device address, and transfer data directly between a user register and an I/O
device — bypassing the memory system entirely.

Instruction format is identical to LW/STW:

```
| I(1) | opcode(7) | R(4) | X(3) | DeviceAddr(17) |
```

RD reads 32 bits from the device into RR[r]. WD writes RR[r] to the device.
For character I/O, data appears in the least significant byte (bits 24:31 in
big-endian notation).

Phase sequence mirrors LW (for RD) and STW (for WD) — PREP1→PREP3 resolves
the device address into P, then EX phases perform the transfer. The CPU asserts
an `io_select` signal during EX phases to distinguish I/O from memory
transactions.

Address family decode: opcodes 0x6C and 0x6D fall into **fa_w** (word
addressing), so they use standard word-aligned EA calculation with optional
indexing and indirection.

### Bus Architecture

A separate `io_select` signal from the CPU indicates that the current bus
transaction targets an I/O device rather than memory. The system module routes
the transaction accordingly:

- `io_select = 0`: transaction goes to Memory module
- `io_select = 1`: transaction goes to I/O device decoder

The device address is carried in the lower bits of `bus_addr`. The I/O decoder
maps device addresses to individual device modules.

---

## Console Device

### Device Addresses

| Address | Register        | Description                              |
|---------|-----------------|------------------------------------------|
| 0x1001  | Console data    | RD reads character; WD writes character  |
| 0x1002  | Console status  | Read-only status register                |

These addresses fall in the unassigned I/O region of the Sigma 7 address map.

### Data Register (0x1001)

**RD from 0x1001:** Returns 32 bits. Character appears in bits 24:31 (least
significant byte, big-endian). Bits 0:23 are zero. If no character is
available, returns zero.

**WD to 0x1001:** Writes the character in bits 24:31 to the console output.
Bits 0:23 are ignored.

### Status Register (0x1002)

Read-only. Reflects device readiness:

```
bits 0:29  — reserved, always 0
bit  30    — TX ready (1 = console can accept output; always 1 in simulation)
bit  31    — RX ready (1 = character available to read)
```

Note: bit 31 is the LSB in Sigma 7 big-endian notation.

A typical console input polling loop:

```
poll:  RD   R1, 0x1002     ; read status
       AND  R1, status_mask ; isolate RX ready bit
       BCR  R1, poll        ; branch if not ready (CC=0)
       RD   R1, 0x1001      ; read character into R1[24:31]
```

---

## Verilog Implementation

### Simulation Console (Icarus Verilog)

The simulation console uses Verilog system tasks for character I/O:

**Input (`$fgetc`):** `$fgetc` blocks until a character is available on stdin.
To avoid stalling the simulation clock, it runs in a separate `initial` block
concurrently with the clocked logic. A 1-character buffer holds the received
byte and a `rx_ready` flag indicates availability:

```verilog
reg        rx_ready;
reg [7:0]  rx_data;

initial begin
    rx_ready = 1'b0;
    forever begin
        rx_data  = $fgetc('h80000000);  // block on stdin
        rx_ready = 1'b1;
        @(posedge rx_read);             // wait for CPU to consume character
        rx_ready = 1'b0;
    end
end
```

The `rx_read` strobe is asserted by the CPU for one cycle when it executes
RD from address 0x1001, signaling to the `initial` block that the character
has been consumed and it can wait for the next one.

**Output (`$fputc`):** Output is immediate — WD to address 0x1001 calls
`$fputc` directly. No buffering needed since stdout is always ready.

**Status register:** Reflects `rx_ready` and constant `tx_ready=1`:

```verilog
assign console_status = {29'b0, 1'b1, rx_ready};
// bit 31 (LSB) = rx_ready, bit 30 = tx_ready
```

### Hardware Console (ICE40 FPGA)

On ICE40 hardware, the simulation `initial` block is replaced by a standard
UART receiver/transmitter:

- **UART RX:** Receives serial characters, stores in a small FIFO, asserts
  `rx_ready` when data is available
- **UART TX:** Accepts characters from WD, serialises at the configured baud
  rate, deasserts `tx_ready` while transmitting
- **Baud rate:** 115200 recommended for ICE40 at typical clock frequencies

The same status register interface is preserved, so monitor software runs
identically in simulation and on hardware.

---

## Instruction Implementation Plan

### RD (Read Direct, 0x6C)

Phase sequence mirrors LW — PREP1→PREP3 resolves device address, then:

```
PREP1-3: DeviceAddr → P; io_select=1
EX1:     io_data_r → C; A ← C_mux         ; read from device
EX2:     RR[r] ← A; CC ← CC_ARITH(A)
         Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX3/ENDE:
```

### WD (Write Direct, 0x6D)

Phase sequence mirrors STW:

```
PREP1-3: DeviceAddr → P; io_select=1
EX1:     A ← RR[r]
EX2:     io_data_w ← A; io_write=1         ; write to device (bus busy)
EX3:     Q_sel; P_sel←P_Q; bus_addr←{Q,00}
EX4/ENDE:
```

---

## Minimal Monitor Program

The monitor is a small program written in Sigma 7 assembly (or machine code)
that runs on the CPU and provides interactive access via the console. It serves
as the foundation for more sophisticated software.

### Proposed Features

**Memory examine:** Display the contents of a memory address or range in hex.

**Memory deposit:** Write a value to a memory address.

**Register display:** Show the contents of all user registers and CC.

**Execute:** Transfer control to a user-specified address.

**Load:** Accept a simple binary or hex format record stream via the console
(S-records or a custom format) and load it into memory.

**Minimal arithmetic/assembler:** Evaluate simple expressions for convenience.

### Command Format

A simple line-oriented command interface:

```
? addr              examine word at addr
! addr value        deposit value at addr
R                   display registers
G addr              go (execute) at addr
L                   load (enter load mode, receive records)
```

### Console I/O Primitives

The monitor would be built on three low-level primitives:

- `GETCHAR`: Poll status register until RX ready, then RD from console data
- `PUTCHAR`: Poll status register until TX ready, then WD to console data
- `PUTS`: Call PUTCHAR for each character of a null-terminated string

---

## Development Sequence

1. ~~**Implement RD and WD**~~ ✓ — CPU Verilog with `io_select` signal
2. ~~**Implement Console module**~~ ✓ — simulation version using `$fwrite`/`$fgetc`
3. ~~**Wire into Sigma7System**~~ ✓ — I/O decoder alongside memory
4. ~~**Write Python assembler**~~ ✓ — `sigma7asm.py` with two-pass assembly
5. ~~**Write and test banner program**~~ ✓ — "Sigma 7 Monitor" printed and verified
6. **Write GETCHAR/PUTCHAR/PUTS primitives** — in Sigma 7 assembly (PUTS implemented in banner)
7. **Write the monitor command loop** — read line, parse, dispatch
8. **Self-checking tests** — programs that verify instruction correctness via console
9. **ICE40 port** — replace simulation console with UART RTL, synthesize

---

## ICE40 Resource Considerations

The iCE40HX8K or UP5K have sufficient resources for a minimal implementation:

- **Logic:** The Sigma 7 CPU is relatively compact — one-hot phase register,
  simple ALU, register file. Should fit comfortably within ICE40 LUT budget.
- **Memory:** ICE40 block RAMs (EBRs) provide 4KB each. The UP5K has 128KB
  SPRAM in addition. A minimal system with 32–64KB of memory is feasible.
- **I/O:** UART RX/TX fits easily. The FTDI USB-serial on most ICE40 boards
  provides the console connection.
- **Clock:** 12MHz or 48MHz depending on board. UART baud rate divider
  designed accordingly.

The key constraint is memory size. A minimal monitor fits in a few KB; the
question is how much RAM to provide for user programs. 32KB is a reasonable
starting point for the ICE40 UP5K using its SPRAM.

---

## Open Questions

1. Should the monitor be stored in ROM (block RAM initialised at synthesis) or
   loaded via the testbench/UART at startup?
2. What record format should the loader accept — standard Motorola S-records,
   Intel HEX, or a simpler custom format?
3. Should CC be set by RD based on the value read (consistent with LW
   behaviour), or left unchanged?
4. Are there other device addresses we should reserve for future peripherals
   (e.g. timer, interrupt controller)?