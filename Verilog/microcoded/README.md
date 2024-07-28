
# Microcode Sequencer

![Sequencer](images/sequencer.png)

A general purpose microcode sequencer in Verilog influenced by the [Am2911](https://bitsavers.org/components/amd/bitslice/1978_The_Am2900_Family_Data_Book.pdf) bit slice sequencer described in [Bit-Slice Microprocessor Design](https://bitsavers.org/components/amd/bitslice/Mick_Bit-Slice_Microprocessor_Design_1980.pdf) by John Mick and Jim Brick.

There are a few differences in this design:

* Scalable design, rather than a series of bit-slices
* Built in adder to support relative branching

## High Level Compiler

Historically, writing microcode was one step below assembly language programming. High level flow control structures, such as if/else, do/while loops, and procedure would simplify the process. To this end, a compiler translates these flow control structures into microcode.
