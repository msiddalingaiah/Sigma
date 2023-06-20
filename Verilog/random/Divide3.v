
// Work in progress...

/*

def single_cycle_divide(numerator, denominator, num_bits=4):
  C = denominator # denominator / divisor
  n = num_bits # number of bits

  C_sign_shift = n-1
  S_carry_shift = n + n
  low_mask = ~(-1 << n)
  high_mask = low_mask << n
  high_low_mask = high_mask | low_mask
  #print(f'{high_mask:x}, {low_mask:x}, {high_low_mask:x}')

  A = (numerator << 1) & high_low_mask
  C_shift = C << n
  C_comp = ((~C_shift) & 0xf0)
  K00 = 1 - (A >> (S_carry_shift-1) & 1) # A already shifted, so use S_carry_shift
  MWN = (C >> C_sign_shift) & 1
  D = 0
  CS31 = 0

  for i in range(0, n):
    if MWN ^ K00 != 0:
      D = C_comp
      CS31 = 1 << n
    else:
      D = C_shift
      CS31 = 0
    S = A + D + CS31
    K00 = (S >> S_carry_shift) & 1
    #print(f'{i+1}: A {A:02x}, D {(D):02x}, CS31 {CS31:02x}, S {(S)&0x1ff:03x}, K00 {K00}')
    # 3-329: last iteration, AXSL1 = False, e.g. don't shift sum, shift B (low word)
    if (i+1 == n):
      A = (S & high_mask) | ((S << 1) & low_mask)
    else:
      A = ((S << 1) | K00) & high_low_mask

  #print(f'end: S {S:03x}, A {A:02x}')

  # TODO: 3-336: quotient/remainder adjustment
  rem = (A >> n) & low_mask
  quotient = (A & low_mask) + 1

  return quotient, rem

 */

