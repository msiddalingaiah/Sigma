
`timescale 1 ns/10 ps  // time-unit = 1 ns, precision = 10 ps
`include "CPU.v"

/**
 * This file contains a test bench for the CPU.
 */

/**
 * A clock generator for simulation only.
 * This module is not used during synthesis.
 *
 * See https://d1.amobbs.com/bbs_upload782111/files_33/ourdev_585395BQ8J9A.pdf
 * pp 129
 */
module Clock(output reg clock);
    initial begin
        #0 clock = 0;
    end

    // Assume a fixed requency, 10MHz clock
    always begin
        #50 clock <= ~clock;
    end
endmodule

module Memory(input wire clock, input wire [15:31] address, input wire write_en, input wire [0:31] data_in,
    output reg [0:31] data_out);

    parameter ADDRESS_MASK = 17'h7f;

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
    localparam CYCLE_LIMIT = 500;
    localparam TIME_LIMIT = 101*CYCLE_LIMIT;

    initial begin
        cycle_count = 0;
        instruction_count = 0;
        $dumpfile("vcd/CPUTestBench.vcd");
        $dumpvars(0, CPUTestBench);

        $readmemh("roms/sigma_microcode.txt", cpu.uc_rom.memory);
        $readmemh("programs/init.txt", ram.ram_cells);
        #0 reset = 0; #25 reset = 1; #90 reset = 0;
        #TIME_LIMIT $display("\nTime limit reached, possible infinite loop.");
        cycles_per_inst = 100*cycle_count / instruction_count;
        $display("%4d cycles, %4d instructions, %1.2f cycles per instruction.",
            cycle_count, instruction_count, cycles_per_inst/100);
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
    real cycles_per_inst;

    always @(posedge clock) begin
        cycle_count <= cycle_count + 1;
        if (cycle_count >= CYCLE_LIMIT) begin
            $display("\nClock limit reached, possible inifinite loop.");
            cycles_per_inst = 100*cycle_count / instruction_count;
            $display("%4d cycles, %4d instructions, %1.2f cycles per instruction.",
                cycle_count, instruction_count, cycles_per_inst/100);
            $finish;
        end
        if (cpu.o == 46) begin
            $display("\nCPU WAIT: execution terminated normally.");
            cycles_per_inst = 100*cycle_count / instruction_count;
            $display("%4d cycles, %4d instructions, %1.2f cycles per instruction.",
                cycle_count, instruction_count, cycles_per_inst/100);
            $finish;
        end
        if (cpu.ende) begin
            instruction_count <= instruction_count + 1;
        end
    end
endmodule
