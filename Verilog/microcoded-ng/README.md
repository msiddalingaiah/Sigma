
# License

MIT License

Copyright (c) 2025 Madhu Siddalingaiah

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

# Microcode NG Sigma 7

This is a microcoded implementation of the Sigma 7 CPU. Registers and datapath of the original CPU are preserved.
Cycle accuracy is not guaranteed. The original Sigma 7 used a hardwired control unit based on DTL SSI logic.
Scientific Data Systems (SDS) was one of the first computer companies to use silicon transistors for all logic circuits.

![Sigma 7 Registers](images/sig7_registers.png)

* A - ALU input and general computation register (32 bits)
* B - Appended to A to form a 64 bit register during multiply/divide instructions (32 bits)
* C - Memory data input, transparent latch to reduce cycles (32 bits)
* D - ALU input (32 bits)
* E - Counter (8 bits)
* CC - Condition codes (4 bits)
* CS - Carry save (32 bits)
* O - Opcode register (7 bits)
* P - Byte address and counter register (19 bits)
* Q - Program word address register (17 bits)
* R - General purpose (R0-R15) register index (4 bits)

The ALU performs basic arithmetic and logical 32-bit operations, such as addition, negation, and, or, exclusive or. Multiply and divide are implemented using bit pair multiplication and non-restoring division. Bit shifts are perform in single and four bit increments.

All instructions are 32-bit fixed width. Indirect and indexed addressing modes are supported. General purpose registers
occupy word memory locations 0-15.

Instruction fetch overlaps with the last cycle of the previous instruction (ENDE). The Q register holds the next instruction word
address. During instruction fetch, the following operations are performed:

* Q is transferred to P, P is incremented by 1 word
* C is loaded with the next instruction
* Opcode O and register index R are loaded from C
* D is loaded with the contents of C

The PREP phase performs instruction decoding. At the end of PREP, prior to individual instruction execution, the following
registers are populated:

* Q contains the next instruction word address
* P is loaded with the effective byte address of the operand
* D contains the instruction or effective word

Upon reset, the Q register is loaded with word location 0x25, and the C register is loaded with 0x02000000. ENDE is asserted,
resulting the execution of the no-operation instruction LCFI, 0 0 in the C register. The first consequential instruction
is loaded from word address 0x26, which contains a four instruction boot sequence:

```
    LW,0        0x24       ; Loads the contents of location X'24' (X'11') containing the address of the I/O unit
    SIO,0       *0x25      ; Indirectly-addressed Start Input/Output instruction.
    TIO,0       *0x25      ; Indirectly-addressed Test Input/Output instruction
    BCS,12      0x28       ; Loop until I/O complete. Program execution continues at next instruction address at 0x2A
```

# Microcode Sequencer

![Sequencer](images/sequencer.png)

This directory contains a general purpose microcode sequencer in Verilog influenced by the [Am2911](https://bitsavers.org/components/amd/bitslice/1978_The_Am2900_Family_Data_Book.pdf) bit slice sequencer described in [Bit-Slice Microprocessor Design](https://bitsavers.org/components/amd/bitslice/Mick_Bit-Slice_Microprocessor_Design_1980.pdf) by John Mick and Jim Brick.

There are a few differences in this design:

* Scalable design, rather than a series of bit-slices
* Built in adder to support relative only branching (position independent code)

## Microprogramming

[Hardwired CPU control units](https://en.wikipedia.org/wiki/Control_unit#Hardwired_control_unit) can execute optimally, but their design, implementation, and modification can be time consuming and difficult to maintain. Hardwired control units are designed as a combinational circuit and a state machine. The state machine can take the form of either a [Moore](https://en.wikipedia.org/wiki/Moore_machine) or [Mealy](https://en.wikipedia.org/wiki/Mealy_machine) machine. Each CPU instruction might require as many 16 or more states, depending on the complexity of an instruction.

Prof. [M. V. Wilkes](https://en.wikipedia.org/wiki/Maurice_Wilkes) of the Cambridge University Mathematical Laboratory coined the term microprogramming in 1951. He provided a systematic [alternative procedure](https://people.eecs.berkeley.edu/~culler/courses/cs252-s05/papers/wilkes52.pdf) for designing the control unit of a digital computer. During instruction execution, a sequence of transformations and register transfers take place. These were called the micro operations. Because of the analogy between the execution of individual steps in a machine instruction to the execution of the individual instruction in a program, Wilkes introduced the concept of microprogramming. The Wilkes control unit replaced the sequential and combinational circuits of a [hardwired control unit](https://en.wikipedia.org/wiki/Control_unit#Hardwired_control_unit) with a programmable control unit in conjunction with a storage unit that stores the sequence of steps of instruction that is a micro-program.

## High Level Compiler

Historically, writing microcode was one step below assembly language programming. High level flow control structures, such as if/else, do/while loops, switch statements, and procedures would simplify the coding process. To this end, a [microcode compiler](roms/Compiler.py) and [microcode generator](roms/Generator.py) translate these flow control structures into microcode.

Below is an example of several operations:
* Subprogram definition (sigma) and call (reset)
* Instruction fetch (ende) is concident with the final microoperation of an instruction
* Intruction decode (prep) preparation label
* Instruction execution (switch)

```
def sigma:
    call reset

    prep: lmx = LMXC, qx = QXP, if COND_OP_INDIRECT:
        cx = CXMB, dx = DXC
    sx = SXADD, px = PXS, switch ADDR_MUX_OPCODE:
    ...
        OP_LW:
            px = PXQ, lmx = LMXC, uc_debug = 1
            cx = CXMB, dx = DXC
            sx = SXD, rrx = RRXS, ax = AXS, lmx = LMXQ
            testa = 1, cx = CXMB, dx = DXC, px = PCTP1, ende = 1, continue prep
```

# Tools

* Python 3
* make (winget install ezwinports.make)
* [OSS Cad Suite](https://github.com/YosysHQ/oss-cad-suite-build) contains pre-built binaries for Windows
* Install [OSS Cad Suite](https://github.com/YosysHQ/oss-cad-suite-build)
* Run ```oss-cad-suite\environment.ps1``` or ```oss-cad-suite\environment.bat``` to set up paths and environment variables

Create the vcd directory if it does not exist:

```
md vcd
```

## TODO

* Test STW
* Instructions, in order: XPSD, LI, CI, CW
* IOPs: card reader, console output
* Test index addressing for byte, halfword, word, and doubleword instructions
* Crossover
