
`timescale 1 ns/10 ps  // time-unit = 1 ns, precision = 10 ps
`include "CPU.v"
`include "Clock.v"

/**
 * This file contains a test bench for the CPU.
 */
module Memory(input wire clock, input wire [15:31] address, input wire write_en, input wire [0:31] data_in,
    output reg [0:31] data_out);

    parameter ADDRESS_MASK = 17'h1ff;

    reg [0:31] ram_cells[0:127];

    integer i;
    initial begin
        for (i=0; i<128; i=i+1) ram_cells[i] = 32'h00000000;
    end

    always @(*) begin
        data_out = 0;
        case (address)
            default:
                data_out = ram_cells[address & ADDRESS_MASK];
        endcase
    end

    always @(posedge clock) begin
        if (write_en) begin
            ram_cells[address & ADDRESS_MASK] <= data_in;
        end
    end
endmodule

module CPUTestBench;
    initial begin
        cycle_count = 0;
        instruction_count = 0;
        $dumpfile("vcd/CPUTestBench.vcd");
        $dumpvars(0, CPUTestBench);

        $readmemh("programs/init.txt", ram.ram_cells);
        #0 reset = 0; #25 reset = 1; #90 reset = 0;
        #20000 $display("\nTime limit reached, possible infinite loop.");
        $display("%4d cycles, %4d instructions.", cycle_count, instruction_count);
        $finish;

        $display("All done!");
        $finish;
    end

    wire writeEnBus;
    wire [0:31] data_c2r, data_r2c;
    wire [0:16] addressBus;
    wire clock;
    Clock cg0(clock);
    Memory ram(clock, addressBus, writeEnBus, data_c2r, data_r2c);
    reg reset;
    CPU cpu(reset, clock, data_r2c, addressBus);
    reg [0:31] cycle_count;
    reg [0:15] instruction_count;

    always @(posedge clock) begin
        cycle_count <= cycle_count + 1;
        if (cycle_count >= 200) begin
            $display("\nClock limit reached, possible inifinite loop.");
            $display("%4d cycles, %4d instructions.", cycle_count, instruction_count);
            $finish;
        end
        if (cpu.o == 46) begin
            $display("\nCPU WAIT, execution terminated normally.");
            $display("%4d cycles, %4d instructions.", cycle_count, instruction_count);
            $finish;
        end
        if (cpu.ende) begin
            instruction_count <= instruction_count + 1;
        end
    end
endmodule
