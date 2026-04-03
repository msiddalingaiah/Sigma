// SDS/Xerox Sigma 7 CPU
// Big-endian: bit 0 is MSB throughout
// Synchronous memory: address on cycle N → data on cycle N+1
//
// Fetch optimization: instruction is loaded during ENDE rather than PREP1.
// The cycle before ENDE always presents the next instruction address on bus_addr.
//
// Phase sequence (direct memory-reference instruction):
//   EX1: C/D←M[EA], A←RR[R]
//   EX2: P←{Q,00} (so p_inc=next instr in ENDE), alu_out←A+D, RR[R]←result → EX3/ENDE
//   EX3/ENDE: p_inc=next instr, Q←P[15:31], bus_addr←{Q,00}
//
// Phase sequence (immediate instruction):
//   EX1: Q←P, P←{Q,00} (so p_inc=next instr in ENDE)          → EX2/ENDE
//
// Boot sequence:
//   PCP4: bus_addr←p_inc                                        → PCP5
//   PCP5: ENDE fires                                            → PREP1/EX1
//
// Supported instructions: LCFI, LI, LW, STW, AW, SW, CW, AND, OR, EOR

module Sigma7CPU (
    input  wire        clock,
    input  wire        reset,
    input  wire        cpu_grant,
    output wire        cpu_release,
    output reg  [15:33] bus_addr,
    input  wire [0:31] bus_data_r,
    output reg  [0:31] bus_data_w,
    output reg         cpu_write,
    output wire [0:1]  bus_size
);

// ---------------------------------------------------------------------------
// Opcodes
// ---------------------------------------------------------------------------
localparam OP_LCFI = 7'h02;
localparam OP_LI   = 7'h22;
localparam OP_AW   = 7'h30;
localparam OP_CW   = 7'h31;
localparam OP_LW   = 7'h32;
localparam OP_STW  = 7'h35;
localparam OP_SW   = 7'h38;
localparam OP_AND  = 7'h4B;
localparam OP_OR   = 7'h49;
localparam OP_EOR  = 7'h48;

// ---------------------------------------------------------------------------
// Phase register (one-hot, bit 0 = PCP4 = MSB)
// ---------------------------------------------------------------------------
reg [0:19] phase;

localparam PCP4  = 20'b10000000000000000000;
localparam PCP5  = 20'b01000000000000000000;  // fires ENDE on instruction arrival
localparam PREP1 = 20'b00100000000000000000;  // Q←P, set up A from index, present ref addr
localparam PREP2 = 20'b00010000000000000000;  // indirect: D←pointer, present EA base
localparam PREP3 = 20'b00001000000000000000;  // P[15:31]←A+D, present EA
localparam EX1   = 20'b00000100000000000000;
localparam EX2   = 20'b00000010000000000000;
localparam EX3   = 20'b00000001000000000000;
localparam EX4   = 20'b00000000100000000000;

// Phase name for GTKWave (right-click → Data Format → ASCII)
reg [0:63] phase_name;
always @(*) begin
    casez (phase)
        20'b1???????????????????: phase_name = "PCP4    ";
        20'b01??????????????????: phase_name = "PCP5    ";
        20'b001?????????????????: phase_name = "PREP1   ";
        20'b0001????????????????: phase_name = "PREP2   ";
        20'b00001???????????????: phase_name = "PREP3   ";
        20'b000001??????????????: phase_name = "EX1     ";
        20'b0000001?????????????: phase_name = "EX2     ";
        20'b00000001????????????: phase_name = "EX3     ";
        20'b000000001???????????: phase_name = "EX4     ";
        default:                  phase_name = "UNKNOWN ";
    endcase
end

// ---------------------------------------------------------------------------
// Internal registers
// ---------------------------------------------------------------------------
reg [0:31]  A;
reg [0:31]  C;
reg [0:31]  D;          // current instruction word
reg [1:7]   O;          // opcode
reg [8:11]  R;          // register field
reg [15:33] P;          // effective byte address
reg [15:31] Q;          // next instruction word address
reg [1:4]   CC;         // CC1=carry, CC2=overflow, CC3=pos, CC4=neg
reg [0:31]  RR [0:15];  // user register file

