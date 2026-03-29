// SDS/Xerox Sigma 7 CPU
// Big-endian: bit 0 is MSB throughout
// Synchronous memory: address on cycle N → data on cycle N+1
//
// Fetch optimization: instruction is loaded during ENDE rather than PREP1.
// The cycle before ENDE always presents the next instruction address on bus_addr.
//
// Phase sequence (memory-reference instruction):
//   EX(n-1): P←{Q,00}, bus_addr←next_ia  — present next instruction address
//   EX(n)/ENDE: C/D/O/R/Q/A←bus_data_r, P←p_inc, bus_addr←{D[15:31],00} → PREP1
//   PREP1: bus_addr←ea                                                     → PREP3
//   PREP3: P←ea                                                            → EX1
//   EX1:   operand arrives
//
// Phase sequence (immediate instruction):
//   EX(n-1): P←{Q,00}, bus_addr←next_ia
//   EX(n)/ENDE: C/D/O/R/Q/A←bus_data_r, P←p_inc, bus_addr←{D[15:31],00} → EX1
//
// Boot sequence:
//   PCP5: bus_addr←p_inc                                                   → PREP2
//   PREP2/BOOT_ENDE: ENDE fires (instruction arrives from PCP5 fetch)      → PREP1/EX1
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
// Phase register (one-hot, bit 0 = PCP5 = MSB)
// ---------------------------------------------------------------------------
reg [0:19] phase;

localparam PCP5  = 20'b10000000000000000000;
localparam PREP1 = 20'b01000000000000000000;  // present EA on bus
localparam PREP2 = 20'b00100000000000000000;  // boot ENDE / future indirect
localparam PREP3 = 20'b00010000000000000000;  // P ← ea
localparam EX1   = 20'b00001000000000000000;
localparam EX2   = 20'b00000100000000000000;
localparam EX3   = 20'b00000010000000000000;
localparam EX4   = 20'b00000001000000000000;

// Phase name for GTKWave (right-click → Data Format → ASCII)
reg [0:63] phase_name;
always @(*) begin
    casez (phase)
        20'b1???????????????????: phase_name = "PCP5    ";
        20'b01??????????????????: phase_name = "PREP1   ";
        20'b001?????????????????: phase_name = "PREP2   ";
        20'b0001????????????????: phase_name = "PREP3   ";
        20'b00001???????????????: phase_name = "EX1     ";
        20'b000001??????????????: phase_name = "EX2     ";
        20'b0000001?????????????: phase_name = "EX3     ";
        20'b00000001????????????: phase_name = "EX4     ";
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
    A  = 32'b0;
    C  = 32'h02000000;
    D  = 32'h02000000;
    O  = 7'h02;
    R  = 4'h0;
    P  = 19'h00094;      // byte 0x94 → p_inc = 0x98 = word 0x26
    Q  = 17'h25;
    CC = 4'b0;
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
wire [15:33] next_ia = {Q + 17'd1, 2'b00};  // next instruction byte address
wire [15:31] ea_word = A[15:31] + D[15:31];
wire [15:33] ea      = {ea_word, P[32:33]};
wire [0:31]  imm20   = {{12{D[12]}}, D[12:31]};

// ---------------------------------------------------------------------------
// ALU
// ---------------------------------------------------------------------------
localparam ALU_ADD   = 3'd0;
localparam ALU_SUB   = 3'd1;
localparam ALU_AND   = 3'd2;
localparam ALU_OR    = 3'd3;
localparam ALU_XOR   = 3'd4;
localparam ALU_PASSA = 3'd5;

reg [2:0]  alu_op;
reg [0:31] alu_out;
reg        alu_carry;
reg        alu_overflow;

