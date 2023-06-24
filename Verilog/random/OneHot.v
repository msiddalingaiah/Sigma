
// A one hot encoded machine

/*

It compiles and simulates in Icarus Verilog:

$ iverilog -o Divide3 Divide3.v
$ vvp Divide3

 */

module OneHot (
    input clock,
    input reset);

    reg [0:7] phase;
    assign ph1 = phase[0];
    assign ph2 = phase[1];
    assign ph3 = phase[2];
    assign ph4 = phase[3];
    assign ph5 = phase[4];
    assign ph6 = phase[5];
    assign ph7 = phase[6];
    assign ph8 = phase[7];
    parameter PH1 = 1<<7, PH2 = 1<<6, PH3 = 1<<5, PH4 = 1<<4, PH5 = 1<<3, PH6 = 1<<2, PH7 = 1<<1, PH8 = 1;

    always @(*) begin
    end

    always @(posedge clock, posedge reset) begin
        if (reset) begin
            phase <= PH1;
        end else begin
            $display("%x", phase);
            case (phase)
                PH1: phase <= PH2;
                PH2: phase <= PH3;
                PH3: phase <= PH4;
                PH4: phase <= PH5;
                PH5: phase <= PH2;
                default: phase <= PH1;
            endcase
        end
    end
endmodule

`timescale 1ns / 1ns
module tb_one_hot;
    reg clock;
    reg reset;

    OneHot uut (
        .clock(clock),
        .reset(reset)
    );
    initial begin
        clock = 0;
        forever #50 clock = ~clock;
    end
    initial begin
        $dumpfile("vcd/OneHot.vcd");
        $dumpvars(0, uut);

        #0 reset=0; #25 reset=1; #100; reset=0;

        #1000;
        $finish;
    end
endmodule
