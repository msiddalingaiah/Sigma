
`timescale 1 ns/10 ps  // time-unit = 1 ns, precision = 10 ps
`include "CPU.v"
// `define TRACE_WR 1

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

module Memory(input wire clock, input wire [15:31] address, input wire [0:3] write_en, input wire [0:31] data_in,
    output reg [0:31] data_out);

    localparam MAX_WORD_LEN = 1024;
    // This only works if MAX_WORD_LEN is a power of two
    localparam ADDRESS_MASK = MAX_WORD_LEN-1;

    reg [0:7] cells0[0:MAX_WORD_LEN-1];
    reg [0:7] cells1[0:MAX_WORD_LEN-1];
    reg [0:7] cells2[0:MAX_WORD_LEN-1];
    reg [0:7] cells3[0:MAX_WORD_LEN-1];
    reg [0:31] temp[0:MAX_WORD_LEN-1];
    wire [15:31] addr = address & ADDRESS_MASK;

    integer i;
    initial begin
        for (i=0; i<MAX_WORD_LEN; i=i+1) begin
            cells0[i] = 0;
            cells1[i] = 0;
            cells2[i] = 0;
            cells3[i] = 0;
            temp[i] = 0;
        end
    end

    always @(*) begin
        data_out = 0;
        case (address)
            default:
                data_out = { cells0[addr], cells1[addr], cells2[addr], cells3[addr] };
        endcase
    end

    always @(posedge clock) begin
        if (write_en[0]) begin
            `ifdef TRACE_WR
                $display("WR0: %x, %x", addr, data_in[0:7]);
            `endif
            cells0[addr] <= data_in[0:7];
        end
        if (write_en[1]) begin
            `ifdef TRACE_WR
                $display("WR1: %x, %x", addr, data_in[8:15]);
            `endif
            cells1[addr] <= data_in[8:15];
        end
        if (write_en[2]) begin
            `ifdef TRACE_WR
                $display("WR2: %x, %x", addr, data_in[16:23]);
            `endif
            cells2[addr] <= data_in[16:23];
        end
        if (write_en[3]) begin
            `ifdef TRACE_WR
                $display("WR3: %x, %x", addr, data_in[24:31]);
            `endif
            cells3[addr] <= data_in[24:31];
        end
    end
endmodule

module CPUTestBench;
    localparam CYCLE_LIMIT = 1500;
    localparam TIME_LIMIT = 101*CYCLE_LIMIT;

    integer i;
    reg [0:31] temp;
    initial begin
        cycle_count = 0;
        instruction_count = 0;
        $dumpfile("vcd/CPUTestBench.vcd");
        $dumpvars(0, CPUTestBench);

        $readmemh("roms/microcode.txt", cpu.uc_rom.memory);
        $readmemh("programs/init.txt", ram.temp);
        for (i=0; i<ram.MAX_WORD_LEN; i=i+1) begin
            temp = ram.temp[i];
            ram.cells0[i] = temp[0:7];
            ram.cells1[i] = temp[8:15];
            ram.cells2[i] = temp[16:23];
            ram.cells3[i] = temp[24:31];
        end

        $readmemh("roms/op_switch.txt", cpu.op_switch);
        #0 reset = 0; #25 reset = 1; #90 reset = 0;
        #TIME_LIMIT $display("\Time limit reached, possible inifinite loop at 0x%4x", (cpu.p >> 2) - 1);
        cycles_per_inst = 100*cycle_count / instruction_count;
        $display("%4d cycles, %4d instructions, %1.2f cycles per instruction.",
            cycle_count, instruction_count, cycles_per_inst/100);
        $finish;
    end

    wire [0:31] data_c2r, data_r2c;
    wire [0:16] addressBus;
    wire [0:3] wr_enables;
    wire clock;
    Clock cg0(clock);
    Memory ram(clock, addressBus, wr_enables, data_c2r, data_r2c);
    reg reset;
    CPU cpu(reset, clock, data_r2c, addressBus, data_c2r, wr_enables);
    reg [0:31] cycle_count;
    reg [0:15] instruction_count;
    real cycles_per_inst;

    always @(posedge clock) begin
        cycle_count <= cycle_count + 1;
        if (cycle_count >= CYCLE_LIMIT) begin
            $display("\nClock limit reached, possible inifinite loop at 0x%4x", (cpu.p >> 2) - 1);
            cycles_per_inst = 100*cycle_count / instruction_count;
            $display("%4d cycles, %4d instructions, %1.2f cycles per instruction.",
                cycle_count, instruction_count, cycles_per_inst/100);
            $finish;
        end
        if (cpu.o == 46) begin
            $display("\nCPU WAIT: execution terminated at 0x%4x", (cpu.p >> 2) - 1);
            cycles_per_inst = 100*cycle_count / instruction_count;
            $display("%4d cycles, %4d instructions, %1.2f cycles per instruction.",
                cycle_count, instruction_count, cycles_per_inst/100);
            $finish;
        end
        if (cpu.trap) begin
            $display("\nTrap encountered at %x, c = %x.", cpu.q - 1, cpu.c);
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