always @(*) begin
    alu_carry    = 1'b0;
    alu_overflow = 1'b0;
    case (alu_op)
        ALU_ADD: begin
            {alu_carry, alu_out} = {1'b0, A} + {1'b0, C_mux};
            alu_overflow = (A[0] == C_mux[0]) && (alu_out[0] != A[0]);
        end
        ALU_SUB: begin
            {alu_carry, alu_out} = {1'b0, A} + {1'b0, ~C_mux} + 33'd1;
            alu_overflow = (A[0] != C_mux[0]) && (alu_out[0] != A[0]);
        end
        ALU_AND:   alu_out = A & C_mux;
        ALU_OR:    alu_out = A | C_mux;
        ALU_XOR:   alu_out = A ^ C_mux;
        ALU_PASSA: alu_out = A;
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
reg        D_sel;
reg        O_sel;
reg        R_sel;
reg        Q_sel;
reg        rr_write;
reg [0:31] rr_data;
reg        ende;
reg        phase_jump;
reg [0:19] phase_target;

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
        phase <= PCP5;
    else if (!cpu_grant)
        phase <= phase;
    else if (phase_jump)
        phase <= phase_target;
    else if (!phase[0])
        phase <= {1'b0, phase[0:18]};
end

// ---------------------------------------------------------------------------
// Register updates
// ---------------------------------------------------------------------------
always @(posedge clock) begin
    if (reset) begin
        A  <= 32'b0;
        C  <= 32'h02000000;
        D  <= 32'h02000000;
        O  <= 7'h02;
        R  <= 4'h0;
        P  <= 19'h00094;
        Q  <= 17'h25;
        CC <= 4'b0;
    end else begin
        if (C_load) C <= bus_data_r;
        case (A_sel)
            A_RR:   A <= RR[R];
            A_CMUX: A <= C_mux;
            A_ALU:  A <= alu_out;
            A_ZERO: A <= 32'b0;
            A_IMM:  A <= imm20;
            default: ;
        endcase
        case (P_sel)
            P_EA:  P <= ea;
            P_Q:   P <= {Q, 2'b00};
            P_INC: P <= p_inc;
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
                CC[2] <= |(A & C_mux);
                CC[3] <= !alu_out[0] && |alu_out;
                CC[4] <= alu_out[0];
            end
            default: ;
        endcase
        if (D_sel) D <= bus_data_r;
        if (O_sel) O <= bus_data_r[1:7];
        if (R_sel) R <= bus_data_r[8:11];
        if (Q_sel) Q <= p_inc[15:31];   // Q ← word address of next instruction
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
    ende         = 1'b0;
    phase_jump   = 1'b0;
    phase_target = PREP1;
    C_load       = 1'b0;
    A_sel        = A_HOLD;
    P_sel        = P_HOLD;
    CC_sel       = CC_HOLD;
    D_sel        = 1'b0;
    O_sel        = 1'b0;
    R_sel        = 1'b0;
    Q_sel        = 1'b0;
    rr_write     = 1'b0;
    rr_data      = 32'b0;
    alu_op       = ALU_PASSA;
    bus_addr     = {Q, 2'b00};
    bus_data_w   = 32'b0;
    cpu_write    = 1'b0;

    case (1'b1)

        // ------------------------------------------------------------------
        // PCP5: present initial instruction address, jump to PREP2 (boot ENDE)
        // ------------------------------------------------------------------
        phase[0]: begin
            if (!reset) begin
                bus_addr     = p_inc;   // present 0x098 to memory
                phase_jump   = 1'b1;
                phase_target = PREP2;
            end
        end

        // ------------------------------------------------------------------
        // PREP1: present EA on bus (D has instruction from ENDE)
        // ------------------------------------------------------------------
        phase[1]: begin
            bus_addr     = {D[15:31], 2'b00};   // EA (A=0 for non-indexed)
            phase_jump   = 1'b1;
            phase_target = PREP3;
        end

        // ------------------------------------------------------------------
        // PREP2: BOOT_ENDE — fires ENDE so instruction loaded from bus
        //        (future: also indirect address resolution)
        // ------------------------------------------------------------------
        phase[2]: begin
            ende = 1'b1;
        end

        // ------------------------------------------------------------------
        // PREP3: P ← ea, hold EA on bus so operand arrives at EX1
        // ------------------------------------------------------------------
        phase[3]: begin
            P_sel    = P_EA;
            bus_addr = ea;
            // auto-shifts to EX1
        end

        // ------------------------------------------------------------------
        // EX1
        // ------------------------------------------------------------------
        phase[4]: begin
            case (O)
                OP_LCFI,
                OP_LI: begin
                    // Restore P and present next instruction (one cycle before ENDE)
                    P_sel    = P_Q;
                    bus_addr = next_ia;
                end
                OP_LW: begin
                    C_load = 1'b1;    // C ← M[EA]
                    A_sel  = A_CMUX;  // A ← C_mux
                end
                OP_STW: A_sel = A_RR; // A ← RR[R]
                OP_AW, OP_SW, OP_CW,
                OP_AND, OP_OR, OP_EOR: begin
                    C_load = 1'b1;    // C ← M[EA]
                    A_sel  = A_RR;    // A ← RR[R]
                end
                default: ;
            endcase
        end

        // ------------------------------------------------------------------
        // EX2
        // ------------------------------------------------------------------
        phase[5]: begin
            case (O)
                OP_LCFI: ende = 1'b1;   // fires ENDE; CC load handled below

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
                    bus_addr = next_ia;
                end

                OP_STW: begin
                    // Bus busy with write — cannot present next_ia yet
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
                    bus_addr = next_ia;
                end

                OP_SW: begin
                    alu_op   = ALU_SUB;
                    A_sel    = A_ALU;
                    CC_sel   = CC_ARITH;
                    rr_data  = alu_out;
                    rr_write = 1'b1;
                    P_sel    = P_Q;
                    bus_addr = next_ia;
                end

                OP_CW: begin
                    alu_op   = ALU_SUB;
                    A_sel    = A_ALU;
                    CC_sel   = CC_COMPARE;
                    P_sel    = P_Q;
                    bus_addr = next_ia;
                end

                OP_AND: begin
                    alu_op   = ALU_AND;
                    A_sel    = A_ALU;
                    CC_sel   = CC_ARITH;
                    rr_data  = alu_out;
                    rr_write = 1'b1;
                    P_sel    = P_Q;
                    bus_addr = next_ia;
                end

                OP_OR: begin
                    alu_op   = ALU_OR;
                    A_sel    = A_ALU;
                    CC_sel   = CC_ARITH;
                    rr_data  = alu_out;
                    rr_write = 1'b1;
                    P_sel    = P_Q;
                    bus_addr = next_ia;
                end

                OP_EOR: begin
                    alu_op   = ALU_XOR;
                    A_sel    = A_ALU;
                    CC_sel   = CC_ARITH;
                    rr_data  = alu_out;
                    rr_write = 1'b1;
                    P_sel    = P_Q;
                    bus_addr = next_ia;
                end

                default: ;
            endcase
        end

        // ------------------------------------------------------------------
        // EX3: ENDE for LW/AW/SW/CW/AND/OR/EOR
        //      Present next_ia for STW (bus now free after write)
        // ------------------------------------------------------------------
        phase[6]: begin
            case (O)
                OP_LW,
                OP_AW, OP_SW, OP_CW,
                OP_AND, OP_OR, OP_EOR: ende = 1'b1;

                OP_STW: begin
                    P_sel    = P_Q;
                    bus_addr = next_ia;
                end

                default: ;
            endcase
        end

        // ------------------------------------------------------------------
        // EX4: ENDE for STW
        // ------------------------------------------------------------------
        phase[7]: begin
            case (O)
                OP_STW: ende = 1'b1;
                default: ;
            endcase
        end

        default: ;

    endcase

    // ------------------------------------------------------------------
    // ENDE: load next instruction, update P/Q/A, present reference address.
    // Fires from PREP2 (boot), or from EX phases (normal operation).
    // ------------------------------------------------------------------
    if (ende) begin
        // Load incoming instruction
        C_load = 1'b1;
        D_sel  = 1'b1;
        O_sel  = 1'b1;
        R_sel  = 1'b1;
        A_sel  = A_ZERO;    // A ← 0 for EA calculation
        Q_sel  = 1'b1;      // Q ← p_inc[15:31]
        P_sel  = P_INC;     // P ← p_inc

        // C_mux is transparent: bus_data_r[15:31] available combinatorially
        bus_addr = {C_mux[15:31], 2'b00};

        // Next phase based on incoming instruction opcode
        phase_jump = 1'b1;
        casez (bus_data_r[1:7])
            OP_LCFI,
            OP_LI:   phase_target = EX1;    // immediate: skip prep
            default: phase_target = PREP1;  // memory-reference: compute EA
        endcase
    end

end

endmodule