initial begin
    A         = 32'b0;
    C         = 32'h02000000;
    D         = 32'h02000000;
    O         = 7'h02;
    R         = 4'h0;
    P         = 19'h00094;      // byte 0x94 → p_inc = 0x98 = word 0x26
    Q         = 17'h25;
    CC        = 4'b0;
end

// ---------------------------------------------------------------------------
// Transparent C latch
// ---------------------------------------------------------------------------
reg C_load;
wire [0:31] C_mux = C_load ? bus_data_r : C;

// ---------------------------------------------------------------------------
// Computed values
// ---------------------------------------------------------------------------
wire [15:33] p_inc   = P + 19'd4;
wire [0:31]  imm20   = {{12{D[12]}}, D[12:31]};

// ---------------------------------------------------------------------------
// Address family decode (based on C — registered instruction word)
// C holds the instruction from ENDE through PREP1 and PREP2 (until clock edge
// of PREP2 for indirect), so decode is always correct during prep phases.
// Reflects the ANLZ instruction table layout — see sigma7_cpu_design.md
// ---------------------------------------------------------------------------
wire        fa_row_00     = C[1:5] == 5'b0;
wire        fa_rows_10_1f = C[3];
wire        fa_rows_08_0f = C[3:4] == 2'b01;
wire        fa_col_00     = C[1:2] == 2'b00;
wire        fa_col_20     = C[1:2] == 2'b01;
wire        fa_col_40     = C[1:2] == 2'b10;
wire        fa_col_60     = C[1:2] == 2'b11;
wire        fa_b          = fa_col_60 & fa_rows_10_1f;
wire        fa_h          = fa_col_40 & fa_rows_10_1f;
wire        fa_d          = fa_col_00 & (fa_rows_08_0f | fa_rows_10_1f);
wire        fa_imm        = fa_row_00 & (fa_col_00 | fa_col_20);
wire        fa_imm_b      = fa_row_00 & (fa_col_40 | fa_col_60);
wire        fa_w          = ~fa_b & ~fa_h & ~fa_d & ~fa_imm & ~fa_imm_b;

