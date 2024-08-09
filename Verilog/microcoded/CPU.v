
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
    localparam AX_NONE = 0;
    localparam AX_S = 1;
    localparam AX_RR = 2;
    localparam DX_NONE = 0;
    localparam DX_1 = 1;
    localparam PX_NONE = 0;
    localparam PX_D = 1;
    localparam PX_Q = 2;
    localparam QX_NONE = 0;
    localparam QX_P = 1;
    localparam RRX_NONE = 0;
    localparam RRX_S = 1;

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
            SX_ADD: s = a+d;
            SX_SUB: s = a-d;
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
            if (ende == 1) begin
                c <= c_in; d <= c_in; o <= c_in[1:7]; r <= c_in[8:11]; p <= p + 1; a <= 0;
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
            endcase
            case (rrx)
                RRX_NONE: ; // do nothing
                RRX_S: rr[r] <= s;
            endcase
            case (px)
                PX_NONE: ; // do nothing
                PX_D: p <= d[15:31];
                PX_Q: p <= q;
            endcase
            case (qx)
                QX_NONE: ; // do nothing
                QX_P: q <= p;
            endcase
            if (testa == 1) begin cc[3] <= (~a[0]) & (a != 0); cc[4] <= a[0]; end
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
