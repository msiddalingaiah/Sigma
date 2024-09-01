
// Bit pair, unsigned integer multiply

/*

It compiles and simulates in Icarus Verilog:

$ iverilog -o vcd/Multiplier Multiplier.v
$ vvp vcd/Multiplier

This is the equivalent algorithm in Python:

def bit_pair_multiply(x, y, num_bits=8):
  C_map = [0, x << num_bits, x << (num_bits+1), (~x) << num_bits]
  CS_map = [0, 0, 0, 1 << num_bits]
  A_B = y
  a_mask = ~(-1 << (num_bits+num_bits))
  n = num_bits >> 1
  bc31 = 0
  if y & 3 == 3:
    bc31 = 1
  D = C_map[y & 3]
  CS = CS_map[y & 3]
  for i in range(n):
    S = A_B + D + CS
    A_B = S >> 2
    bpair = ((S >> 2) & 0x3) + bc31
    bc31 = bpair >> 2
    D = C_map[bpair & 3]
    CS = CS_map[bpair & 3]
  return A_B & a_mask

 */

`define WIDTH 32

module Multiplier (
    input clock,
    input reset,
    input start,
    input [0:`WIDTH-1] multiplier,
    input [0:`WIDTH-1] multiplicand,
    output reg [0:2*`WIDTH-1] result,
    output reg done);

    reg [0:3] phase;
    reg [0:7] count;
    reg [0:`WIDTH-1] a, b, c, d;
    reg [0:`WIDTH-1] cs;
    reg [0:`WIDTH-1] s;
    reg bc31;
    reg [0:2] bpair;

    always @(*) begin
        s = a + d + cs;
        bpair = { 1'b0, b[`WIDTH-4:`WIDTH-3] } + { 2'b00, bc31 };
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
            bc31 <= 0;
            result <= 0;
            done <= 1;
        end else begin
            case (phase)
                0: if (start == 1) begin
                    a <= 0;
                    b <= multiplicand;
                    c <= multiplier;
                    case (multiplicand & 3)
                        0: begin d <= 0; cs <= 0; bc31 <= 0; end
                        1: begin d <= multiplier; cs <= 0; bc31 <= 0; end
                        2: begin d <= { multiplier[1:`WIDTH-1], 1'b0 }; cs <= 0; bc31 <= 0; end
                        3: begin d <= ~multiplier;  cs <= 1; bc31 <= 1; end
                    endcase
                    count <= (`WIDTH >> 1) - 1;
                    done <= 0;
                    phase <= 1;
                end
                1: begin // multiplication iteration loop
                    //$display("count: %d, a:b %x:%x, d: %x, cs: %x, s: %x, bpair: %x, bc31: %x", count, a, b, d, cs, s, bpair, bc31);
                    a <= { {2{s[0]}}, s[0:`WIDTH-3] };
                    b <= { s[`WIDTH-2:`WIDTH-1], b[0:`WIDTH-3] };
                    bc31 <= bpair[0] | (bpair[1] & bpair[2]);
                    case (bpair & 3)
                        0: begin d <= 0; cs <= 0; end
                        1: begin d <= c; cs <= 0; end
                        2: begin d <= { c[1:`WIDTH-1], 1'b0 }; cs <= 0; end
                        3: begin d <= ~c;  cs <= 1; end
                    endcase
                    count <= count - 1;
                    if (count == 0) phase <= 2;
                end
                2: begin // result
                    //$display("a:b %x:%x, d: %x, cs: %x, s: %x, bpair: %x, bc31: %x", count, a, b, d, cs, s, bpair, bc31);
                    result <= { a, b };
                    done <= 1;
                    phase <= 0;
                end
                default: phase <= 0;
            endcase
        end
    end
endmodule

`timescale 1ns / 1ns
module tb_multiplier;
    // Inputs
    reg clock;
    reg reset;
    reg start;
    reg [0:`WIDTH-1] multiplier;
    reg [0:`WIDTH-1] multiplicand;
    // Outputs
    wire [0:2*`WIDTH-1] result;
    wire done;

    Multiplier uut (
        .clock(clock),
        .start(start),
        .reset(reset),
        .multiplier(multiplier),
        .multiplicand(multiplicand),
        .result(result),
        .done(done)
    );
    initial begin
        clock = 0;
        forever #50 clock = ~clock;
    end
    initial begin
        $dumpfile("vcd/Multiplier.vcd");
        $dumpvars(0, uut);

        start = 0;
        #0 reset=0; #25 reset=1; #100; reset=0;

        multiplier = 1; multiplicand = 1; start = 1; #200 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));
        multiplier = 1; multiplicand = 2; start = 1; #200 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));
        multiplier = 1; multiplicand = 3; start = 1; #200 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));

        multiplier = 1; multiplicand = 11; start = 1; #200 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));
        multiplier = 35; multiplicand = 17; start = 1; #200 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));
        multiplier = 17; multiplicand = 35; start = 1; #200 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));
        multiplier = 35; multiplicand = 63; start = 1; #200 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));
        multiplier = 113; multiplicand = 31415; start = 1; #200 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));
        multiplier = 31415; multiplicand = 113; start = 1; #200 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));

        $finish;
    end
endmodule
