
`include "Sequencer.v"

// `define TRACE_I 1

/*
Memory is word addressed, 17 bits
*/
module CPU(input wire reset, input wire clock, input wire [0:31] memory_data_in,
    output wire [15:31] memory_address, output reg [0:31] memory_data_out, output reg [0:3] wr_enables);
    assign memory_address = lb;

    reg ende;
    reg testa;
    reg wd_en;
    reg trap;
    reg [0:2] px;
    reg [0:3] sxop;
    
    localparam SX_ADD = 0;
    localparam SX_SUB = 1;
    localparam SX_A = 2;
    localparam SX_D = 3;
    localparam WR_NONE = 0;
    localparam WR_BYTE = 1;
    localparam WR_HALF = 2;
    localparam WR_WORD = 3;
    localparam DIV_NONE = 0;
    localparam DIV_PREP = 1;
    localparam DIV_LOOP = 2;
    localparam DIV_POST = 3;
    localparam DIV_SAVE = 4;
    localparam MUL_NONE = 0;
    localparam MUL_PREP = 1;
    localparam MUL_LOOP = 2;
    localparam MUL_SAVE = 3;
    localparam PX_NONE = 0;
    localparam PX_D_INDX = 1;
    localparam PX_Q = 2;

    reg [31:0] phase;
    assign ph1 = phase[0];
    assign ph2 = phase[1];
    assign ph3 = phase[2];
    assign ph4 = phase[3];
    assign ph5 = phase[4];
    assign ph6 = phase[5];
    assign ph7 = phase[6];
    assign ph8 = phase[7];

    assign ph9  = phase[8];
    assign ph10 = phase[9];
    assign ph11 = phase[10];
    assign ph12 = phase[11];
    assign ph13 = phase[12];
    assign ph14 = phase[13];
    assign ph15 = phase[14];
    assign ph16 = phase[15];
 
    assign prep1 = phase[16];
    assign prep2 = phase[17];
    assign prep3 = phase[18];
    assign prep4 = phase[19];
 
    assign pcp1 = phase[24];
    assign pcp2 = phase[25];
    assign pcp3 = phase[26];
    assign pcp4 = phase[27];
 
    parameter PH1 = 1<<0, PH2 = 1<<1, PH3 = 1<<2, PH4 = 1<<3, PH5 = 1<<4, PH6 = 1<<5, PH7 = 1<<6, PH8 = 1<<7;
    parameter PH9 = 1<<8, PH10 = 1<<9, PH11 = 1<<10, PH12 = 1<<11, PH13 = 1<<12, PH14 = 1<<13, PH15 = 1<<14, PH16 = 1<<15;
    parameter PREP1 = 1<<16, PREP2 = 1<<17, PREP3 = 1<<18, PREP4 = 1<<19;
    parameter PCP1 = 1<<24, PCP2 = 1<<25, PCP3 = 1<<26, PCP4 = 1<<27;

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

    // Multiply logic
    reg bc31;
    reg [0:2] bpair;

    reg [0:2] divide;
    reg [0:1] multiply;
    reg [0:1] write_size;

    // Signals

    // Guideline #3: When modeling combinational logic with an "always" 
    //              block, use blocking assignments.
    // Order matters here!!!
    always @(*) begin
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
            p <= { 32'h25, 2'h0 };
            q <= 0;
            r <= 0;
            for (i=0; i<16; i=i+1) rr[i] = 32'h00000000;
            e <= 0;
            x <= 0;
            dw_lsb <= 0;
            bc31 <= 0;
            wr_enables <= 0;
            sxop <= SX_ADD;
            phase <= PCP1;
            ende <= 0;
            testa <= 0;
        end else begin
            wr_enables <= 0;
            if (pcp1) begin
                ende <= 1;
            end
            if (prep1) begin
                // $display("phase: %x, ia: %x, PREP2: %x\n", phase, ia, PREP2);
                if (ia == 0) phase <= PREP2;
            end
            if (prep2) begin
                a <= rr[r];
                q <= p[15:31];
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
                phase <= PH1;
            end

            // LI
            if (ph1 & (o == OP_LI)) begin
                // a contains register value, d contains immediate value
                p[15:33] <= { q, 2'h0 };
                sxop <= SX_D; a <= s; rr[r] <= s;
                phase <= PH2;
            end
            if (ph2 & (o == OP_LI)) begin
                testa <= 1; ende <= 1;
            end

            // BAL
            if (ph1 & (o == OP_BAL)) begin
                rr[r] <= q; ende <= 1;
            end

            // LB
            if (ph1 & (o == OP_LB)) begin
                // a contains register value, d contains immediate value
                case (p[32:33])
                    0: d <= { 24'h0, c_in[0:7] };
                    1: d <= { 24'h0, c_in[8:15] };
                    2: d <= { 24'h0, c_in[16:23] };
                    3: d <= { 24'h0, c_in[24:31] };
                endcase
                phase <= PH2;
            end
            if (ph2 & (o == OP_LB)) begin
                sxop <= SX_D; a <= s; rr[r] <= s;
                p[15:33] <= { q, 2'h0 };
                phase <= PH3;
            end
            if (ph3 & (o == OP_LB)) begin
                testa <= 1; ende <= 1;
            end

            if (ende == 1) begin
                ende <= 0;
                // ende entry: p contains next instruction byte address
                `ifdef TRACE_I
                    $display("* Q %x: %x", q-1, c);
                    $display("  R0 %x %x %x %x %x %x %x %x", rr[0], rr[1], rr[2], rr[3], rr[4], rr[5], rr[6], rr[7]);
                    $display("  R8 %x %x %x %x %x %x %x %x", rr[8], rr[9], rr[10], rr[11], rr[12], rr[13], rr[14], rr[15]);
                `endif
                c <= c_in; d <= c_in; o <= c_in[1:7]; cs <= 0;
                r <= c_in[8:11]; x <= c_in[12:14]; p <= p + 4;
                // immediate value is sign extended and stored in d
                phase <= PREP2;
                if (~c_in[3] & ~c_in[4] & ~c_in[5]) begin
                    d <= { {12{c_in[12]}}, c_in[12:31] };
                end else if (c_in[0] == 1) begin
                    ia <= 1;
                    phase <= PREP1;
                end
                // ende exit: c: instruction word, d: instruction word or immediate value, r: register number,
                // x: index register, p: next instruction byte address, ia: indirect flag
            end
            if (ia == 1) begin
                c <= c_in; d <= c_in; // indirect addressing mode: c, d contain indirect word, e.g. *c
                ia <= 0;
            end
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
        end
    end

    parameter OP_LCFI = 7'h02;
    parameter OP_CAL1 = 7'h04;
    parameter OP_CAL2 = 7'h05;
    parameter OP_CAL3 = 7'h06;
    parameter OP_CAL4 = 7'h07;
    parameter OP_PLW = 7'h08;
    parameter OP_PSW = 7'h09;
    parameter OP_PLM = 7'h0A;
    parameter OP_PSM = 7'h0B;
    parameter OP_LPSD = 7'h0E;
    parameter OP_XPSD = 7'h0F;
    parameter OP_AD = 7'h10;
    parameter OP_CD = 7'h11;
    parameter OP_LD = 7'h12;
    parameter OP_MSP = 7'h13;
    parameter OP_STD = 7'h15;
    parameter OP_SD = 7'h18;
    parameter OP_CLM = 7'h19;
    parameter OP_LCD = 7'h1A;
    parameter OP_LAD = 7'h1B;
    parameter OP_FSL = 7'h1C;
    parameter OP_FAL = 7'h1D;
    parameter OP_FDL = 7'h1E;
    parameter OP_FML = 7'h1F;
    parameter OP_AI = 7'h20;
    parameter OP_CI = 7'h21;
    parameter OP_LI = 7'h22;
    parameter OP_MI = 7'h23;
    parameter OP_SF = 7'h24;
    parameter OP_S = 7'h25;
    parameter OP_CVS = 7'h28;
    parameter OP_CVA = 7'h29;
    parameter OP_LM = 7'h2A;
    parameter OP_STM = 7'h2B;
    parameter OP_WAIT = 7'h2E;
    parameter OP_LRP = 7'h2F;
    parameter OP_AW = 7'h30;
    parameter OP_CW = 7'h31;
    parameter OP_LW = 7'h32;
    parameter OP_MTW = 7'h33;
    parameter OP_STW = 7'h35;
    parameter OP_DW = 7'h36;
    parameter OP_MW = 7'h37;
    parameter OP_SW = 7'h38;
    parameter OP_CLR = 7'h39;
    parameter OP_LCW = 7'h3A;
    parameter OP_LAW = 7'h3B;
    parameter OP_FSS = 7'h3C;
    parameter OP_FAS = 7'h3D;
    parameter OP_FDS = 7'h3E;
    parameter OP_FMS = 7'h3F;
    parameter OP_TTBS = 7'h40;
    parameter OP_TBS = 7'h41;
    parameter OP_ANLZ = 7'h44;
    parameter OP_CS = 7'h45;
    parameter OP_XW = 7'h46;
    parameter OP_STS = 7'h47;
    parameter OP_EOR = 7'h48;
    parameter OP_OR = 7'h49;
    parameter OP_LS = 7'h4A;
    parameter OP_AND = 7'h4B;
    parameter OP_SIO = 7'h4C;
    parameter OP_TIO = 7'h4D;
    parameter OP_TDV = 7'h4E;
    parameter OP_HIO = 7'h4F;
    parameter OP_AH = 7'h50;
    parameter OP_CH = 7'h51;
    parameter OP_LH = 7'h52;
    parameter OP_MTH = 7'h53;
    parameter OP_STH = 7'h55;
    parameter OP_DH = 7'h56;
    parameter OP_MH = 7'h57;
    parameter OP_SH = 7'h58;
    parameter OP_LCH = 7'h5A;
    parameter OP_LAH = 7'h5B;
    parameter CBS = 7'h60;
    parameter OP_MBS = 7'h61;
    parameter OP_EBS = 7'h63;
    parameter OP_BDR = 7'h64;
    parameter OP_BIR = 7'h65;
    parameter OP_AWM = 7'h66;
    parameter OP_EXU = 7'h67;
    parameter OP_BCR = 7'h68;
    parameter OP_BCS = 7'h69;
    parameter OP_BAL = 7'h6A;
    parameter OP_INT = 7'h6B;
    parameter OP_RD = 7'h6C;
    parameter OP_WD = 7'h6D;
    parameter OP_AIO = 7'h6E;
    parameter OP_MMC = 7'h6F;
    parameter OP_LCF = 7'h70;
    parameter OP_CB = 7'h71;
    parameter OP_LB = 7'h72;
    parameter OP_MTB = 7'h73;
    parameter OP_STFC = 7'h74;
    parameter OP_STB = 7'h75;
    parameter OP_PACK = 7'h76;
    parameter OP_UNPK = 7'h77;
    parameter OP_DS = 7'h78;
    parameter OP_DA = 7'h79;
    parameter OP_DD = 7'h7A;
    parameter OP_DM = 7'h7B;
    parameter OP_DSA = 7'h7C;
    parameter OP_DC = 7'h7D;
    parameter OP_DL = 7'h7E;
    parameter OP_DST = 7'h7F;
endmodule
