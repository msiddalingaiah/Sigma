
/*
Memory is word addressed, 17 bits
lb - memory address lines from either p, q, or c registers depending on lmxc/lmxq
*/
module CPU(input wire reset, input wire clock, input wire [0:31] memory_data_in, output wire [15:31] memory_address);
    assign memory_address = lb;
    // Extended register configuration
    reg [0:71] a, b, d;
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
    reg [1:7] o_opcode;
    // p is a counting register, acts as the program counter in conjunction with q
    reg [15:33] p;
    // Phase register, one-hot encoded
    reg [0:7] phase;
    // q holds the next instruction address
    reg [15:31] q;
    // private memory address (register number), pctr counts up, mctr counts down
    reg [28:31] r;
    // private memory registers
    reg [0:31] rr[0:31];
    // register pointer
    reg [23:27] rp;
    // sum bus
    reg [0:31] s;

    // Signals
    reg lmxc, lmxq;
    reg ende;
    wire preim = (o_opcode == LCFI) | (o_opcode == AI) | (o_opcode == LI) | (o_opcode == CBS) |
        (o_opcode == EBS) | (o_opcode == MBS);

    parameter PRE1 = 1, PRE2 = 2, PRE3 = 3, PRE4 = 4;
    parameter PH1 = 11, PH2 = 12, PH3 = 13, PH4 = 14;

    // Guideline #3: When modeling combinational logic with an "always" 
    //              block, use blocking assignments.
    always @(*) begin
        // TODO: needs logic here
        lmxq = 0;
        // Memory address logic (no map), see pp 3-198
        //lb = { p[15:22], 9'h000 };
        lb = p;
        if (lmxq == 1) begin
            lb[15:22] = q[15:22];
        end
        if (lmxc == 1) begin
            lb[15:30] = c[15:30];
        end

        ende = phase == PH2;
    end

    // Guideline #1: When modeling sequential logic, use nonblocking 
    //              assignments.
    always @(posedge clock, posedge reset) begin
        if (reset == 1) begin
            a <= 0;
            b <= 0;
            c <= 0;
            d <= 0;
            o_opcode <= 0;
            p <= 0;
            q <= 0;
            e <= 0;
            lmxc <= 0;
            phase <= PH2;
        end else begin
            c <= c_in;
            case (phase)
                PRE1: begin
                    q <= p;
                    a <= 0;
                    b <= 0;
                    e <= 0;
                    phase <= PRE2;
                    if (preim == 1) begin
                        phase <= PH1;
                    end
                    lmxc <= 0;
                end
                PRE2: begin
                    // p <= a[0:31] + d[0:31] + cs[0:31]; // not sure about cs
                    a <= 0;
                    d <= 0;
                    phase <= PRE3;
                end
                PRE3: begin
                    phase <= PRE4;
                end
                PRE4: begin
                    phase <= PH1;
                end
                PH1: begin
                    phase <= PH2;
                end
                PH2: begin
                    phase <= PRE3;
                end
                default: begin
                    phase <= PRE1;
                end
            endcase
            if (ende == 1) begin
                o_opcode[1:7] <= c_in[1:7];
                r[28:31] <= c_in[8:11];
                d[0:31] <= c_in[0:31];
                p <= p + 1;
                phase <= PRE1;
                lmxc <= 1;
            end
        end
    end

    parameter LCFI = 'h02;
    parameter CAL1 = 'h04;
    parameter CAL2 = 'h05;
    parameter CAL3 = 'h06;
    parameter CAL4 = 'h07;
    parameter PLW = 'h08;
    parameter PSW = 'h09;
    parameter PLM = 'h0A;
    parameter PSM = 'h0B;
    parameter LPSD = 'h0E;
    parameter XPSD = 'h0F;
    parameter AD = 'h10;
    parameter CD = 'h11;
    parameter LD = 'h12;
    parameter MSP = 'h13;
    parameter STD = 'h15;
    parameter SD = 'h18;
    parameter CLM = 'h19;
    parameter LCD = 'h1A;
    parameter LAD = 'h1B;
    parameter FSL = 'h1C;
    parameter FAL = 'h1D;
    parameter FDL = 'h1E;
    parameter FML = 'h1F;
    parameter AI = 'h20;
    parameter CI = 'h21;
    parameter LI = 'h22;
    parameter MI = 'h23;
    parameter SF = 'h24;
    parameter S = 'h25;
    parameter CVS = 'h28;
    parameter CVA = 'h29;
    parameter LM = 'h2A;
    parameter STM = 'h2B;
    parameter WAIT = 'h2E;
    parameter LRP = 'h2F;
    parameter AW = 'h30;
    parameter CW = 'h31;
    parameter LW = 'h32;
    parameter MTW = 'h33;
    parameter STW = 'h35;
    parameter DW = 'h36;
    parameter MW = 'h37;
    parameter SW = 'h38;
    parameter CLR = 'h39;
    parameter LCW = 'h3A;
    parameter LAW = 'h3B;
    parameter FSS = 'h3C;
    parameter FAS = 'h3D;
    parameter FDS = 'h3E;
    parameter FMS = 'h3F;
    parameter TTBS = 'h40;
    parameter TBS = 'h41;
    parameter ANLZ = 'h44;
    parameter CS = 'h45;
    parameter XW = 'h46;
    parameter STS = 'h47;
    parameter EOR = 'h48;
    parameter OR = 'h49;
    parameter LS = 'h4A;
    parameter AND = 'h4B;
    parameter SIO = 'h4C;
    parameter TIO = 'h4D;
    parameter TDV = 'h4E;
    parameter HIO = 'h4F;
    parameter AH = 'h50;
    parameter CH = 'h51;
    parameter LH = 'h52;
    parameter MTH = 'h53;
    parameter STH = 'h55;
    parameter DH = 'h56;
    parameter MH = 'h57;
    parameter SH = 'h58;
    parameter LCH = 'h5A;
    parameter LAH = 'h5B;
    parameter CBS = 'h60;
    parameter MBS = 'h61;
    parameter EBS = 'h63;
    parameter BDR = 'h64;
    parameter BIR = 'h65;
    parameter AWM = 'h66;
    parameter EXU = 'h67;
    parameter BCR = 'h68;
    parameter BCS = 'h69;
    parameter BAL = 'h6A;
    parameter INT = 'h6B;
    parameter RD = 'h6C;
    parameter WD = 'h6D;
    parameter AIO = 'h6E;
    parameter MMC = 'h6F;
    parameter LCF = 'h70;
    parameter CB = 'h71;
    parameter LB = 'h72;
    parameter MTB = 'h73;
    parameter STFC = 'h74;
    parameter STB = 'h75;
    parameter PACK = 'h76;
    parameter UNPK = 'h77;
    parameter DS = 'h78;
    parameter DA = 'h79;
    parameter DD = 'h7A;
    parameter DM = 'h7B;
    parameter DSA = 'h7C;
    parameter DC = 'h7D;
    parameter DL = 'h7E;
    parameter DST = 'h7F;

endmodule
