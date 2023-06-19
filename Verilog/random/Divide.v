
// See https://www.fpga4student.com/2016/12/32-bit-unsigned-divider-in-verilog.html
// fpga4student.com FPGA projects, Verilog projects, VHDL projects
// Verilog project: Verilog code for 8-bit divider
// Verilog code for divider using behavioral modelling

// *** This doesn't appear to work properly...
module Divide(
    input clk,
    input reset,
    input start,
    input [7:0]  A,
    input [7:0]  B,
    output [7:0]  D,
    output [7:0]  R,
    output ok ,   // =1 when ready to get the result
    output err);

    reg active;   // True if the divider is running
    reg [4:0] cycle;   // Number of cycles to go
    reg [7:0] result;   // Begin with A, end with D
    reg [7:0] denom;   // B
    reg [7:0] work;    // Running R
    // Calculate the current digit
    wire [8:0] sub = { work[6:0], result[7] } - denom;
    assign err = !B;
    // Send the results to our master
    assign D = result;
    assign R = work;
    assign ok = ~active;
    // fpga4student.com FPGA projects, Verilog projects, VHDL projects
    // The state machine
    always @(posedge clk,posedge reset) begin
        if (reset) begin
            active <= 0;
            cycle <= 0;
            result <= 0;
            denom <= 0;
            work <= 0;
        end else if(start) begin
            if (active) begin
                // Run an iteration of the divide.
                if (sub[8] == 0) begin
                    work <= sub[7:0];
                    result <= {result[6:0], 1'b1};
                end else begin
                    work <= {work[6:0], result[7]};
                    result <= {result[6:0], 1'b0};
                end
                if (cycle == 0) begin
                    active <= 0;
                end
                cycle <= cycle - 5'd1;
                $display("cycle %d, sub %b, work %b, result %b", cycle, sub, work, result);
            end else begin
                // Set up for an unsigned divide.
                cycle <= 5'd7;
                result <= A;
                denom <= B;
                work <= 8'b0;
                active <= 1;
            end
        end
    end
endmodule

`timescale 1ns / 1ns
// fpga4student.com FPGA projects, Verilog projects, VHDL projects
// Verilog project: Verilog code for 8-bit divider
// Testbench Verilog code for divider using behavioral modelling
module tb_divider;
    // Inputs
    reg clock;
    reg reset;
    reg start;
    reg [7:0] A;
    reg [7:0] B;
    // Outputs
    wire [7:0] D;
    wire [7:0] R;
    wire ok;
    wire err;

    // Instantiate the Unit Under Test (UUT)
    Divide uut (
        .clk(clock),
        .start(start),
        .reset(reset),
        .A(A),
        .B(B),
        .D(D),
        .R(R),
        .ok(ok),
        .err(err)
    );
    initial begin
        clock = 0;
        forever #50 clock = ~clock;
    end
    initial begin
        // Initialize Inputs
        start = 0;
        A = 8'd7;
        B = 8'd2;
        reset=1;
        // Wait 100 ns for global reset to finish
        #1000;
        reset=0;
        start = 1;
        #5000;
        $display("A: %d, B: %d, D: %d, R: %d", A, B, D, R);
        $finish;
    end
endmodule
