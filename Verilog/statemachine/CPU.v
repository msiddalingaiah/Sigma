
/*
 A non-canonical implementation of Sigma7
 - Not cycle accurate
 - Similar internal registers
 */
module CPU(input wire reset, input wire clock, input wire [0:31] memory_data_in, output wire [15:31] memory_address,
    output reg [0:31] memory_data_out, output reg [0:3] wr_enables);
    assign memory_address = lb;
    // a is one input to the adder, hold private memory register operand
    reg [0:31] a;
    // b is the least significant word in doubleword operations
    reg [0:31] b;
    // c is a transparent latch, see pp 3-38, receives data from memory
    reg [0:31] c;
    // d is the other input to the adder, holds memory operand
    reg [0:31] d;
    // e is a counting register
    reg [0:7] e;
    // Condition code register
    reg [0:3] cc;
    // carry inputs to the adder
    reg [0:31] cs;
    // Indirect addressing flip flop
    reg ia;
    // Index register pointer
    reg [0:2] indx;

    // Memory address lines
    reg [15:31] lb;
    // o holds the current opcode
    reg [1:7] o;
    // p is a counting register, acts as the program counter in conjunction with q
    reg [15:33] p;
    // Phase register, one-hot encoded
    reg [0:7] phase;
    // q holds the next instruction address
    reg [15:31] q;
    // private memory address (register number), pctr counts up, mctr counts down
    reg [0:3] r;
    // private memory registers
    reg [0:31] rr[0:15];
    // Sum bus
    reg [0:31] s;
    // Sum bus function
    reg [0:3] sf;

    // Memory address select
    reg [0:1] mem_select;

    // Divide LSB
    reg dw_lsb;

    parameter MEM_SEL_C = 0;
    parameter MEM_SEL_P = 1;
    parameter MEM_SEL_Q = 2;
    parameter MEM_SEL_S = 3;

    parameter SF_ADD = 0;
    parameter SF_SUB = 1;
    parameter SF_AND = 2;
    parameter SF_OR = 3;
    parameter SF_XOR = 4;
    parameter SF_LSR = 5;
    parameter SF_ASR = 6;
    parameter SF_LSL = 7;

    // Flip flops
    reg ende;

    parameter PRE1 = 8'h11, PRE2 = 8'h12, PRE3 = 8'h13, PRE4 = 8'h14;
    parameter PH1 = 8'h01, PH2 = 8'h02, PH3 = 8'h03, PH4 = 8'h04, PH5 = 8'h05, PH6 = 8'h06;
    parameter PCP1 = 8'h21, PCP2 = 8'h22, PCP3 = 8'h23, PCP4 = 8'h24, PCP5 = 8'h25;

    // Guideline #3: When modeling combinational logic with an "always" 
    //              block, use blocking assignments.
    always @(*) begin
        case (sf)
            SF_ADD: s = a + d + cs;
            SF_AND: s = a & d;
            SF_OR: s = a | d;
            SF_XOR: s = a ^ d;
            SF_LSR: s = { 1'h0, a[0:30] };
            SF_ASR: s = { a[0], a[0:30] };
            SF_LSL: s = { a[1:31], 1'h0 };
            default: s = 0;
        endcase

        case (mem_select)
            MEM_SEL_C: lb = c[15:31];
            MEM_SEL_P: lb = p[15:31];
            MEM_SEL_Q: lb = q[15:31];
            MEM_SEL_S: lb = s[15:31];
        endcase
    end

    task automatic exec_AD; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_AH; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_AI; begin
        case (phase)
            PH1: begin
                `ifdef TRACE_I
                    $display("AI,%d %x", r, d);
                `endif
                a <= rr[r];
                cs <= 0;
                sf <= SF_ADD;
                phase <= PH2;
            end
            PH2: begin
                rr[r] <= s;
                p[15:31] <= q[15:31];
                mem_select <= MEM_SEL_Q; ende <= 1; phase <= PH3;
            end
            default: begin
            end
        endcase
    end endtask;

    task automatic exec_AIO; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_AND; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_ANLZ; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_AW; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_AWM; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_BAL; begin
        if (phase == PH1) begin
            `ifdef TRACE_I
                $display("BAL,%d %x", r, p[15:31]);
            `endif
            rr[r] <= q;
            q[15:31] <= p[15:31];
            mem_select <= MEM_SEL_Q; ende <= 1; phase <= PH2;
        end
    end endtask;

    task automatic exec_BCR; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_BCS; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_BDR; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_BIR; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_CAL1; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_CAL2; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_CAL3; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_CAL4; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_CB; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_CBS; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_CD; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_CH; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_CI; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_CLM; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_CLR; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_CS; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_CVA; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_CVS; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_CW; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_DA; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_DC; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_DD; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_DH; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_DL; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_DM; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_DS; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_DSA; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_DST; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_DW; begin
        case (phase)
            PH1: begin
                `ifdef TRACE_I
                    $display("DW,%d %x (%x)", r, p[15:31], memory_data_in);
                `endif
                a <= { rr[r][1:31], 1'b0 };
                b <= { rr[r|1][1:31], 1'b0 };
                c <= memory_data_in;
                //$display("%d:%d/%d", rr[r], rr[r|1], memory_data_in);
                // Start with sign == 0
                d <= ~memory_data_in;
                cs <= 32'h1;
                sf <= SF_ADD;
                dw_lsb <= 1;
                e <= 32-2;
                phase <= PH2;
            end

            PH2: begin
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
                if (e == 0) phase <= PH3;
            end

            PH3: begin
                //$display("count: %d, a:b %x:%x, d: %x, cs: %x", e, a, b, d, cs);
                a <= { s[0:31] };
                b <= { b[2:31], dw_lsb, ~s[0] };
                d <= 0;
                cs <= 0;
                if (s[0] == 1) begin
                    d <= c;
                end
                phase <= PH4;
            end

            PH4: begin
                rr[r] <= s; // remainder
                rr[r|1] <= b; // quotient
                //$display("quotient: %d, rem: %d", b, s);
                p[15:31] <= q[15:31];
                mem_select <= MEM_SEL_Q; ende <= 1; phase <= PH5;
            end
        endcase
    end endtask;

    task automatic exec_EBS; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_EOR; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_EXU; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_FAL; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_FAS; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_FDL; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_FDS; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_FML; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_FMS; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_FSL; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_FSS; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_HIO; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_INT; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_LAD; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_LAH; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_LAW; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_LB; begin
        if (phase == PH1) begin
            `ifdef TRACE_I
                $display("LB,%d %x + %x", r, p[15:31], p[32:33]);
            `endif
            case (p[32:33])
                0: rr[r] <= { 24'd0, memory_data_in[0:7] };
                1: rr[r] <= { 24'd0, memory_data_in[8:15] };
                2: rr[r] <= { 24'd0, memory_data_in[16:23] };
                3: rr[r] <= { 24'd0, memory_data_in[24:31] };
            endcase
            p[15:31] <= q[15:31];
            mem_select <= MEM_SEL_Q; ende <= 1; phase <= PH2;
        end
    end endtask;

    task automatic exec_LCD; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_LCF; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_LCFI; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_LCH; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_LCW; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_LD; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_LH; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_LI; begin
        if (phase == PH1) begin
            `ifdef TRACE_I
                $display("LI,%d %x", r, d);
            `endif
            rr[r] <= d;
            p[15:31] <= q[15:31];
            mem_select <= MEM_SEL_Q; ende <= 1; phase <= PH2;
        end
    end endtask;

    task automatic exec_LM; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_LPSD; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_LRP; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_LS; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_LW; begin
        if (phase == PH1) begin
            `ifdef TRACE_I
                $display("LW,%d %x (%x)", r, p[15:31], memory_data_in);
            `endif
            rr[r] <= memory_data_in;
            p[15:31] <= q[15:31];
            mem_select <= MEM_SEL_Q; ende <= 1; phase <= PH2;
        end
    end endtask;

    task automatic exec_MBS; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_MH; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_MI; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_MMC; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_MSP; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_MTB; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_MTH; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_MTW; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_MW; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_OR; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_PACK; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_PLM; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_PLW; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_PSM; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_PSW; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_RD; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_S; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_SD; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_SF; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_SH; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_SIO; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_STB; begin
        case (phase)
            PH1: begin
                `ifdef TRACE_I
                    $display("STB,%d %x+%x (%x)", r, p[15:31], p[32:33], rr[r][24:31]);
                `endif
                case (p[32:33])
                    0: begin memory_data_out <= { rr[r][24:31], 24'd0 }; wr_enables <= 4'b1000; end
                    1: begin memory_data_out <= { 8'd0, rr[r][24:31], 16'd0 }; wr_enables <= 4'b0100; end
                    2: begin memory_data_out <= { 16'd0, rr[r][24:31], 8'd0 }; wr_enables <= 4'b0010; end
                    3: begin memory_data_out <= { 24'd0, rr[r][24:31] }; wr_enables <= 4'b0001; end
                endcase
                mem_select <= MEM_SEL_P;
                phase <= PH2;
            end

            PH2: begin
                wr_enables <= 0;
                p[15:31] <= q[15:31];
                mem_select <= MEM_SEL_Q; ende <= 1; phase <= PH3;
            end
        endcase
    end endtask;

    task automatic exec_STD; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_STFC; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_STH; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_STM; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_STS; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_STW; begin
        case (phase)
            PH1: begin
                `ifdef TRACE_I
                    $display("STW,%d %x (%x)", r, p[15:31], rr[r]);
                `endif
                mem_select <= MEM_SEL_P;
                memory_data_out <= rr[r];
                wr_enables <= 4'b1111;
                phase <= PH2;
            end

            PH2: begin
                wr_enables <= 0;
                p[15:31] <= q[15:31];
                mem_select <= MEM_SEL_Q; ende <= 1; phase <= PH3;
            end
        endcase
    end endtask;

    task automatic exec_SW; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_TBS; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_TDV; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_TIO; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_TTBS; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_UNPK; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_WAIT; begin
        if (phase == PH1) begin
            `ifdef TRACE_I
                $display("WAIT %x (%x)", p[15:31], memory_data_in);
            `endif
            phase <= PCP2;
        end
    end endtask;

    task automatic exec_WD; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_XPSD; begin
        phase <= PCP2;
    end endtask;

    task automatic exec_XW; begin
        phase <= PCP2;
    end endtask;

    // Guideline #1: When modeling sequential logic, use nonblocking 
    //              assignments.
    integer i;
    always @(posedge clock, posedge reset) begin
        if (reset == 1) begin
            a <= 0;
            b <= 0;
            c <= 0;
            cs <= 0;
            d <= 0;
            ia <= 0;
            o <= 0;
            p <= 0;
            q <= 0;
            r <= 0;
            e <= 0;
            dw_lsb <= 0;
            ende <= 0;
            wr_enables <= 0;
            begin
                for (i=0; i<16; i=i+1) rr[i] = 32'h00000000;
            end
            phase <= PCP1;
            mem_select = MEM_SEL_Q;
        end else begin
            wr_enables <= 0;
            case (phase)
                PRE1: begin
                    q[15:31] <= p[15:31];
                    mem_select <= MEM_SEL_S;
                    if (o == LI || o == AI) begin
                        d <= { {13{c[12]}}, c[13:31] };
                        phase <= PH1;
                    end else begin
                        ia <= c[0];
                        indx <= d[12:14];
                        mem_select <= MEM_SEL_C;
                        phase <= PRE2;
                    end
                end
                PRE2: begin
                    if (ia == 1) begin
                        c <= memory_data_in[0:31];
                        d <= memory_data_in[0:31];
                        phase <= PRE3;
                    end
                    if (indx != 0) begin
                        a <= rr[indx];
                        if (o == LB || o == STB) begin
                            a <= { 2'b00, rr[indx][0:29] };
                            p[32:33] <= rr[indx][30:31];
                        end
                    end else begin
                        a <= 0;
                    end
                    sf <= SF_ADD;
                    phase <= PRE3;
                end
                PRE3: begin
                    mem_select = MEM_SEL_P;
                    p[15:31] <= s[15:31];
                    phase <= PH1;
                end
                PRE4: begin
                end

                PCP1: begin
                    $display("Compute: RUN");
                    ende <= 1;
                end

                PCP2: begin
                    // Compute to IDLE, not exactly, see 3-651
                    $display("Compute: IDLE");
                end

                default: begin
                end
            endcase

            if (ende == 1) begin
                `ifdef TRACE_I
                    $display("* Q %x: %x", q, memory_data_in);
                    $display("  R0 %x %x %x %x %x %x %x %x", rr[0], rr[1], rr[2], rr[3], rr[4], rr[5], rr[6], rr[7]);
                    $display("  R8 %x %x %x %x %x %x %x %x", rr[8], rr[9], rr[10], rr[11], rr[12], rr[13], rr[14], rr[15]);
                `endif
                a <= 0;
                c <= memory_data_in[0:31];
                o[1:7] <= memory_data_in[1:7];
                r[0:3] <= memory_data_in[8:11];
                d[0:31] <= memory_data_in[0:31];
                p <= p + 4;
                ende <= 0;
                phase <= PRE1;
            end

            // d = signed extended immediate value
            // p = effective address
            // r = register
            // indx = index register

            case (o)
                AD: exec_AD;
                AH: exec_AH;
                AI: exec_AI;
                AIO: exec_AIO;
                AND: exec_AND;
                ANLZ: exec_ANLZ;
                AW: exec_AW;
                AWM: exec_AWM;
                BAL: exec_BAL;
                BCR: exec_BCR;
                BCS: exec_BCS;
                BDR: exec_BDR;
                BIR: exec_BIR;
                CAL1: exec_CAL1;
                CAL2: exec_CAL2;
                CAL3: exec_CAL3;
                CAL4: exec_CAL4;
                CB: exec_CB;
                CBS: exec_CBS;
                CD: exec_CD;
                CH: exec_CH;
                CI: exec_CI;
                CLM: exec_CLM;
                CLR: exec_CLR;
                CS: exec_CS;
                CVA: exec_CVA;
                CVS: exec_CVS;
                CW: exec_CW;
                DA: exec_DA;
                DC: exec_DC;
                DD: exec_DD;
                DH: exec_DH;
                DL: exec_DL;
                DM: exec_DM;
                DS: exec_DS;
                DSA: exec_DSA;
                DST: exec_DST;
                DW: exec_DW;
                EBS: exec_EBS;
                EOR: exec_EOR;
                EXU: exec_EXU;
                FAL: exec_FAL;
                FAS: exec_FAS;
                FDL: exec_FDL;
                FDS: exec_FDS;
                FML: exec_FML;
                FMS: exec_FMS;
                FSL: exec_FSL;
                FSS: exec_FSS;
                HIO: exec_HIO;
                INT: exec_INT;
                LAD: exec_LAD;
                LAH: exec_LAH;
                LAW: exec_LAW;
                LB: exec_LB;
                LCD: exec_LCD;
                LCF: exec_LCF;
                LCFI: exec_LCFI;
                LCH: exec_LCH;
                LCW: exec_LCW;
                LD: exec_LD;
                LH: exec_LH;
                LI: exec_LI;
                LM: exec_LM;
                LPSD: exec_LPSD;
                LRP: exec_LRP;
                LS: exec_LS;
                LW: exec_LW;
                MBS: exec_MBS;
                MH: exec_MH;
                MI: exec_MI;
                MMC: exec_MMC;
                MSP: exec_MSP;
                MTB: exec_MTB;
                MTH: exec_MTH;
                MTW: exec_MTW;
                MW: exec_MW;
                OR: exec_OR;
                PACK: exec_PACK;
                PLM: exec_PLM;
                PLW: exec_PLW;
                PSM: exec_PSM;
                PSW: exec_PSW;
                RD: exec_RD;
                S: exec_S;
                SD: exec_SD;
                SF: exec_SF;
                SH: exec_SH;
                SIO: exec_SIO;
                STB: exec_STB;
                STD: exec_STD;
                STFC: exec_STFC;
                STH: exec_STH;
                STM: exec_STM;
                STS: exec_STS;
                STW: exec_STW;
                SW: exec_SW;
                TBS: exec_TBS;
                TDV: exec_TDV;
                TIO: exec_TIO;
                TTBS: exec_TTBS;
                UNPK: exec_UNPK;
                WAIT: exec_WAIT;
                WD: exec_WD;
                XPSD: exec_XPSD;
                XW: exec_XW;
                default: if (phase == PH1) phase <= PCP2;
            endcase
        end
    end

    parameter LCFI = 7'h02;
    parameter CAL1 = 7'h04;
    parameter CAL2 = 7'h05;
    parameter CAL3 = 7'h06;
    parameter CAL4 = 7'h07;
    parameter PLW = 7'h08;
    parameter PSW = 7'h09;
    parameter PLM = 7'h0A;
    parameter PSM = 7'h0B;
    parameter LPSD = 7'h0E;
    parameter XPSD = 7'h0F;
    parameter AD = 7'h10;
    parameter CD = 7'h11;
    parameter LD = 7'h12;
    parameter MSP = 7'h13;
    parameter STD = 7'h15;
    parameter SD = 7'h18;
    parameter CLM = 7'h19;
    parameter LCD = 7'h1A;
    parameter LAD = 7'h1B;
    parameter FSL = 7'h1C;
    parameter FAL = 7'h1D;
    parameter FDL = 7'h1E;
    parameter FML = 7'h1F;
    parameter AI = 7'h20;
    parameter CI = 7'h21;
    parameter LI = 7'h22;
    parameter MI = 7'h23;
    parameter SF = 7'h24;
    parameter S = 7'h25;
    parameter CVS = 7'h28;
    parameter CVA = 7'h29;
    parameter LM = 7'h2A;
    parameter STM = 7'h2B;
    parameter WAIT = 7'h2E;
    parameter LRP = 7'h2F;
    parameter AW = 7'h30;
    parameter CW = 7'h31;
    parameter LW = 7'h32;
    parameter MTW = 7'h33;
    parameter STW = 7'h35;
    parameter DW = 7'h36;
    parameter MW = 7'h37;
    parameter SW = 7'h38;
    parameter CLR = 7'h39;
    parameter LCW = 7'h3A;
    parameter LAW = 7'h3B;
    parameter FSS = 7'h3C;
    parameter FAS = 7'h3D;
    parameter FDS = 7'h3E;
    parameter FMS = 7'h3F;
    parameter TTBS = 7'h40;
    parameter TBS = 7'h41;
    parameter ANLZ = 7'h44;
    parameter CS = 7'h45;
    parameter XW = 7'h46;
    parameter STS = 7'h47;
    parameter EOR = 7'h48;
    parameter OR = 7'h49;
    parameter LS = 7'h4A;
    parameter AND = 7'h4B;
    parameter SIO = 7'h4C;
    parameter TIO = 7'h4D;
    parameter TDV = 7'h4E;
    parameter HIO = 7'h4F;
    parameter AH = 7'h50;
    parameter CH = 7'h51;
    parameter LH = 7'h52;
    parameter MTH = 7'h53;
    parameter STH = 7'h55;
    parameter DH = 7'h56;
    parameter MH = 7'h57;
    parameter SH = 7'h58;
    parameter LCH = 7'h5A;
    parameter LAH = 7'h5B;
    parameter CBS = 7'h60;
    parameter MBS = 7'h61;
    parameter EBS = 7'h63;
    parameter BDR = 7'h64;
    parameter BIR = 7'h65;
    parameter AWM = 7'h66;
    parameter EXU = 7'h67;
    parameter BCR = 7'h68;
    parameter BCS = 7'h69;
    parameter BAL = 7'h6A;
    parameter INT = 7'h6B;
    parameter RD = 7'h6C;
    parameter WD = 7'h6D;
    parameter AIO = 7'h6E;
    parameter MMC = 7'h6F;
    parameter LCF = 7'h70;
    parameter CB = 7'h71;
    parameter LB = 7'h72;
    parameter MTB = 7'h73;
    parameter STFC = 7'h74;
    parameter STB = 7'h75;
    parameter PACK = 7'h76;
    parameter UNPK = 7'h77;
    parameter DS = 7'h78;
    parameter DA = 7'h79;
    parameter DD = 7'h7A;
    parameter DM = 7'h7B;
    parameter DSA = 7'h7C;
    parameter DC = 7'h7D;
    parameter DL = 7'h7E;
    parameter DST = 7'h7F;

endmodule