// Index register setup — uses C[12:14] (instruction X field)
wire [2:0]  x_field   = C[12:14];
wire [0:31] idx_reg   = RR[x_field];
wire        indexed   = (x_field != 3'b0) & ~fa_imm & ~fa_imm_b;

// Index-shifted value for A
wire [0:31] idx_data  = fa_b ? {2'b00, idx_reg[0:29]} :
                        fa_h ? {1'b0,  idx_reg[0:30]} :
                               idx_reg;

// Byte offset for P[32:33]
wire [0:1]  idx_boff  = fa_b ? idx_reg[30:31] :
                        fa_h ? {1'b0, idx_reg[31]} :
                               2'b00;

// ---------------------------------------------------------------------------
// ALU — inputs are A and D (not C_mux); C_mux is only used to load registers
// ---------------------------------------------------------------------------
localparam ALU_ADD   = 3'd0;
localparam ALU_SUB   = 3'd1;
localparam ALU_AND   = 3'd2;
localparam ALU_OR    = 3'd3;
localparam ALU_XOR   = 3'd4;
localparam ALU_PASSA = 3'd5;  // S ← A
localparam ALU_PASSD = 3'd6;  // S ← D

reg [2:0]  alu_op;
reg [0:31] alu_out;
reg        alu_carry;
reg        alu_overflow;

always @(*) begin
    alu_carry    = 1'b0;
    alu_overflow = 1'b0;
    case (alu_op)
        ALU_ADD: begin
            {alu_carry, alu_out} = {1'b0, A} + {1'b0, D};
            alu_overflow = (A[0] == D[0]) && (alu_out[0] != A[0]);
        end
        ALU_SUB: begin
            {alu_carry, alu_out} = {1'b0, A} + {1'b0, ~D} + 33'd1;
            alu_overflow = (A[0] != D[0]) && (alu_out[0] != A[0]);
        end
        ALU_AND:   alu_out = A & D;
        ALU_OR:    alu_out = A | D;
        ALU_XOR:   alu_out = A ^ D;
        ALU_PASSA: alu_out = A;
        ALU_PASSD: alu_out = D;
        default:   alu_out = A;
    endcase
end

// ---------------------------------------------------------------------------
// Sel constants
// ---------------------------------------------------------------------------
localparam A_HOLD = 3'd0;
localparam A_RR   = 3'd1;
localparam A_CMUX = 3'd2;
localparam A_ALU  = 3'd3;
localparam A_ZERO = 3'd4;
localparam A_IMM  = 3'd5;
localparam A_IDX  = 3'd6;  // A ← idx_data (shifted index register)

localparam P_HOLD = 2'd0;
localparam P_EA   = 2'd1;
localparam P_Q    = 2'd2;
localparam P_INC  = 2'd3;

localparam CC_HOLD    = 2'd0;
localparam CC_ARITH   = 2'd1;
localparam CC_COMPARE = 2'd2;

// ---------------------------------------------------------------------------
// Control signals
// ---------------------------------------------------------------------------
reg [2:0]  A_sel;
reg [1:0]  P_sel;
reg [1:0]  CC_sel;
reg [0:1]  p_byte_offset;  // byte offset for P[32:33] set during ENDE
reg        D_sel;
reg        O_sel;
reg        R_sel;
reg        Q_sel;
reg        rr_write;
reg [0:31] rr_data;
reg        ende;
reg [0:19] phase_next;

// ---------------------------------------------------------------------------
// Bus outputs
// ---------------------------------------------------------------------------
assign bus_size    = 2'b10;
assign cpu_release = 1'b0;

// ---------------------------------------------------------------------------
// Phase sequencer
// ---------------------------------------------------------------------------
always @(posedge clock) begin
    if (reset)
        phase <= PCP4;
    else if (cpu_grant)
        phase <= phase_next;
end

// ---------------------------------------------------------------------------
// Register updates
// ---------------------------------------------------------------------------
always @(posedge clock) begin
    if (reset) begin
        A         <= 32'b0;
        C         <= 32'h02000000;
        D         <= 32'h02000000;
        O         <= 7'h02;
        R         <= 4'h0;
        P         <= 19'h00094;
        Q         <= 17'h25;
        CC        <= 4'b0;
    end else begin
        if (C_load) C <= bus_data_r;
        case (A_sel)
            A_RR:   A <= RR[R];
            A_CMUX: A <= C_mux;
            A_ALU:  A <= alu_out;
            A_ZERO: A <= 32'b0;
            A_IMM:  A <= imm20;
            A_IDX:  A <= idx_data;
            default: ;
        endcase
        case (P_sel)
            P_EA:  P <= {alu_out[15:31], P[32:33]};         // EA from S[15:31]
            P_Q:   P <= {Q, 2'b00};
            P_INC: P <= {p_inc[15:31], p_byte_offset};      // byte offset set by ENDE
            default: ;
        endcase
        case (CC_sel)
            CC_ARITH: begin
                CC[1] <= alu_carry;
                CC[2] <= alu_overflow;
                CC[3] <= !alu_out[0] && |alu_out;
                CC[4] <= alu_out[0];
            end
            CC_COMPARE: begin
                CC[1] <= 1'b0;
                CC[2] <= |(A & D);
                CC[3] <= !alu_out[0] && |alu_out;
                CC[4] <= alu_out[0];
            end
            default: ;
        endcase
        if (D_sel) D <= C_mux;  // D ← C_mux (instruction in ENDE, operand in EX1, pointer in PREP2)
        if (O_sel) O <= bus_data_r[1:7];
        if (R_sel) R <= bus_data_r[8:11];
        if (Q_sel) Q <= P[15:31];  // Q ← next instruction word address (P=p_inc after ENDE)
    end
end

// RR file
always @(posedge clock) begin
    if (reset) begin : rr_reset
        integer i;
        for (i = 0; i < 16; i = i + 1)
            RR[i] <= 32'b0;
    end else if (rr_write)
        RR[R] <= rr_data;
end

// ---------------------------------------------------------------------------
// Control unit — combinatorial
// ---------------------------------------------------------------------------
always @(*) begin
    // Defaults
    ende           = 1'b0;
    phase_next     = {1'b0, phase[0:18]};  // default: advance to next phase
    C_load         = 1'b0;
    A_sel          = A_HOLD;
    P_sel          = P_HOLD;
    CC_sel         = CC_HOLD;
    p_byte_offset  = 2'b00;
    D_sel          = 1'b0;
    O_sel        = 1'b0;
    R_sel        = 1'b0;
    Q_sel        = 1'b0;
    rr_write     = 1'b0;
    rr_data      = 32'b0;
    alu_op       = ALU_PASSA;
    bus_addr     = {P[15:31], 2'b00};   // default: hold current address
    bus_data_w   = 32'b0;
    cpu_write    = 1'b0;

    case (1'b1)

        // ------------------------------------------------------------------
        // PCP4: stable reset/halt state. On release present p_inc, jump to PCP5
        // ------------------------------------------------------------------
        phase[0]: begin
            if (!reset) begin
                bus_addr   = p_inc;
                phase_next = PCP5;
            end else
                phase_next = PCP4;  // hold in PCP4 during reset
        end

        // ------------------------------------------------------------------
        // PCP5: ENDE fires — instruction arrived from PCP4 fetch
        // ------------------------------------------------------------------
        phase[1]: begin
            ende = 1'b1;
        end

        // ------------------------------------------------------------------
        // PREP1: Q ← P; set up A from index (RR now fresh after any EX write);
        //        present reference address on bus (works for direct and indirect);
        //        check I bit to decide PREP2 (indirect) or PREP3 (direct).
        // ------------------------------------------------------------------
        phase[2]: begin
            Q_sel = 1'b1;                   // Q ← P[15:31] = IA word address
            if (indexed) begin
                A_sel         = A_IDX;
                p_byte_offset = idx_boff;
            end else begin
                A_sel         = A_ZERO;
                p_byte_offset = 2'b00;
            end
            bus_addr = {C[15:31], 2'b00};   // reference address field
            if (C[0]) phase_next = PREP2;   // indirect: resolve pointer
            else      phase_next = PREP3;   // direct: compute EA
        end

        // ------------------------------------------------------------------
        // PREP2: indirect resolution — pointer arrives on bus
        //        C_load and D_sel both fire: C and D ← pointer word
        //        A and P[32:33] already set correctly in PREP1
        //        Use C (registered instruction) for bus_addr to avoid
        //        combinatorial path through memory output → C_mux → bus_addr
        // ------------------------------------------------------------------
        phase[3]: begin
            C_load   = 1'b1;
            D_sel    = 1'b1;                    // D ← C_mux = indirect pointer
            bus_addr = {C[15:31], 2'b00};       // safe: C=instruction, breaks comb. path
            // auto-shifts to PREP3
        end

        // ------------------------------------------------------------------
        // PREP3: P[15:31] ← A+D (EA); present EA on bus → operand at EX1
        // ------------------------------------------------------------------
        phase[4]: begin
            alu_op   = ALU_ADD;         // A + D = index + base
            P_sel    = P_EA;            // P[15:31] ← alu_out[15:31]
            bus_addr = {alu_out[15:31], P[32:33]};
            // auto-shifts to EX1
        end

        // ------------------------------------------------------------------
        // EX1: operand arrives on bus; load C and D; load A from RR[R]
        // ------------------------------------------------------------------
        phase[5]: begin
            case (O)
                OP_LCFI,
                OP_LI: begin
                    // P holds IA (set by previous ENDE, unchanged since immediate skips PREP3)
                    // Q ← P[15:31] = IA word address; bus presents IA for ENDE fetch
                    Q_sel    = 1'b1;
                    bus_addr = {P[15:31], 2'b00};  // = IA; use P since Q not yet updated
                end
                OP_LW: begin
                    C_load = 1'b1;      // C ← M[EA]
                    A_sel  = A_CMUX;    // A ← M[EA] directly (simple load)
                end
                OP_STW: A_sel = A_RR;  // A ← RR[R]
                OP_AW, OP_SW, OP_CW,
                OP_AND, OP_OR, OP_EOR: begin
                    C_load = 1'b1;      // C ← M[EA]
                    D_sel  = 1'b1;      // D ← C_mux = M[EA] (ALU second input)
                    A_sel  = A_RR;      // A ← RR[R]
                end
                default: ;
            endcase
        end

        // ------------------------------------------------------------------
        // EX2: compute result using A and D; write RR; set CC
        // ------------------------------------------------------------------
        phase[6]: begin
            case (O)
                OP_LCFI: ende = 1'b1;

                OP_LI: begin
                    A_sel    = A_IMM;
                    alu_op   = ALU_PASSA;
                    CC_sel   = CC_ARITH;
                    rr_data  = imm20;
                    rr_write = 1'b1;
                    ende     = 1'b1;
                end

                OP_LW: begin
                    alu_op   = ALU_PASSA;
                    CC_sel   = CC_ARITH;
                    rr_data  = A;
                    rr_write = 1'b1;
                    P_sel    = P_Q;
                    bus_addr = {Q, 2'b00};
                end

                OP_STW: begin
                    bus_addr   = P;
                    bus_data_w = A;
                    cpu_write  = 1'b1;
                end

                OP_AW: begin
                    alu_op   = ALU_ADD;
                    A_sel    = A_ALU;
                    CC_sel   = CC_ARITH;
                    rr_data  = alu_out;
                    rr_write = 1'b1;
                    P_sel    = P_Q;
                    bus_addr = {Q, 2'b00};
                end

                OP_SW: begin
                    alu_op   = ALU_SUB;
                    A_sel    = A_ALU;
                    CC_sel   = CC_ARITH;
                    rr_data  = alu_out;
                    rr_write = 1'b1;
                    P_sel    = P_Q;
                    bus_addr = {Q, 2'b00};
                end

                OP_CW: begin
                    alu_op   = ALU_SUB;
                    A_sel    = A_ALU;
                    CC_sel   = CC_COMPARE;
                    P_sel    = P_Q;
                    bus_addr = {Q, 2'b00};
                end

                OP_AND: begin
                    alu_op   = ALU_AND;
                    A_sel    = A_ALU;
                    CC_sel   = CC_ARITH;
                    rr_data  = alu_out;
                    rr_write = 1'b1;
                    P_sel    = P_Q;
                    bus_addr = {Q, 2'b00};
                end

                OP_OR: begin
                    alu_op   = ALU_OR;
                    A_sel    = A_ALU;
                    CC_sel   = CC_ARITH;
                    rr_data  = alu_out;
                    rr_write = 1'b1;
                    P_sel    = P_Q;
                    bus_addr = {Q, 2'b00};
                end

                OP_EOR: begin
                    alu_op   = ALU_XOR;
                    A_sel    = A_ALU;
                    CC_sel   = CC_ARITH;
                    rr_data  = alu_out;
                    rr_write = 1'b1;
                    P_sel    = P_Q;
                    bus_addr = {Q, 2'b00};
                end

                default: ;
            endcase
        end

        // ------------------------------------------------------------------
        // EX3: ENDE for LW/AW/SW/CW/AND/OR/EOR; restore P for STW
        // ------------------------------------------------------------------
        phase[7]: begin
            case (O)
                OP_LW,
                OP_AW, OP_SW, OP_CW,
                OP_AND, OP_OR, OP_EOR: ende = 1'b1;

                OP_STW: begin
                    P_sel    = P_Q;
                    bus_addr = {Q, 2'b00};
                end

                default: ;
            endcase
        end

        // ------------------------------------------------------------------
        // EX4: ENDE for STW
        // ------------------------------------------------------------------
        phase[8]: begin
            case (O)
                OP_STW: ende = 1'b1;
                default: ;
            endcase
        end

        default: ;

    endcase

    // ------------------------------------------------------------------
    // ENDE: load next instruction, update P/Q/A, present reference address.
    // Fires from PCP5 (boot ENDE) or from EX phases (normal operation).
    // Index register setup moved to PREP1 so freshly-written RR is available.
    // ------------------------------------------------------------------
    if (ende) begin
        // Load incoming instruction
        C_load        = 1'b1;
        D_sel         = 1'b1;
        O_sel         = 1'b1;
        R_sel         = 1'b1;
        A_sel         = A_ZERO;   // A ← 0; index setup done in PREP1
        p_byte_offset = 2'b00;
        P_sel         = P_INC;    // P ← p_inc = next instruction byte address
        // bus_addr not critical here — next instruction already fetched

        bus_addr = {Q, 2'b00};  // hold current instruction address (next instr already fetched)

        // Next phase based on incoming instruction opcode
        casez (bus_data_r[1:7])
            OP_LCFI,
            OP_LI:   phase_next = EX1;    // immediate: skip prep
            default: phase_next = PREP1;  // memory-reference: compute EA
        endcase
    end

end

endmodule