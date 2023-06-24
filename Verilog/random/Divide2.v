
// Two cycle non-restoring divide

/*
  This is known to work in Colab/Sigma

  Q = numerator # numerator / dividend
  M = denominator # denominator / divisor
  n = num_bits # number of bits

  sign_mask = 1 << (n+n-1)
  result_mask = ~(-1 << (n-1))

  A = Q
  M_shift = M << n
  M_comp = (~M_shift) & 0xff00

  lsb = 0
  for i in range(n):
    a = (A | lsb) << 1
    if A & sign_mask == 0:
      s = a + M_comp + (1 << n)
    else:
      s = a + M_shift
    A = s
    lsb = 1 if s & sign_mask == 0 else 0

  A |= lsb
  if A & sign_mask:
    A += M_shift

  rem = (A >> n) & result_mask
  quotient = A & result_mask

 */
module Divide2(
    input clock,
    input reset,
    input start,
    input [15:0] numerator,
    input [7:0] denominator,
    output reg [7:0] quotient,
    output reg [7:0] remainder,
    output reg done);

    reg lsb;
    reg [3:0] phase;
    reg [4:0] count;
    reg [15:0] M_shift;
    reg [15:0] a, d;
    reg [15:0] cs;
    reg [15:0] s;

    always @(*) begin
        s = a + d + cs;
    end

    always @(posedge clock, posedge reset) begin
        if (reset) begin
            phase <= 0;
            count <= 0;
            M_shift <= 0;
            a <= 0;
            d <= 0;
            cs <= 0;
            lsb <= 0;
            done <= 1;
        end else begin
            case (phase)
                0: if (start == 1) begin
                    count <= 8;
                    M_shift <= { denominator, 8'h00 };
                    a <= numerator;
                    d <= 0;
                    cs <= 0;
                    lsb <= 0;
                    count <= 8;
                    done <= 0;
                    phase <= 1;
                end
                1: begin
                    //$display("  %d: a = %x", count, { a[14:0] | { 13'h0, lsb }, 1'b0 });
                    a <= { a[14:0] | { 13'h0, lsb }, 1'b0 };
                    if (a[15] == 0) begin
                        d <= { ~denominator, 8'h00 };
                        cs <= 16'h0100;
                    end else begin
                        d <= {  denominator, 8'h00 };
                        cs <= 16'h0000;
                    end
                    phase <= 2;
                end
                2: begin
                    a <= s;
                    lsb <= ~s[15];
                    if (count == 1) begin
                        phase <= 3;
                    end else begin
                        count <= count - 1;
                        phase <= 1;
                    end
                end
                3: begin
                    a <= a | { 15'h0, lsb };
                    d <= {  denominator, 8'h00 };
                    cs <= 16'h0000;
                    phase <= 4;
                end
                4: begin
                    if (a[15] == 1) begin
                        remainder <= s[15:8];
                        quotient <= s[7:0];
                        //$display("  end %d r%d", s[7:0], s[15:8]);
                    end else begin
                        remainder <= a[15:8];
                        quotient <= a[7:0];
                        //$display("  end %d r%d", a[7:0], a[15:8]);
                    end
                    done <= 1;
                    phase <= 0;
                end
                5: begin
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
    reg [15:0] numerator;
    reg [7:0] denominator;
    // Outputs
    wire [7:0] quotient;
    wire [7:0] remainder;
    wire done;

    // Instantiate the Unit Under Test (UUT)
    Divide2 uut (
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
        $dumpfile("vcd/Divide2.vcd");
        $dumpvars(0, uut);

        // Initialize Inputs
        start = 0;
        reset=1;
        // Wait 100 ns for global reset to finish
        #1000;
        reset=0;

        // [[3550, 113], [3550, 112], [3550, 114], [100, 15], [100, 16], [100, 17]]
        numerator = 16'd3550; denominator = 8'd113; start = 1; #200 start = 0; #2000;
        $display("%d/%d, => %d, r%d, %d", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder));

        numerator = 16'd3550; denominator = 8'd112; start = 1; #200 start = 0; #2000;
        $display("%d/%d, => %d, r%d, %d", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder));

        numerator = 16'd3550; denominator = 8'd114; start = 1; #200 start = 0; #2000;
        $display("%d/%d, => %d, r%d, %d", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder));

        numerator = 16'd100; denominator = 8'd15; start = 1; #200 start = 0; #2000;
        $display("%d/%d, => %d, r%d, %d", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder));

        numerator = 16'd100; denominator = 8'd16; start = 1; #200 start = 0; #2000;
        $display("%d/%d, => %d, r%d, %d", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder));

        numerator = 16'd100; denominator = 8'd17; start = 1; #200 start = 0; #2000;
        $display("%d/%d, => %d, r%d, %d", numerator, denominator, quotient, remainder, numerator-(denominator*quotient+remainder));
        $finish;
    end
endmodule
