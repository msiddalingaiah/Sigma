
`include "Sequencer.v"

// `define TRACE_I 1

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
module CPU(input wire reset, input wire clock, input wire active, input wire [0:31] memory_data_in,
    output wire [15:31] memory_address, output reg [0:31] memory_data_out, output reg [0:3] wr_enables);
    assign memory_address = lb;

    // Microcode sequencer
    reg [0:1] uc_op;
    reg [0:11] uc_din;
    Sequencer seq(reset, clock, active, uc_op, uc_din, uc_rom_address);
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
    //     |__| - seq_condition[4:7] 4 bits
    //         |__| - ax[8:11] 4 bits
    // |-------|-------|-------|-------|-------|-------|-------|
    //             |_| - dx[12:14] 3 bits
    //                |_| - px[15:17] 3 bits
    //                   | - qx[18]
    //                    |__| - rrx[19:22] 4 bits
    // |-------|-------|-------|-------|-------|-------|-------|
    //                        |__| - sxop[23:26] 4 bits
    //                            | - ende[27]
    //                             | - testa[28]
    //                              | - wd_en[29]
    // |-------|-------|-------|-------|-------|-------|-------|
    //                               | - trap[30]
    //                                |_| - divide[31:33] 3 bits
    //                                   || - multiply[34:35] 2 bits
    //                                     | - uc_debug[36]
    // |-------|-------|-------|-------|-------|-------|-------|
    //                                      || - write_size[37:38] 2 bits
    //                                        |___| - __unused[39:43] 5 bits
    //                                             |__________| - seq_address[44:55] 12 bits
    //                                                 |______| - _const8[48:55] 8 bits

    reg [0:55] pipeline;
    wire [0:1] seq_op = pipeline[0:1];
    wire [0:1] seq_address_mux = pipeline[2:3];
    wire [0:3] seq_condition = pipeline[4:7];
    wire [0:3] ax = pipeline[8:11];
    wire [0:2] dx = pipeline[12:14];
    wire [0:2] px = pipeline[15:17];
    wire qx = pipeline[18];
    wire [0:3] rrx = pipeline[19:22];
    wire [0:3] sxop = pipeline[23:26];
    wire ende = pipeline[27];
    wire testa = pipeline[28];
    wire wd_en = pipeline[29];
    wire trap = pipeline[30];
    wire [0:2] divide = pipeline[31:33];
    wire [0:1] multiply = pipeline[34:35];
    wire uc_debug = pipeline[36];
    wire [0:1] write_size = pipeline[37:38];
    wire [0:4] __unused = pipeline[39:43];
    wire [0:11] seq_address = pipeline[44:55];
    wire [0:7] _const8 = pipeline[48:55];
    
    localparam SX_ADD = 0;
    localparam SX_SUB = 1;
    localparam SX_A = 2;
    localparam SX_D = 3;
    localparam AX_NONE = 0;
    localparam AX_S = 1;
    localparam AX_RR = 2;
    localparam AX_0 = 3;
    localparam DX_NONE = 0;
    localparam DX_0 = 1;
    localparam DX_1 = 2;
    localparam DX_CINB = 3;
    localparam DX_CINH = 4;
    localparam DX_CIN = 5;
    localparam PX_NONE = 0;
    localparam PX_D_INDX = 1;
    localparam PX_Q = 2;
    localparam QX_NONE = 0;
    localparam QX_P = 1;
    localparam RRX_NONE = 0;
    localparam RRX_S = 1;
    localparam RRX_Q = 2;
    localparam COND_NONE = 0;
    localparam COND_S_GT_ZERO = 1;
    localparam COND_S_LT_ZERO = 2;
    localparam COND_CC_AND_R_ZERO = 3;
    localparam COND_C0_EQ_1 = 4;
    localparam COND_CIN0_EQ_1 = 5;
    localparam COND_E_NEQ_0 = 6;
    localparam ADDR_MUX_SEQ = 0;
    localparam ADDR_MUX_OPCODE = 1;
    localparam ADDR_MUX_OPROM = 2;
    localparam DIV_NONE = 0;
    localparam DIV_PREP = 1;
    localparam DIV_LOOP = 2;
    localparam DIV_POST = 3;
    localparam DIV_SAVE = 4;
    localparam MUL_NONE = 0;
    localparam MUL_PREP = 1;
    localparam MUL_LOOP = 2;
    localparam MUL_SAVE = 3;
    localparam WR_NONE = 0;
    localparam WR_BYTE = 1;
    localparam WR_HALF = 2;
    localparam WR_WORD = 3;

    // ---- END Pipeline definitions DO NOT EDIT

    reg branch;

    // Standard register configuration
    reg [0:31] a, b, d;
    // c is a transparent latch, see pp 3-38, receives data from memory
    reg [0:31] c;
    reg [0:31] c_in;
    // e is a counting register
    reg [0:7] e;
    // Condition code register
    reg [1:4] cc;
    // Carry save register
    reg [0:31] cs;
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
    // Divide LSB
    reg dw_lsb;

    // Address family decode, see ANLZ instruction
    wire fa_b = o[1] & o[2] & o[3];
    wire fa_h = o[1] & ~o[2] & o[3];
    wire ou3 = (~o[1]) & o[2] & o[3];
    wire fa_w = ou3 | (~o[3] & ~o[4] & o[5]) | (o[1] & ~o[3] & o[4]) | (o[2] & ~o[3] & o[4]); // pp 3-182
    wire [0:31] indx_offset = {32{(x[0] | x[1] | x[2])}} & rr[x];

    reg [11:0] op_switch[0:127];

    // Multiply logic
    reg bc31;
    reg [0:2] bpair;

    // Signals

    // Guideline #3: When modeling combinational logic with an "always" 
    //              block, use blocking assignments.
    // Order matters here!!!
    always @(*) begin
        // Sequencer d_in mux
        uc_din = seq_address;
        case (seq_address_mux)
            ADDR_MUX_SEQ: uc_din = seq_address; // jump or call
            ADDR_MUX_OPCODE: uc_din = { 3'h0, o, 2'h0 } + { 4'h0, o, 1'h0 }; // instruction op code
            ADDR_MUX_OPROM: uc_din = op_switch[o]; // instruction op code
        endcase
        s = 0;
        case (sxop)
            SX_ADD: s = a+d+cs;
            SX_SUB: s = a-d;
            SX_A: s = a;
            SX_D: s = d;
        endcase
        if (ia == 0) begin
            lb = p[15:31];
            c_in = memory_data_in;
            if (p[15:27] == 0) c_in = rr[p[28:31]];
        end else begin
            lb = c[15:31];
            c_in = memory_data_in;
            if (c[15:27] == 0) c_in = rr[c[28:31]];
        end
        // Multiply logic
        bpair = { 1'b0, b[28:29] } + { 2'b00, bc31 };
        // These cases must be at the end, as they depend on signals above!
        branch = 0;
        case (seq_condition)
            COND_NONE: branch = 0; // branch unconditionally
            COND_S_GT_ZERO: branch = ~(s[0] | (s == 0));
            COND_S_LT_ZERO: branch = s[0];
            COND_CC_AND_R_ZERO: branch = (cc & r) == 0;
            COND_C0_EQ_1: branch = c[0];
            COND_CIN0_EQ_1: branch = c_in[0];
            COND_E_NEQ_0: branch = e != 0;
        endcase
        uc_op = seq_op;
        case (seq_op)
            0: uc_op = { 1'h0, branch }; // next, invert selected branch condition
            1: uc_op = { 1'h0, ~branch }; // jump
            2: ; // call
            3: ; // return
        endcase
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
            cs <= 0;
            d <= 0;
            ia <= 0;
            o <= 0;
            p <= { 32'h26, 2'h0 }; // Boot location + 1, see 3-510 Bootstrap program
            q <= 0;
            r <= 0;
            for (i=0; i<16; i=i+1) rr[i] = 32'h00000000;
            e <= 0;
            x <= 0;
            dw_lsb <= 0;
            bc31 <= 0;
            pipeline <= 0;
            wr_enables <= 0;
        end else begin
            if (active) begin
                pipeline <= uc_rom_data;
                wr_enables <= 0;
                ia <= 0;
                if (ende == 1) begin
                    // ende entry: p contains next instruction byte address
                    `ifdef TRACE_I
                        $display("* Q %x: %x", q-1, c);
                        $display("  R0 %x %x %x %x %x %x %x %x", rr[0], rr[1], rr[2], rr[3], rr[4], rr[5], rr[6], rr[7]);
                        $display("  R8 %x %x %x %x %x %x %x %x", rr[8], rr[9], rr[10], rr[11], rr[12], rr[13], rr[14], rr[15]);
                    `endif
                    c <= c_in; d <= c_in; o <= c_in[1:7]; cs <= 0;
                    r <= c_in[8:11]; x <= c_in[12:14]; p <= p + 4;
                    // immediate value is sign extended and stored in d
                    if (~c_in[3] & ~c_in[4] & ~c_in[5]) begin
                        d <= { {12{c_in[12]}}, c_in[12:31] };
                    end else if (c_in[0] == 1) begin
                        ia <= 1;
                    end
                    // ende exit: c: instruction word, d: instruction word or immediate value, r: register number,
                    // x: index register, p: next instruction byte address, ia: indirect flag
                end
                if (ia == 1) begin
                    c <= c_in; d <= c_in; // indirect addressing mode: c, d contain indirect word, e.g. *c
                end
                case (ax)
                    AX_NONE: ; // do nothing
                    AX_S: a <= s;
                    AX_RR: a <= rr[r];
                    AX_0: a <= 32'h0;
                endcase
                case (dx)
                    DX_NONE: ; // do nothing
                    DX_0: d <= 32'h0;
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
                    RRX_Q: rr[r] <= q;
                endcase
                case (px)
                    PX_NONE: ; // do nothing
                    PX_D_INDX:
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
                case (write_size)
                    WR_NONE: ;
                    WR_BYTE:
                        case (p[32:33])
                            0: begin memory_data_out <= { s[24:31], 24'd0 }; wr_enables <= 4'b1000; end
                            1: begin memory_data_out <= { 8'd0, s[24:31], 16'd0 }; wr_enables <= 4'b0100; end
                            2: begin memory_data_out <= { 16'd0, s[24:31], 8'd0 }; wr_enables <= 4'b0010; end
                            3: begin memory_data_out <= { 24'd0, s[24:31] }; wr_enables <= 4'b0001; end
                        endcase
                    WR_HALF: ;
                    WR_WORD:
                        begin
                            memory_data_out <= s;
                            wr_enables <= 4'b1111;
                        end
                endcase
                case (divide)
                    DIV_NONE: ; // do nothing
                    DIV_PREP: begin
                        // a:b - 64 bit numerator
                        a <= { rr[r][1:31], 1'b0 };
                        b <= { rr[r|1][1:31], 1'b0 };
                        // c - 32 bit denominator
                        c <= c_in;
                        // $display("%d:%d/%d", rr[r], rr[r|1], c_in);
                        // Start with sign == 0
                        d <= ~c_in;
                        cs <= 32'h1;
                        dw_lsb <= 1;
                        e <= 32-2;
                    end
                    DIV_LOOP: begin
                        //$display("count: %d, a:b %x:%x, d: %x, cs: %x", e, a, b, d, cs);
                        a <= { s[1:31], b[0] };
                        b <= { b[1:31], dw_lsb };
                        if (s[0] == 0) begin
                            d <= ~c;
                            cs <= 32'h1;
                            dw_lsb <= 1;
                        end else begin
                            d <= c;
                            cs <= 0;
                            dw_lsb <= 0;
                        end
                        e <= e - 1;
                    end
                    DIV_POST: begin
                        //$display("count: %d, a:b %x:%x, d: %x, cs: %x", e, a, b, d, cs);
                        a <= { s[0:31] };
                        b <= { b[2:31], dw_lsb, ~s[0] };
                        d <= 0;
                        cs <= 0;
                        if (s[0] == 1) begin
                            d <= c;
                        end
                    end
                    DIV_SAVE: begin
                        rr[r] <= s; // remainder
                        rr[r|1] <= b; // quotient
                        // $display("quotient: %d, rem: %d", b, s);
                    end
                endcase
                case (multiply)
                    MUL_NONE: ; // do nothing
                    MUL_PREP: begin
                        // $display("%d x %d", rr[r], d);
                        a <= 0;
                        b <= rr[r];
                        c <= d;
                        bc31 <= 0;
                        case (rr[r][30:31])
                            0: begin d <= 0; cs <= 0; end
                            1: begin d <= d; cs <= 0; end
                            2: begin d <= { d[1:31], 1'b0 }; cs <= 0; end
                            3: begin d <= ~d;  cs <= 1; bc31 <= 1; end
                        endcase
                        e <= (32 >> 1) - 1;
                    end
                    MUL_LOOP: begin
                        // $display("e: %d, a:b %x:%x, d: %x, cs: %x, s: %x, bpair: %x, bc31: %x", e, a, b, d, cs, s, bpair, bc31);
                        a <= { {2{s[0]}}, s[0:29] };
                        b <= { s[30:31], b[0:29] };
                        bc31 <= bpair[0] | (bpair[1] & bpair[2]);
                        case (bpair & 3)
                            0: begin d <= 0; cs <= 0; end
                            1: begin d <= c; cs <= 0; end
                            2: begin d <= { c[1:31], 1'b0 }; cs <= 0; end
                            3: begin d <= ~c;  cs <= 1; end
                        endcase
                        e <= e - 1;
                    end
                    MUL_SAVE: begin
                        // $display("a:b %d:%d, d: %x, cs: %x, s: %x, bpair: %x, bc31: %x", a, b, d, cs, s, bpair, bc31);
                        rr[r] <= a;
                        rr[r | 1] <= b;
                    end
                endcase
                if (testa == 1) begin cc[3] <= (~a[0]) & (a != 0); cc[4] <= a[0]; end
                if (wd_en == 1) begin
                    // $display("wd_en, d[24:31] = %x, r = %x, rr[r][25:31]", d[24:31], r, rr[r][25:31]);
                    if ((d[24:31] == 0) && (r != 0)) begin
                        $write("%s", rr[r][25:31]);
                    end
                end
                if (uc_debug == 1) begin
                    $display("%4d: q: %x, p[15:31]: %x, c_in: %x, s: %x, fa_b: %x, indx_offset: %x, x: %x, ia: %x, branch: %x",
                        seq.pc-1, q, p[15:31], c_in, s, fa_b, indx_offset, x, ia, branch);
                    //$stop;
                end
            end
        end
    end
endmodule
