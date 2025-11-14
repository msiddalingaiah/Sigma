
`timescale 1 ns/10 ps  // time-unit = 1 ns, precision = 10 ps

`ifdef CPU_HW
    `include "CPUhw.v"
`else
    `include "CPU.v"
`endif

`include "CardReader.v"

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

module Arbiter(input wire reset, input wire clock,
    input wire [0:3] write_en[0:1], input wire [15:31] address[0:1], input wire [0:31] data_in[0:1],
    output reg [0:3] mem_write_en, output reg [15:31] memory_address, output reg [0:31] memory_data,
    input wire [0:1] running, output reg [0:1] active);

    reg [0:3] selected_device;

    always @(*) begin
        active = 0;
        if (running[selected_device]) begin
            active[selected_device] = 1;
            mem_write_en = write_en[selected_device];
            memory_address = address[selected_device];
            memory_data = data_in[selected_device];
        end else begin
            active[0] = 1;
            mem_write_en = write_en[0];
            memory_address = address[0];
            memory_data = data_in[0];
        end
        // active = 0;
        // mem_write_en = 0;
        // memory_address = 0;
        // memory_data = 0;
        // case (active_device)
        //     0: begin // CPU
        //         active[0] = 1;
        //         mem_write_en = write_en[0];
        //         memory_address = address[0];
        //         memory_data = data_in[0];
        //     end
        //     1: begin // CPU
        //         active[1] = 1;
        //         mem_write_en = write_en[1];
        //         memory_address = address[1];
        //         memory_data = data_in[1];
        //     end
        // endcase
    end

    always @(posedge clock, posedge reset) begin
        if (reset == 1) begin
            selected_device <= 0;
        end else begin
            selected_device <= selected_device + 1;
            if (selected_device == 1) selected_device <= 0;
        end
    end
endmodule

module CPUTestBench;
    localparam CYCLE_LIMIT = 2000;
    localparam TIME_LIMIT = 101*CYCLE_LIMIT;

    reg reset;
    reg [0:31] cycle_count;
    reg [0:15] instruction_count;
    real cycles_per_inst;

    integer i;
    reg [0:31] temp;
    initial begin
        cycle_count = 0;
        instruction_count = 0;
        $dumpfile("vcd/CPUTestBench.vcd");
        $dumpvars(0, CPUTestBench);

        $readmemh("programs/init.txt", ram.temp);
        $readmemh("programs/sighcp.txt", cr0.card_words);
        for (i=0; i<ram.MAX_WORD_LEN; i=i+1) begin
            temp = ram.temp[i];
            ram.cells0[i] = temp[0:7];
            ram.cells1[i] = temp[8:15];
            ram.cells2[i] = temp[16:23];
            ram.cells3[i] = temp[24:31];
        end

        `ifdef CPU_HW
        `else
            $readmemh("roms/microcode.txt", cpu.uc_rom.memory);
            $readmemh("roms/op_switch.txt", cpu.op_switch);
        `endif

        #0 reset = 0; #25 reset = 1; #90 reset = 0;
        #TIME_LIMIT $display("\Time limit reached, possible inifinite loop at 0x%4x", (cpu.p >> 2) - 1);
        cycles_per_inst = 100*cycle_count / instruction_count;
        $display("%4d cycles, %4d instructions, %1.2f cycles per instruction.",
            cycle_count, instruction_count, cycles_per_inst/100);
        $finish;
    end

    wire [0:31] memory_data_in, memory_data_out;
    wire [0:31] cpu_data_out, cr0_data_out;
    wire [15:31] memory_address, cpu_address, cr0_address;
    wire [0:3] mem_write_en, cpu_wr_en, ccr0_wr_en;
    wire clock;
    Clock cg0(clock);
    Memory ram(clock, memory_address, mem_write_en, memory_data_in, memory_data_out);
    wire [0:11] iop;
    wire cr0_sio, cr0_tio;
    wire [0:3] cr0_cc;

    wire [0:3] write_en[0:1];
    assign write_en[0] = cpu_wr_en;
    assign write_en[1] = ccr0_wr_en;

    wire [15:31] address[0:1];
    assign address[0] = cpu_address;
    assign address[1] = cr0_address;

    wire [0:31] data_in[0:1];
    assign data_in[0] = cpu_data_out;
    assign data_in[1] = cr0_data_out;

    wire [0:1] running;
    wire cr0_running;
    assign running[0] = 1;
    assign running[1] = cr0_running;

    wire [0:1] active;

    Arbiter arb(reset, clock, write_en, address, data_in,
        mem_write_en, memory_address, memory_data_in, running, active);

    CPU cpu(reset, clock, active[0], memory_data_out, cpu_address, cpu_data_out, cpu_wr_en);

    CardReader cr0(reset, clock, cr0_running, active[1], memory_data_out, cr0_address, cr0_data_out, ccr0_wr_en,
        cr0_sio, cr0_tio, cr0_cc);

    always @(posedge clock, posedge reset) begin
        if (reset == 1) begin
        end else begin
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
    end
endmodule
