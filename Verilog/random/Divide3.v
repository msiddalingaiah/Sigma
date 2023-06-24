
// Single cycle, unsigned non-restoring integer divide

/*

It compiles and simulates in Icarus Verilog:

$ iverilog -o Divide3 Divide3.v
$ vvp Divide3

This is the equivalent algorithm in Python:

def non_restoring_divide2(numerator, denominator, num_bits=8):
  C = denominator
  n = num_bits

  lo_word_mask = ~(-1 << n)

  A = numerator << 1
  B = 0
  C_shift = C << n
  C_comp = (~C & lo_word_mask) << n

  sign = (A >> (n+n)) & 1
  if sign == 1:
    D = C_shift
    c_in = 0
  else:
    D = C_comp
    c_in = 1 << n

  for i in range(n):
    s = A + D + c_in
    # last cycle, no shift avoids extra shift after loop
    if i == n-1:
      A = s
    else:
      A = s << 1
    B = (B<<1) | ~sign & 1
    sign = (s >> (n+n-1)) & 1
    if sign == 1:
      D = C_shift
      c_in = 0
    else:
      D = C_comp
      c_in = 1 << n

  # Simplification of B = B - (~B) quotient and remainder restoration
  B = B << 1
  sign = (A >> (n+n-1)) & 1
  if sign:
    A = A + C_shift
  else:
    B = B + 1

  rem = (A >> n) & lo_word_mask
  quotient = B & lo_word_mask
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
    reg lsb;

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
            done <= 1;
        end else begin
            case (phase)
                0: if (start == 1) begin
                    a <= numerator[1:`WIDTH];
                    b <= { numerator[`WIDTH+1:`WIDTH*2-1], 1'b0 };
                    c <= denominator;
                    // Start with sign == 0
                    d <= ~denominator;
                    cs <= `WIDTH'h1;
                    lsb <= 1;
                    count <= `WIDTH-2;
                    done <= 0;
                    phase <= 1;
                end
                1: begin // division iteration loop
                    $display("count: %d, a:b %x:%x, d: %x, cs: %x", count, a, b, d, cs);
                    a <= { s[1:`WIDTH-1], b[0] };
                    b <= { b[1:`WIDTH-1], lsb };
                    if (s[0] == 0) begin
                        d <= ~c;
                        cs <= `WIDTH'h1;
                        lsb <= 1;
                    end else begin
                        d <= c;
                        cs <= 0;
                        lsb <= 0;
                    end
                    count <= count - 1;
                    if (count == 0) phase <= 2;
                end
                2: begin // last iteration
                    $display("count:  -1, a:b %x:%x, d: %x, cs: %x", a, b, d, cs);
                    a <= { s[0:`WIDTH-1] };
                    b <= { b[2:`WIDTH-1], lsb, ~s[0] };
                    d <= 0;
                    cs <= 0;
                    if (s[0] == 1) begin
                        d <= c;
                    end
                    phase <= 3;
                end
                3: begin // result
                    //$display("result, a:b %x:%x, d: %x, cs: %x", a, b, d, cs);
                    remainder <= s;
                    quotient <= b;
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

        start = 0;
        #25 reset=1; #100; reset=0;


        // [[3550, 113], [3550, 112], [3550, 114], [100, 15], [100, 16], [100, 17]]
        numerator = 7; denominator = 2; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder));
        /*
        numerator = 3550; denominator = 113; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder));
        numerator = 3550; denominator = 112; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder));
        numerator = 3550; denominator = 114; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder));

        numerator = 3550000000; denominator = 113; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder));
        numerator = 35500000; denominator = 112; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder));
        numerator = 35500000; denominator = 114; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder));

        numerator = 100; denominator = 17; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder));
        numerator = 100; denominator = 16; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder));
        numerator = 100; denominator = 15; start = 1; #200 start = 0; #4000;
        $display("%d/%d, => %d, r%d, %d==0", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder));
        */
        $finish;
    end
endmodule
