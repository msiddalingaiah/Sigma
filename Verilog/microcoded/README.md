
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

# Microcode Sequencer

![Sequencer](images/sequencer.png)

This directory contains a general purpose microcode sequencer in Verilog influenced by the [Am2911](https://bitsavers.org/components/amd/bitslice/1978_The_Am2900_Family_Data_Book.pdf) bit slice sequencer described in [Bit-Slice Microprocessor Design](https://bitsavers.org/components/amd/bitslice/Mick_Bit-Slice_Microprocessor_Design_1980.pdf) by John Mick and Jim Brick.

There are a few differences in this design:

* Scalable design, rather than a series of bit-slices
* Built in adder to support relative only branching (position independent code)

## Microprogramming

Prof. [M. V. Wilkes](https://en.wikipedia.org/wiki/Maurice_Wilkes) of the Cambridge University Mathematical Laboratory coined the term microprogramming in 1951. He provided a systematic [alternative procedure](https://people.eecs.berkeley.edu/~culler/courses/cs252-s05/papers/wilkes52.pdf) for designing the control unit of a digital computer. During instruction executing a machine instruction, a sequence of transformations and transfer of information from one register in the processor to another take place. These were also called the micro operations. Because of the analogy between the execution of individual steps in a machine instruction to the execution of the individual instruction in a program, Wilkes introduced the concept of microprogramming. The Wilkes control unit replaced the sequential and combinational circuits of a [hardwired control unit](https://en.wikipedia.org/wiki/Control_unit#Hardwired_control_unit) by a programmable control unit in conjunction with a storage unit that stores the sequence of steps of instruction that is a micro-program.

Hardwired control units execute efficiently, but their design, implementation, and modification can be time consuming and difficult to maintain. The control unit is designed as a combinational circuit and a state machine. The state machine can take the form of either a [Moore](https://en.wikipedia.org/wiki/Moore_machine) or [Mealy](https://en.wikipedia.org/wiki/Mealy_machine) machine. Each CPU instruction might require as many 16 or more states, corresponding to as many lines of a microprogram.

## High Level Compiler

Historically, writing microcode was one step below assembly language programming. High level flow control structures, such as if/else, do/while loops, switch statements, and procedures would simplify the process. To this end, a compiler translates these flow control structures into microcode.

Below is a snippet of the instruction loop with the Branch on Decrementing Register (BDR) instruction:

```
    ende = 1; # fetch next instruction
    loop {
        sxop = SX_ADD; # Empty slot for indirect address
        direct: ax = AX_RR, qx = QX_P, px = PX_D_INDX, romswitch ADDR_MUX_OPROM "roms/op_switch.txt" {
            ...
            OP_BDR: {
                dx = DX_1;
                sxop = SX_SUB, rrx = RRX_S, if COND_S_GT_ZERO {
                    # take branch
                    ende = 1, if COND_CIN0_EQ_0 continue direct;
                    continue direct;
                }
                # next instruction
                px = PX_Q;
                ende = 1, if COND_CIN0_EQ_0 continue direct;
                continue direct; # microcode branch delay if next instruction is indirect addressed
            }
            ...
        }
        ...
    }
```

Notes
* ax, bx, cx, dx, px, qx etc. control multiplexors to assign respective registers, e.g. qx = QX_P loads q register with p
* loop { ... } is an infinite loop
* romswitch generates a ROM lookup table with branch addresses, each case label must be sequential, starting from zero
* continue label; unconditionally branches to label
* The last cycle of every instruction fetches the next instruction, with a 16.5% improvement for direct addressing

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

Run the test suite using the following command:

```
make run
```

## Debugging

* Enable instruction tracing in CPU.v:

```
`define TRACE_I 1
```

* Microcode tracing:

```
, uc_debug = 1;
```

* Icarus Verilog [interactive mode](https://steveicarus.github.io/iverilog/usage/vvp_debug.html)
* $stop suspends simulation in interactive mode

```
$ make run
> cd CPUTestBench
> cd cpu
> $display a
```

TODO:

* More instructions, e.g. CAL, XPSD
* Fix broken tests
* Check for overlapping field assignments (Generator)