`define WIDTH 32

module Divide3 (
    input clock,
    input reset,
    input start,
    input [0:2*`WIDTH-1] numerator,
    input [0:`WIDTH-1] denominator,
    output reg [0:`WIDTH-1] quotient,
    output reg [0:`WIDTH-1] remainder,
    output reg done);

    reg [0:3] phase;
    reg [0:7] count;
    reg [0:`WIDTH-1] a, b, c, d;
    reg [0:`WIDTH-1] cs;
    wire [0:`WIDTH-1] s = carry_sum[1:`WIDTH];
    reg [0:`WIDTH] carry_sum;
    reg rn, mwn, sw3;

    wire k00 = carry_sum[0];
    wire a0031Z = a == 0;

    always @(*) begin
        carry_sum = { 1'b0, a } + { 1'b0, d } + { 1'b0, cs };
    end

    always @(posedge clock, posedge reset) begin
        if (reset) begin
            phase <= 0;
            count <= 0;
            a <= 0;
            b <= 0;
            c <= 0;
            d <= 0;
            cs <= 0;
            sw3 <= 0;
            done <= 1;
        end else begin
            case (phase)
                0: if (start == 1) begin
                    a <= numerator[0:`WIDTH-1];
                    b <= numerator[`WIDTH:`WIDTH*2-1];
                    c <= denominator;
                    d <= 0;
                    cs <= 0;
                    rn <= numerator[0];
                    mwn <= denominator[0];
                    sw3 <= 0;
                    done <= 0;
                    phase <= 1;
                end
                1: begin // setup prior to division iteration loop
                    //$display("  %d: a = %x", count, { a[14:0] | { 13'h0, lsb }, 1'b0 });
                    a <= { a[1:`WIDTH-1], b[0] };
                    b <= { b[1:`WIDTH-1], 1'b0 };
                    if (rn ^ mwn) begin
                        d <= c;
                        cs <= 0;
                    end else begin
                        d <= ~c;
                        cs <= `WIDTH'h1;
                    end
                    count <= `WIDTH-2;
                    phase <= 2;
                end
                2: begin // division iteration loop
                    // $display("count: %d, a:b %x:%x, k00: %d, d: %x, cs: %x", count, a, b, k00, d, cs);
                    a <= { s[1:`WIDTH-1], b[0] };
                    b <= { b[1:`WIDTH-1], k00 };
                    if (mwn ^ k00) begin
                        d <= ~c;
                        cs <= `WIDTH'h1;
                    end else begin
                        d <= c;
                        cs <= 0;
                    end
                    if (a0031Z && rn) sw3 <= 1;
                    count <= count - 1;
                    if (count == 0) phase <= 3;
                end
                3: begin // post loop a/b update
                    // $display("exit, a:b %x:%x, k00: %d, d: %x, cs: %x", a, b, k00, d, cs);
                    a <= s;
                    b <= { b[1:`WIDTH-1], k00 };
                    if (a0031Z && rn) sw3 <= 1;
                    phase <= 4;
                end
                4: begin // remainder restoration, see 3-333
                    // $display("end: a:b %x:%x", a, b);
                    // case 1, quotient and residue have same sign, reside is true remainder
                    if (((rn ^ d[0]) & ~sw3)) begin
                        remainder <= a;
                    end
                    // case 2: quotient and residue have like signs, zero residue was achieved, S = 0
                    // case 3: quotient and residue have unlike signs, residue = 0, S = 0
                    // case 4: quotient and residue have unlike signs, residue != 0
                    if (~(rn ^ d[0]) & ~a0031Z) begin
                        remainder <= s; // doesn't seem to work properly
                    end
                    remainder <= a; // temporary fix...
                    phase <= 5;
                end
                5: begin // quotient adjustment
                    if ((~rn & mwn) | (rn & ~mwn & ~a0031Z) | (rn & mwn & a0031Z)) begin
                        quotient <= b + 1;
                    end else begin
                        quotient <= b;
                    end
                    done <= 1;
                    phase <= 0;
                end
                default: phase <= 0;
            endcase
        end
    end
endmodule

`timescale 1ns / 1ns
module tb_divider;
    // Inputs
    reg clock;
    reg reset;
    reg start;
    reg [0:2*`WIDTH-1] numerator;
    reg [0:`WIDTH-1] denominator;
    // Outputs
    wire [0:`WIDTH-1] quotient;
    wire [0:`WIDTH-1] remainder;
    wire done;

    // Instantiate the Unit Under Test (UUT)
    Divide3 uut (
        .clock(clock),
        .start(start),
        .reset(reset),
        .numerator(numerator),
        .denominator(denominator),
        .quotient(quotient),
        .remainder(remainder),
        .done(ok)
    );
    initial begin
        clock = 0;
        forever #50 clock = ~clock;
    end
    initial begin
        $dumpfile("vcd/Divide3.vcd");
        $dumpvars(0, uut);

        // Initialize Inputs
        start = 0;
        reset=1;
        // Wait 100 ns for global reset to finish
        #1000;
        reset=0;

        // [[3550, 113], [3550, 112], [3550, 114], [100, 15], [100, 16], [100, 17]]
        numerator = 3550; denominator = 113; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0, %d, %d, %d, %d", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder), uut.rn, uut.mwn, uut.sw3, uut.a0031Z);
        numerator = 3550; denominator = 112; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0, %d, %d, %d, %d", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder), uut.rn, uut.mwn, uut.sw3, uut.a0031Z);
        numerator = 3550; denominator = 114; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0, %d, %d, %d, %d", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder), uut.rn, uut.mwn, uut.sw3, uut.a0031Z);

        numerator = 35500; denominator = 113; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0, %d, %d, %d, %d", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder), uut.rn, uut.mwn, uut.sw3, uut.a0031Z);
        numerator = 35500; denominator = 112; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0, %d, %d, %d, %d", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder), uut.rn, uut.mwn, uut.sw3, uut.a0031Z);
        numerator = 35500; denominator = 114; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0, %d, %d, %d, %d", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder), uut.rn, uut.mwn, uut.sw3, uut.a0031Z);

        numerator = 100; denominator = 17; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0, %d, %d, %d, %d", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder), uut.rn, uut.mwn, uut.sw3, uut.a0031Z);
        numerator = 100; denominator = 16; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0, %d, %d, %d, %d", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder), uut.rn, uut.mwn, uut.sw3, uut.a0031Z);
        numerator = 100; denominator = 15; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0, %d, %d, %d, %d", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder), uut.rn, uut.mwn, uut.sw3, uut.a0031Z);
        $finish;
    end
endmodule
