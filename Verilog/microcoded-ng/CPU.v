
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

    // Microcode ROM(s)
    wire [0:11] uc_rom_address;
    wire [0:55] uc_rom_data;
    CodeROM uc_rom(uc_rom_address, uc_rom_data);
    // Microcode sequencer
    reg [0:1] uc_op;
    reg [0:11] uc_din;
    Sequencer seq(reset, clock, active, uc_op, uc_din, uc_rom_address);

    // ---- BEGIN Pipeline definitions DO NOT EDIT

    // Microcode pipeline register
    // 0       8       16      24      32      40      48      56      
    // |-------|-------|-------|-------|-------|-------|-------|
    // || - seq_op[0:1] 2 bits
    //   || - seq_address_mux[2:3] 2 bits
    //     |__| - seq_condition[4:7] 4 bits
    //         |_| - ax[8:10] 3 bits
    // |-------|-------|-------|-------|-------|-------|-------|
    //            || - bx[11:12] 2 bits
    //              |_| - cx[13:15] 3 bits
    //                 |_| - dx[16:18] 3 bits
    //                    |_| - ex[19:21] 3 bits
    // |-------|-------|-------|-------|-------|-------|-------|
    //                       | - ox[22]
    //                        |_| - px[23:25] 3 bits
    //                           || - qx[26:27] 2 bits
    //                             | - rrx[28]
    // |-------|-------|-------|-------|-------|-------|-------|
    //                              |__| - sx[29:32] 4 bits
    //                                  | - ende[33]
    //                                   | - testa[34]
    //                                    | - wd_en[35]
    // |-------|-------|-------|-------|-------|-------|-------|
    //                                     | - trap[36]
    //                                      | - uc_debug[37]
    //                                       || - write_size[38:39] 2 bits
    //                                         |__| - __unused[40:43] 4 bits
    // |-------|-------|-------|-------|-------|-------|-------|
    //                                             |__________| - seq_address[44:55] 12 bits
    //                                             |__________| - _const12[44:55] 12 bits

    reg [0:55] pipeline;
    wire [0:1] seq_op = pipeline[0:1];
    wire [0:1] seq_address_mux = pipeline[2:3];
    wire [0:3] seq_condition = pipeline[4:7];
    wire [0:2] ax = pipeline[8:10];
    wire [0:1] bx = pipeline[11:12];
    wire [0:2] cx = pipeline[13:15];
    wire [0:2] dx = pipeline[16:18];
    wire [0:2] ex = pipeline[19:21];
    wire ox = pipeline[22];
    wire [0:2] px = pipeline[23:25];
    wire [0:1] qx = pipeline[26:27];
    wire rrx = pipeline[28];
    wire [0:3] sx = pipeline[29:32];
    wire ende = pipeline[33];
    wire testa = pipeline[34];
    wire wd_en = pipeline[35];
    wire trap = pipeline[36];
    wire uc_debug = pipeline[37];
    wire [0:1] write_size = pipeline[38:39];
    wire [0:3] __unused = pipeline[40:43];
    wire [0:11] seq_address = pipeline[44:55];
    wire [0:11] _const12 = pipeline[44:55];
    
    localparam AXNONE = 0;
    localparam AXCONST = 1;
    localparam AXE = 2;
    localparam AXR = 3;
    localparam AXRR = 4;
    localparam AXS = 5;
    localparam BXNONE = 0;
    localparam BXCONST = 1;
    localparam BXS = 2;
    localparam CXNONE = 0;
    localparam CXCONST = 1;
    localparam CXMB = 2;
    localparam CXRR = 3;
    localparam CXS = 4;
    localparam DXNONE = 0;
    localparam DXCONST = 1;
    localparam DXC = 2;
    localparam DXCC = 3;
    localparam DXNC = 4;
    localparam DXPSW1 = 5;
    localparam DXPSW2 = 6;
    localparam EXNONE = 0;
    localparam EXCONST = 1;
    localparam EXB = 1;
    localparam EXCC = 2;
    localparam EXS = 3;
    localparam OXNONE = 0;
    localparam OXC = 1;
    localparam PXNONE = 0;
    localparam PXCONST = 1;
    localparam PXQ = 2;
    localparam PXS = 3;
    localparam PCTP1 = 4;
    localparam QXNONE = 0;
    localparam QXCONST = 1;
    localparam QXP = 2;
    localparam RRXNONE = 0;
    localparam RRXS = 1;
    localparam SXPLUS = 0;
    localparam SXXOR = 1;
    localparam SXOR = 2;
    localparam SXAND = 3;
    localparam SXMA = 4;
    localparam SXMD = 5;
    localparam SXUAB = 6;
    localparam SXUAH = 7;
    localparam SXUDB = 8;
    localparam SXUDH = 9;
    localparam SXA = 10;
    localparam SXB = 11;
    localparam SXD = 12;
    localparam SXP = 13;
    localparam ADDR_MUX_SEQ = 0;
    localparam ADDR_MUX_OPCODE = 1;
    localparam ADDR_MUX_OPROM = 2;
    localparam COND_NONE = 0;
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
    // sum bus
    reg [0:31] s;
    // private memory index register number
    reg [0:2] x;

    // memory address lines
    reg [15:31] lb;
    // memory output data
    reg [0:31] mem_out;
    // memory write enables
    reg [0:3] wr_en;

    assign memory_address = active ? lb : 17'bZ;
    assign memory_data_out = active ? mem_out : 32'bZ;
    assign wr_enables = active ? wr_en : 4'bZ;

    // Address family decode, see ANLZ instruction
    wire fa_b = o[1] & o[2] & o[3];
    wire fa_h = o[1] & ~o[2] & o[3];
    wire ou3 = (~o[1]) & o[2] & o[3];
    wire fa_w = ou3 | (~o[3] & ~o[4] & o[5]) | (o[1] & ~o[3] & o[4]) | (o[2] & ~o[3] & o[4]); // pp 3-182
    wire [0:31] indx_offset = {32{(x[0] | x[1] | x[2])}} & rr[x];

    wire [0:31] constant32 = { {20{_const12[0]}}, _const12[0:11] };

    reg [11:0] op_switch[0:127];

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
        case (sx)
            SXPLUS: s = a+d+cs;
        endcase
        branch = 0;
        case (seq_condition)
            COND_NONE: branch = 0; // branch unconditionally
        endcase
        uc_op = seq_op;
        case (seq_op)
            0: uc_op = { 1'h0, branch }; // next, invert selected branch condition
            1: uc_op = { 1'h0, ~branch }; // jump
            2: uc_op = { ~branch, 1'h0 }; // call
            3: uc_op = { ~branch, ~branch }; // return
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
            o <= 0;
            p <= { 32'h26, 2'h0 }; // Boot location + 1, see 3-510 Bootstrap program
            q <= 0;
            r <= 0;
            for (i=0; i<16; i=i+1) rr[i] = 32'h00000000;
            e <= 0;
            x <= 0;
            pipeline <= 0;
            wr_en <= 0;
        end else begin
            if (active) begin
                pipeline <= uc_rom_data;
                wr_en <= 0;
                if (ende == 1) begin
                    // ende entry: p contains next instruction byte address
                    `ifdef TRACE_I
                        $display("* Q %x: %x", q-1, c);
                        $display("  R0 %x %x %x %x %x %x %x %x", rr[0], rr[1], rr[2], rr[3], rr[4], rr[5], rr[6], rr[7]);
                        $display("  R8 %x %x %x %x %x %x %x %x", rr[8], rr[9], rr[10], rr[11], rr[12], rr[13], rr[14], rr[15]);
                    `endif
                end
                case (ax)
                    AXNONE: ; // do nothing
                    AXCONST: a <= constant32;
                    AXS: a <= s;
                endcase
                case (dx)
                    DXNONE: ; // do nothing
                    DXCONST: d <= constant32;
                endcase
                case (ox)
                    OXNONE: ; // do nothing
                endcase
                if (uc_debug == 1) begin
                    $display("%4d: a: %x",
                        seq.pc-1, a);
                end
            end
        end
    end
endmodule
