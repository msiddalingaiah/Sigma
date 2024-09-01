
// Bit pair, unsigned integer multiply

/*

It compiles and simulates in Icarus Verilog:

$ iverilog -o vcd/Multiplier Multiplier.v
$ vvp vcd/Multiplier

Below is the equivalent algorithm in Python.
* A, B form a double word containing the partial product, B initially contains the multiplicand
* For each iteration of half the number of bits:
** Add 0, x, 2x, -x to A, depending on the LSB bit pair of B
** Propagate bit pair carry (bc31) to to the next bit pair
** Shift A:B two bits to the right
* Product is is A:B

def bit_pair_multiply(x, y, num_bits=8):
  C_map = [0, x, x << 1, -x]
  A, B, D = 0, y, C_map[y & 3]
  bc31 = int(y & 3 == 3)
  for i in range(num_bits >> 1):
    S = A + D
    bpair = ((B >> 2) & 0x3) + bc31
    # print intermediate values here for debugging
    A, B, D = S >> 2, ((S & 3) << num_bits-2) | (B >> 2), C_map[bpair & 3]
    bc31 = (bpair >> 2) | ((bpair & 3) == 3)
  return (A << num_bits) | B

Intermediate hex values for bit_pair_multiply(3, 11, 8):

 E  A  B  D CS  S bpair bc31
 3  0  b fc  1 fd     3    1
 2 ff 42 fc  1 fc     1    1
 1 ff 10  3  0  2     0    0
 0  0 84  0  0  0     1    0

The final result:

    A  B  D CS  S bpair bc31
    0 21  3  0  0     1    0

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

    reg [0:7] phase;
    assign ph1 = phase[7];
    assign ph2 = phase[6];
    assign ph3 = phase[5];
    assign ph4 = phase[4];
    assign ph5 = phase[3];
    assign ph6 = phase[2];
    assign ph7 = phase[1];
    assign ph8 = phase[0];
    parameter PH1 = 1<<0, PH2 = 1<<1, PH3 = 1<<2, PH4 = 1<<3, PH5 = 1<<4, PH6 = 1<<5, PH7 = 1<<6, PH8 = 1<<7;

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
            phase <= PH1;
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
            if (start & ph1) begin
                a <= 0;
                b <= multiplicand;
                c <= multiplier;
                cs <= 0;
                bc31 <= 0;
                case (multiplicand[`WIDTH-2:`WIDTH-1])
                    0: begin d <= 0; end
                    1: begin d <= multiplier; end
                    2: begin d <= { multiplier[1:`WIDTH-1], 1'b0 }; end
                    3: begin d <= ~multiplier;  cs <= 1; bc31 <= 1; end
                endcase
                count <= (`WIDTH >> 1) - 1;
                done <= 0;
                phase <= PH2;
            end
            if (ph2) begin // multiplication iteration loop
                //$display("count: %d, a:b %x:%x, d: %x, cs: %x, s: %x, bpair: %x, bc31: %x", count, a, b, d, cs, s, bpair, bc31);
                a <= { {2{s[0]}}, s[0:`WIDTH-3] };
                b <= { s[`WIDTH-2:`WIDTH-1], b[0:`WIDTH-3] };
                cs <= 0;
                bc31 <= bpair[0] | (bpair[1] & bpair[2]);
                case (bpair[1:2])
                    0: begin d <= 0; end
                    1: begin d <= c; end
                    2: begin d <= { c[1:`WIDTH-1], 1'b0 }; end
                    3: begin d <= ~c;  cs <= 1; end
                endcase
                count <= count - 1;
                if (count == 0) phase <= PH3;
            end
            if (ph3) begin // result
                //$display("a:b %x:%x, d: %x, cs: %x, s: %x, bpair: %x, bc31: %x", count, a, b, d, cs, s, bpair, bc31);
                result <= { a, b };
                done <= 1;
                phase <= PH1;
            end
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
        #0 reset=0; #25 reset=1; #50; reset=0;

        multiplier = 1; multiplicand = 1; #100 start = 1; #100 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));
        multiplier = 1; multiplicand = 2; #100 start = 1; #100 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));
        multiplier = 1; multiplicand = 3; #100 start = 1; #100 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));

        multiplier = 1; multiplicand = 32'h3f3f3f0; #100 start = 1; #100 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));
        multiplier = 35; multiplicand = 17; #100 start = 1; #100 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));
        multiplier = 17; multiplicand = 35; #100 start = 1; #100 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));
        multiplier = 35; multiplicand = 63; #100 start = 1; #100 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));
        multiplier = 31415; multiplicand = 113; #100 start = 1; #100 start = 0; #2000;
        $display("%d*%d, => %d, %d==0", multiplier, multiplicand, result, result-(multiplier*multiplicand));

        $finish;
    end
endmodule
