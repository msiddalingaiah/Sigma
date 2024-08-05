
`include "Sequencer.v"

/**
 * This module implements the microcode ROM.
 * Microcode is loaded from a text file, which is synthesizable.
 */
module CodeROM(input wire [11:0] address, output wire [55:0] data);
    reg [55:0] memory[0:4095];

    assign data = memory[address];
endmodule

/*
Memory is word addressed, 17 bits
*/
module CPU(input wire reset, input wire clock, input wire [0:31] memory_data_in, output wire [15:31] memory_address);
    assign memory_address = lb;

    // Microcode sequencer
    reg [0:1] uc_op;
    reg [0:11] uc_din;
    Sequencer seq(reset, clock, uc_op, uc_din, uc_rom_address);
    // Microcode ROM(s)
    wire [0:11] uc_rom_address;
    wire [0:55] uc_rom_data;
    CodeROM uc_rom(uc_rom_address, uc_rom_data);

    // ---- BEGIN Pipeline definitions DO NOT EDIT

    // Microcode pipeline register
    // 0       8       16      24      32      40      48      56      
    // |-------|-------|-------|-------|-------|-------|-------|
    // | - seq_address_mux[0:1] 2 bits
    //   | - seq_op[2:3] 2 bits
    //     | - seq_condition[4:6] 3 bits
    //        | - sxop[7:10] 4 bits
    // |-------|-------|-------|-------|-------|-------|-------|
    //            | - ende[11]
    //             | - testa[12]
    //              | - rrxa[13]
    //               | - wd_en[14]
    // |-------|-------|-------|-------|-------|-------|-------|
    //                | - dx1[15]
    //                 | - axrr[16]
    //                  | - axs[17]
    //                   | - exconst8[18]
    // |-------|-------|-------|-------|-------|-------|-------|
    //                    | - e_count[19:20] 2 bits
    //                      | - pxqxp[21]
    //                       | - pxd[22]
    //                        | - rrxs[23]
    // |-------|-------|-------|-------|-------|-------|-------|
    //                         | - uc_debug[24]
    //                          | - __unused[25:43] 19 bits
    //                                             | - seq_address[44:55] 12 bits
    //                                                 | - _const8[48:55] 8 bits

    reg [0:55] pipeline;
    wire [0:1] seq_address_mux = pipeline[0:1];
    wire [0:1] seq_op = pipeline[2:3];
    wire [0:2] seq_condition = pipeline[4:6];
    wire [0:3] sxop = pipeline[7:10];
    wire ende = pipeline[11];
    wire testa = pipeline[12];
    wire rrxa = pipeline[13];
    wire wd_en = pipeline[14];
    wire dx1 = pipeline[15];
    wire axrr = pipeline[16];
    wire axs = pipeline[17];
    wire exconst8 = pipeline[18];
    wire [0:1] e_count = pipeline[19:20];
    wire pxqxp = pipeline[21];
    wire pxd = pipeline[22];
    wire rrxs = pipeline[23];
    wire uc_debug = pipeline[24];
    wire [0:18] __unused = pipeline[25:43];
    wire [0:11] seq_address = pipeline[44:55];
    wire [0:7] _const8 = pipeline[48:55];

    // ---- END Pipeline definitions DO NOT EDIT

    reg branch;

    // Standard register configuration
    reg [0:31] a, b, d;
    // c is a transparent latch, see pp 3-38, receives data from memory
    reg [0:31] c;
    wire [0:31] c_in = memory_data_in;
    // e is a counting register
    reg [0:7] e;
    // Condition code register
    reg [1:4] cc;
    // Carry save register
    reg [0:33] cs;
    // Indirect addressing flip flop
    reg ia;

    reg [15:31] lb;
    // opcode register
    reg [1:7] o;
    // p is a counting register, acts as the program counter in conjunction with q
    reg [15:31] p;
    // Phase register, one-hot encoded
    reg [0:7] phase;
    // q holds the next instruction address
    reg [15:31] q;
    // private memory address (register number), pctr counts up, mctr counts down
    reg [28:31] r;
    // private memory registers
    reg [0:31] rr[0:16];
    // register pointer
    reg [23:27] rp;
    // sum bus
    reg [0:31] s;

    // Signals

    // Guideline #3: When modeling combinational logic with an "always" 
    //              block, use blocking assignments.
    // Order matters here!!!
    always @(*) begin
        // Sequencer d_in mux
        uc_din = seq_address;
        case (seq_address_mux)
            0: uc_din = seq_address; // jump or call
            1: uc_din = o; // instruction op code
            2: uc_din = 0; // not used
            3: uc_din = 0; // not used
        endcase
        s = 0;
        case (sxop)
            0: s = a+d;
            1: s = a-d;
        endcase
        branch = 0;
        case (seq_condition)
            0: branch = 0; // branch unconditionally
            1: branch = e == 0; // COND_EQ_ZERO
            2: branch = ~(s[0] | (s == 0)); // COND_S_GT_ZERO
            3: branch = s[0]; // COND_S_LT_ZERO
            4: branch = 0;
            5: branch = 0;
            6: branch = 0;
            7: branch = 0;
        endcase
        uc_op = seq_op;
        case (seq_op)
            0: uc_op = { 1'h0, branch }; // next, invert selected branch condition
            1: uc_op = { 1'h0, ~branch }; // jump
            2: ; // call
            3: ; // return
        endcase
        lb = p;
    end

    // Guideline #1: When modeling sequential logic, use nonblocking 
    //              assignments.
    always @(posedge clock, posedge reset) begin
        if (reset == 1) begin
            a <= 0;
            b <= 0;
            c <= 0;
            cc <= 0;
            d <= 0;
            o <= 0;
            p <= 0;
            q <= 0;
            r <= 0;
            e <= 0;
            pipeline <= 0;
        end else begin
            pipeline <= uc_rom_data;
            if (exconst8 == 1) e <= _const8;
            case (e_count)
                0: ;
                1: e <= e + 1;
                2: e <= e - 1;
                3: ;
            endcase
            if (ende == 1) begin
                c <= c_in; d <= c_in; o <= c_in[1:7]; r <= c_in[8:11]; p <= p + 1; a <= 0;
                // immediate value
                if (~c_in[3] & ~c_in[4] & ~c_in[5]) begin d <= { {12{c_in[12]}}, c_in[12:31] }; end
            end
            if (axs == 1) begin a <= s; end
            if (axrr == 1) begin a <= rr[r]; end
            if (rrxa == 1) begin rr[r] <= a; end
            if (rrxs == 1) begin rr[r] <= s; end
            if (testa == 1) begin cc[3] <= (~a[0]) & (a != 0); cc[4] <= a[0]; end
            if (dx1 == 1) begin d <= 32'h1; end
            if (pxqxp == 1) begin p <= q; q <= p; end
            if (pxd == 1) begin p <= d[15:31]; end
            if (wd_en == 1) begin
                // $display("wd_en, d[24:31] = %x, r = %x, rr[r][25:31]", d[24:31], r, rr[r][25:31]);
                if ((d[24:31] == 0) && (r != 0)) begin
                    $write("%s", rr[r][25:31]);
                end
            end
            if (uc_debug == 1) begin
                $display("%4d: op %1d, branch: %1d, s %x, rr[r] %x", seq.pc-1, seq.op, branch, s, rr[r]);
            end
        end
    end
endmodule
