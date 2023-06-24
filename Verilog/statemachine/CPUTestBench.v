
`define TRACE_I // trace instructions

`timescale 1 ns/10 ps  // time-unit = 1 ns, precision = 10 ps
`include "CPU.v"
`include "Clock.v"

module Memory(input wire clock, input wire [15:31] address, input wire [0:3] write_en, input wire [0:31] data_in,
    output reg [0:31] data_out);

    parameter ADDRESS_MASK = 17'h7f;
    parameter MEM_SIZE = 128;

    reg [0:7] cells0[0:MEM_SIZE-1];
    reg [0:7] cells1[0:MEM_SIZE-1];
    reg [0:7] cells2[0:MEM_SIZE-1];
    reg [0:7] cells3[0:MEM_SIZE-1];
    reg [0:31] temp[0:MEM_SIZE-1];
    wire [15:31] addr = address & ADDRESS_MASK;

    integer i;
    initial begin
        for (i=0; i<MEM_SIZE; i=i+1) begin
            cells0[i] = 0;
            cells1[i] = 0;
            cells2[i] = 0;
            cells3[i] = 0;
            temp[i] = 0;
        end
    end

    always @(*) begin
        data_out = 0;
        case (addr)
            default:
                data_out = { cells0[addr], cells1[addr], cells2[addr], cells3[addr] };
        endcase
    end

    always @(posedge clock) begin
        if (write_en[0]) begin
            cells0[addr] <= data_in[0:7];
        end
        if (write_en[1]) begin
            cells1[addr] <= data_in[8:15];
        end
        if (write_en[2]) begin
            cells2[addr] <= data_in[16:23];
        end
        if (write_en[3]) begin
            //$display("WR3: %x", data_in[24:31]);
            cells3[addr] <= data_in[24:31];
        end
    end
endmodule

module CPUTestBench;
    integer i;
    reg [0:31] temp;
    initial begin
        $dumpfile("vcd/CPUTestBench.vcd");
        $dumpvars(0, CPUTestBench);

        $write("Begin:\n");
        $readmemh("programs/init.txt", ram.temp);
        for (i=0; i<ram.MEM_SIZE; i=i+1) begin
            temp = ram.temp[i];
            ram.cells0[i] = temp[0:7];
            ram.cells1[i] = temp[8:15];
            ram.cells2[i] = temp[16:23];
            ram.cells3[i] = temp[24:31];
        end

        sim_end = 0; #0 reset = 0; #25 reset = 1; #50 reset = 0;
        wait(sim_end == 1);
        //#10000 $finish;

        $display("All done!");
        $finish;
    end

    wire [0:31] data_c2m, data_m2c;
    wire [0:16] addressBus;
    wire [0:3] wr_enables;
    wire clock;
    Clock cg0(clock);
    Memory ram(clock, addressBus, wr_enables, data_c2m, data_m2c);
    reg reset;
    CPU cpu(reset, clock, data_m2c, addressBus, data_c2m, wr_enables);
    reg sim_end;

    always @(posedge clock) begin
        if (cpu.phase == cpu.PCP2) begin
            sim_end <= 1;
        end
    end
endmodule
