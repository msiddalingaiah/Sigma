
`include "Sequencer.v"

//`define TRACE_I 1

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
    // || - seq_op[0:1] 2 bits
    //   || - seq_address_mux[2:3] 2 bits
    //     |_| - seq_condition[4:6] 3 bits
    //        |__| - ax[7:10] 4 bits
    // |-------|-------|-------|-------|-------|-------|-------|
    //            |_| - dx[11:13] 3 bits
    //               |_| - px[14:16] 3 bits
    //                  | - qx[17]
    //                   |__| - rrx[18:21] 4 bits
    // |-------|-------|-------|-------|-------|-------|-------|
    //                       |__| - sxop[22:25] 4 bits
    //                           | - ende[26]
    //                            | - testa[27]
    //                             | - wd_en[28]
    // |-------|-------|-------|-------|-------|-------|-------|
    //                              | - uc_debug[29]
    //                               |____________| - __unused[30:43] 14 bits
    //                                             |__________| - seq_address[44:55] 12 bits
    //                                                 |______| - _const8[48:55] 8 bits

    reg [0:55] pipeline;
    wire [0:1] seq_op = pipeline[0:1];
    wire [0:1] seq_address_mux = pipeline[2:3];
    wire [0:2] seq_condition = pipeline[4:6];
    wire [0:3] ax = pipeline[7:10];
    wire [0:2] dx = pipeline[11:13];
    wire [0:2] px = pipeline[14:16];
    wire qx = pipeline[17];
    wire [0:3] rrx = pipeline[18:21];
    wire [0:3] sxop = pipeline[22:25];
    wire ende = pipeline[26];
    wire testa = pipeline[27];
    wire wd_en = pipeline[28];
    wire uc_debug = pipeline[29];
    wire [0:13] __unused = pipeline[30:43];
    wire [0:11] seq_address = pipeline[44:55];
    wire [0:7] _const8 = pipeline[48:55];
    
    localparam SX_ADD = 0;
    localparam SX_SUB = 1;
    localparam SX_D = 2;
    localparam AX_NONE = 0;
    localparam AX_S = 1;
    localparam AX_RR = 2;
    localparam DX_NONE = 0;
    localparam DX_1 = 1;
    localparam DX_CINB = 2;
    localparam DX_CINH = 3;
    localparam DX_CIN = 4;
    localparam PX_NONE = 0;
    localparam PX_D = 1;
    localparam PX_Q = 2;
    localparam QX_NONE = 0;
    localparam QX_P = 1;
    localparam RRX_NONE = 0;
    localparam RRX_S = 1;
    localparam COND_NONE = 0;
    localparam COND_S_GT_ZERO = 1;
    localparam COND_S_LT_ZERO = 2;
    localparam ADDR_MUX_SEQ = 0;
    localparam ADDR_MUX_OPCODE = 1;

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
    reg [15:33] p;
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
    // private memory index register number
    reg [0:2] x;

    // Address family decode, see ANLZ instruction
    wire fa_b = o[1] & o[2] & o[3];
    wire fa_h = o[1] & ~o[2] & o[3];
    wire ou3 = (~o[1]) & o[2] & o[3];
    wire fa_w = ou3 | (~o[3] & ~o[4] & o[5]) | (o[1] & ~o[3] & o[4]) | (o[2] & ~o[3] & o[4]); // pp 3-182
    wire [0:31] indx_offset = {32{(x[0] | x[1] | x[2])}} & rr[x];

    // Signals

    // Guideline #3: When modeling combinational logic with an "always" 
    //              block, use blocking assignments.
    // Order matters here!!!
    always @(*) begin
        // Sequencer d_in mux
        uc_din = seq_address;
        case (seq_address_mux)
            ADDR_MUX_SEQ: uc_din = seq_address; // jump or call
            ADDR_MUX_OPCODE: uc_din = o; // instruction op code
        endcase
        s = 0;
        case (sxop)
            SX_ADD: s = a+d;
            SX_SUB: s = a-d;
            SX_D: s = d;
        endcase
        branch = 0;
        case (seq_condition)
            COND_NONE: branch = 0; // branch unconditionally
            COND_S_GT_ZERO: branch = ~(s[0] | (s == 0));
            COND_S_LT_ZERO: branch = s[0];
        endcase
        uc_op = seq_op;
        case (seq_op)
            0: uc_op = { 1'h0, branch }; // next, invert selected branch condition
            1: uc_op = { 1'h0, ~branch }; // jump
            2: ; // call
            3: ; // return
        endcase
        lb = p[15:31];
    end

    // Guideline #1: When modeling sequential logic, use nonblocking 
    //              assignments.
    integer i;
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
            for (i=0; i<16; i=i+1) rr[i] = 32'h00000000;
            e <= 0;
            x <= 0;
            pipeline <= 0;
        end else begin
            pipeline <= uc_rom_data;
            if (ende == 1) begin
                `ifdef TRACE_I
                    $display("* Q %x: %x", q, memory_data_in);
                    $display("  R0 %x %x %x %x %x %x %x %x", rr[0], rr[1], rr[2], rr[3], rr[4], rr[5], rr[6], rr[7]);
                    $display("  R8 %x %x %x %x %x %x %x %x", rr[8], rr[9], rr[10], rr[11], rr[12], rr[13], rr[14], rr[15]);
                `endif
                c <= c_in; d <= c_in; o <= c_in[1:7]; r <= c_in[8:11]; x <= c_in[12:14]; p <= p + 4;
                // immediate value
                if (~c_in[3] & ~c_in[4] & ~c_in[5]) begin d <= { {12{c_in[12]}}, c_in[12:31] }; end
            end
            case (ax)
                AX_NONE: ; // do nothing
                AX_S: a <= s;
                AX_RR: a <= rr[r];
            endcase
            case (dx)
                DX_NONE: ; // do nothing
                DX_1: d <= 32'h1;
                DX_CINB:
                    case (p[32:33])
                        0: d <= { 24'h0, c_in[0:7] };
                        1: d <= { 24'h0, c_in[8:15] };
                        2: d <= { 24'h0, c_in[16:23] };
                        3: d <= { 24'h0, c_in[24:31] };
                    endcase
                DX_CINH:
                    case (p[32])
                        0: d <= { {16{c_in[0]}}, c_in[0:15] };
                        1: d <= { {16{c_in[16]}}, c_in[16:31] };
                    endcase
                DX_CIN: d <= c_in;
            endcase
            case (rrx)
                RRX_NONE: ; // do nothing
                RRX_S: rr[r] <= s;
            endcase
            case (px)
                PX_NONE: ; // do nothing
                PX_D:
                    begin
                        p[15:33] <= { d[15:31], 2'h0 };
                        if (fa_b) begin
                            p[15:33] <= { d[15:31], 2'h0 } + indx_offset[13:31];
                        end
                        if (fa_h) begin
                            p[15:33] <= { d[15:31], 2'h0 } + { indx_offset[14:31], 1'h0 };
                        end
                        if (fa_w) begin
                            p[15:33] <= { d[15:31], 2'h0 } + { indx_offset[15:31], 2'h0 };
                        end
                    end
                PX_Q: p[15:33] <= { q, 2'h0 };
            endcase
            case (qx)
                QX_NONE: ; // do nothing
                QX_P: q <= p[15:31];
            endcase
            if (testa == 1) begin cc[3] <= (~a[0]) & (a != 0); cc[4] <= a[0]; end
            if (wd_en == 1) begin
                // $display("wd_en, d[24:31] = %x, r = %x, rr[r][25:31]", d[24:31], r, rr[r][25:31]);
                if ((d[24:31] == 0) && (r != 0)) begin
                    $write("%s", rr[r][25:31]);
                end
            end
            if (uc_debug == 1) begin
                $display("%4d: d: %x, p: %x, c_in: %x, s: %x, fa_b: %x, indx_offset: %x, x: %x",
                    seq.pc-1, d, p, c_in, s, fa_b, indx_offset, x);
            end
        end
    end
endmodule
