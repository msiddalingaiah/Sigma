
/*
 A non-canonical implementation of Sigma7
 - Not cycle accurate
 - Similar internal registers
 */
module CPUX(input wire reset, input wire clock, input wire [0:31] memory_data_in, output wire [15:31] memory_address);
    assign memory_address = lb;
    // Extended register configuration
    reg [0:31] a, b, d;
    // c is a transparent latch, see pp 3-38, receives data from memory
    reg [0:31] c;
    // e is a counting register
    reg [0:7] e;
    // Condition code register
    reg [0:3] cc;
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

    // Signals
    reg ende;

    parameter PRE1 = 8'h11, PRE2 = 8'h12, PRE3 = 8'h13, PRE4 = 8'h14;
    parameter PH1 = 8'h01, PH2 = 8'h02, PH3 = 8'h03, PH4 = 8'h04, PH5 = 8'h05, HALT = 8'h0f;
    parameter PCP1 = 8'h21, PCP2 = 8'h22, PCP3 = 8'h23, PCP4 = 8'h24, PCP5 = 8'h25;

    // Guideline #3: When modeling combinational logic with an "always" 
    //              block, use blocking assignments.
    always @(*) begin
        case (sf)
            SF_ADD: s = a + d;
            SF_SUB: s = a - d;
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

    // Guideline #1: When modeling sequential logic, use nonblocking 
    //              assignments.
    integer i;
    always @(posedge clock, posedge reset) begin
        if (reset == 1) begin
            a <= 0;
            b <= 0;
            c <= 0;
            d <= 0;
            ia <= 0;
            o <= 0;
            p <= 0;
            q <= 0;
            r <= 0;
            e <= 0;
            ende <= 0;
            begin
                for (i=0; i<16; i=i+1) rr[i] = 32'h00000000;
            end
            phase <= PCP1;
            mem_select = MEM_SEL_Q;
        end else begin
            case (phase)
                PRE1: begin
                    q[15:31] <= p[15:31];
                    mem_select <= MEM_SEL_S;
                    if (o == LI || o == AI) begin
                        d <= { {12{c[12]}}, c[13:31] };
                        phase <= PH1;
                    end else begin
                        ia <= c[0];
                        indx <= d[12:14];
                        mem_select <= MEM_SEL_C;
                        phase <= PRE2;
                    end
                    if (o == 0) begin
                        phase <= HALT;
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

                PH1: begin
                    // d = signed extended immediate value
                    // p = effective address
                    // r = register
                    // indx = index register
                    ende <= 1;
                    phase <= PH2;
                    mem_select <= MEM_SEL_Q;
                    case (o)
                        AI:
                            begin
                                a <= rr[r];
                                sf <= SF_ADD;
                                p[15:31] <= q[15:31];
                            end
                        LI:
                            begin
                                rr[r] <= d;
                                p[15:31] <= q[15:31];
                            end
                        LW:
                            begin
                                rr[r] <= memory_data_in;
                                p[15:31] <= q[15:31];
                            end
                        BAL:
                            begin
                                rr[r] <= q;
                                q[15:31] <= p[15:31];
                            end
                        default:
                            begin
                                p[15:31] <= q[15:31];
                            end
                    endcase
                end
                PH2: begin
                    case (o)
                        AI:
                            begin
                                rr[r] <= s;
                            end 
                        default:
                            begin
                            end
                    endcase
                end
                PH3: begin
                end
                PH4: begin
                end
                PH5: begin
                end

                PCP1: begin
                    ende <= 1;
                end

                HALT: begin
                end

                default: begin
                end
            endcase
            if (ende == 1) begin
                $display("* Q %x: %x", q, memory_data_in);
                $display("  R0 %x %x %x %x %x %x %x %x", rr[0], rr[1], rr[2], rr[3], rr[4], rr[5], rr[6], rr[7]);
                $display("  R8 %x %x %x %x %x %x %x %x", rr[8], rr[9], rr[10], rr[11], rr[12], rr[13], rr[14], rr[15]);
                a <= 0;
                c <= memory_data_in[0:31];
                o[1:7] <= memory_data_in[1:7];
                r[0:3] <= memory_data_in[8:11];
                d[0:31] <= memory_data_in[0:31];
                p <= p + 4;
                ende <= 0;
                phase <= PRE1;
            end
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
