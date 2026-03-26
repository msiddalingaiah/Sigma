// SDS/Xerox Sigma 7 CPU
// RTL implementation matching physical hardware phase structure
// Big-endian: bit 0 is MSB throughout

module Sigma7CPU (
    input  wire        clock,
    input  wire        reset,
    // Bus interface
    input  wire        cpu_grant,      // arbiter grants bus to CPU
    output wire        cpu_release,    // CPU releases bus to IOP
    output wire [15:33] bus_addr,      // shared memory address
    input  wire [0:31] bus_data_r,     // read data from memory
    output wire [0:31] bus_data_w,     // write data to memory
    output wire        cpu_write,      // CPU write strobe
    output wire [0:1]  bus_size        // 00=byte, 01=halfword, 10=word
);

// ---------------------------------------------------------------------------
// Phase register (one-hot shift register)
// Bits 0-2:  PREP1, PREP2, PREP3
// Bits 3-18: EX1-EX16
// ---------------------------------------------------------------------------
reg [0:18] phase;

localparam PREP1 = 19'b100_0000_0000_0000_0000;
localparam PREP2 = 19'b010_0000_0000_0000_0000;
localparam PREP3 = 19'b001_0000_0000_0000_0000;
localparam EX1   = 19'b000_1000_0000_0000_0000;
localparam EX2   = 19'b000_0100_0000_0000_0000;
localparam EX3   = 19'b000_0010_0000_0000_0000;
localparam EX4   = 19'b000_0001_0000_0000_0000;
localparam EX5   = 19'b000_0000_1000_0000_0000;
localparam EX6   = 19'b000_0000_0100_0000_0000;
localparam EX7   = 19'b000_0000_0010_0000_0000;
localparam EX8   = 19'b000_0000_0001_0000_0000;
localparam EX9   = 19'b000_0000_0000_1000_0000;
localparam EX10  = 19'b000_0000_0000_0100_0000;
localparam EX11  = 19'b000_0000_0000_0010_0000;
localparam EX12  = 19'b000_0000_0000_0001_0000;
localparam EX13  = 19'b000_0000_0000_0000_1000;
localparam EX14  = 19'b000_0000_0000_0000_0100;
localparam EX15  = 19'b000_0000_0000_0000_0010;
localparam EX16  = 19'b000_0000_0000_0000_0001;

// ---------------------------------------------------------------------------
// Opcode constants
// ---------------------------------------------------------------------------
localparam OP_LCFI = 7'h02;
localparam OP_AD  = 7'h10; localparam OP_CD  = 7'h11;
localparam OP_LD  = 7'h12; localparam OP_STD = 7'h15;
localparam OP_SD  = 7'h18; localparam OP_LCD = 7'h1A;
localparam OP_LAD = 7'h1B;
localparam OP_AI  = 7'h20; localparam OP_CI  = 7'h21;
localparam OP_LI  = 7'h22; localparam OP_MI  = 7'h23;
localparam OP_SF  = 7'h24; localparam OP_S   = 7'h25;
localparam OP_AW  = 7'h30; localparam OP_CW  = 7'h31;
localparam OP_LW  = 7'h32; localparam OP_MTW = 7'h33;
localparam OP_STW = 7'h35; localparam OP_DW  = 7'h36;
localparam OP_MW  = 7'h37; localparam OP_SW  = 7'h38;
localparam OP_CLR = 7'h39; localparam OP_LCW = 7'h3A;
localparam OP_LAW = 7'h3B;
localparam OP_EOR = 7'h48; localparam OP_OR  = 7'h49;
localparam OP_AND = 7'h4B;
localparam OP_SIO = 7'h4C; localparam OP_TIO = 7'h4D;
localparam OP_TDV = 7'h4E; localparam OP_HIO = 7'h4F;
localparam OP_AH  = 7'h50; localparam OP_CH  = 7'h51;
localparam OP_LH  = 7'h52; localparam OP_MTH = 7'h53;
localparam OP_STH = 7'h55; localparam OP_DH  = 7'h56;
localparam OP_MH  = 7'h57; localparam OP_SH  = 7'h58;
localparam OP_LCH = 7'h5A; localparam OP_LAH = 7'h5B;
localparam OP_CB  = 7'h71; localparam OP_LB  = 7'h72;
localparam OP_MTB = 7'h73; localparam OP_STB = 7'h75;
localparam OP_BDR = 7'h64; localparam OP_BIR = 7'h65;
localparam OP_BCR = 7'h68; localparam OP_BCS = 7'h69;
localparam OP_BAL = 7'h6A;

// ---------------------------------------------------------------------------
// Internal registers
// ---------------------------------------------------------------------------

// Primary ALU input (32-bit, bit 0 = MSB)
reg [0:31] A;

// Multiply/divide pair with A (32-bit, bit 0 = MSB)
reg [0:31] B;

// Memory interface register with transparent mux (32-bit, bit 0 = MSB)
reg  [0:31] C;
wire [0:31] C_mux;      // presents C_in when C_load high, else C
wire        C_load;     // driven by control unit
wire [0:31] C_in;       // data to load into C

// Secondary ALU input (32-bit, bit 0 = MSB)
reg [0:31] D;

// Floating-point exponent register (8-bit, bit 0 = MSB)
reg [0:7] E;

// Opcode register (7-bit, Sigma bits 1-7)
reg [1:7] O;

// Register field register (4-bit, Sigma bits 8-11)
reg [8:11] R;

// Effective byte address register (19-bit, Sigma bits 15-33)
reg [15:33] P;

// Next instruction word address register (17-bit, Sigma bits 15-31)
reg [15:31] Q;

// Condition code register (4-bit, Sigma bits 1-4)
// CC[1]=carry, CC[2]=overflow, CC[3]=positive, CC[4]=negative
reg [1:4] CC;

// A-Was-Zero flip-flop for doubleword zero detection
reg AWZ;

// User-visible register file (16 x 32-bit, bit 0 = MSB)
reg [0:31] RR [0:15];

// ---------------------------------------------------------------------------
// Instruction field decode (from C_mux — available combinatorially via ENDE)
// ---------------------------------------------------------------------------
wire        inst_i    = C_mux[0];       // indirect bit   (Sigma bit 0)
wire [1:7]  inst_op   = C_mux[1:7];     // opcode         (Sigma bits 1-7)
wire [0:3]  inst_r    = C_mux[8:11];    // R field        (Sigma bits 8-11)
wire [0:2]  inst_x    = C_mux[12:14];   // X field        (Sigma bits 12-14)
wire [0:16] inst_addr = C_mux[15:31];   // address field  (Sigma bits 15-31)

// ---------------------------------------------------------------------------
// RR file address decode
// Access is to RR file if address bits 15:29 are all zero (addresses 0-15)
// Uses NOR reduction rather than comparator for simpler synthesis
// ---------------------------------------------------------------------------
wire        rr_access = ~|bus_addr[15:29];
wire [0:3]  rr_index  = bus_addr[30:33];
wire [0:31] rr_data_r = RR[rr_index];

// Memory read data mux — RR file or external memory
wire [0:31] mem_data_in = rr_access ? rr_data_r : bus_data_r;

// ---------------------------------------------------------------------------
// C register — synchronous with transparent mux
// C_mux presents C_in when C_load is asserted (before clock edge)
// ---------------------------------------------------------------------------
assign C_mux = C_load ? C_in : C;

always @(posedge clock)
    if (reset)
        C <= 32'b0;
    else if (C_load)
        C <= C_in;

// ---------------------------------------------------------------------------
// Phase register — one-hot shift register
// Default: shift left (next phase)
// Control unit asserts phase_load with one-hot target for jumps
// Stalls when bus not granted (cpu_grant = 0)
// ---------------------------------------------------------------------------
wire [0:18] phase_next;
wire        phase_load;   // assert to load phase_target instead of shifting
wire [0:18] phase_target; // jump target (one-hot)

assign phase_next = ~cpu_grant  ? phase :                    // stall
                     phase_load  ? phase_target :             // jump
                                   {phase[1:18], phase[0]};  // shift (next phase)

always @(posedge clock)
    if (reset)
        phase <= PREP1;
    else
        phase <= phase_next;

// ---------------------------------------------------------------------------
// Bus tri-state — CPU drives bus only when granted
// ---------------------------------------------------------------------------
wire [15:33] cpu_bus_addr;
wire [0:31]  cpu_bus_data_w;
wire         cpu_bus_write;
wire [0:1]   cpu_bus_size;

assign bus_addr   = cpu_grant ? cpu_bus_addr   : 19'bz;
assign bus_data_w = cpu_grant ? cpu_bus_data_w : 32'bz;
assign cpu_write  = cpu_grant ? cpu_bus_write  : 1'bz;
assign bus_size   = cpu_grant ? cpu_bus_size   : 2'bz;

// ---------------------------------------------------------------------------
// ALU operand size constants (for bus_size)
// ---------------------------------------------------------------------------
localparam SIZE_BYTE     = 2'b00;
localparam SIZE_HALFWORD = 2'b01;
localparam SIZE_WORD     = 2'b10;

// ---------------------------------------------------------------------------
// ALU operation constants
// ---------------------------------------------------------------------------
localparam ALU_ADD   = 4'b0000;
localparam ALU_SUB   = 4'b0001;
localparam ALU_AND   = 4'b0010;
localparam ALU_OR    = 4'b0011;
localparam ALU_XOR   = 4'b0100;
localparam ALU_INV   = 4'b0101;
localparam ALU_SHL1  = 4'b0110;
localparam ALU_SHR1  = 4'b0111;
localparam ALU_SHL4  = 4'b1000;
localparam ALU_SHR4  = 4'b1001;
localparam ALU_UALB  = 4'b1010;  // upward align byte
localparam ALU_UALH  = 4'b1011;  // upward align halfword
localparam ALU_PASSA = 4'b1100;  // pass A through
localparam ALU_PASSD = 4'b1101;  // pass D through

// ---------------------------------------------------------------------------
// A source select constants
// ---------------------------------------------------------------------------
localparam A_SEL_RR    = 3'b000;  // A ← RR[r]
localparam A_SEL_S     = 3'b001;  // A ← S (ALU output)
localparam A_SEL_C     = 3'b010;  // A ← C_mux
localparam A_SEL_ZERO  = 3'b011;  // A ← 0
localparam A_SEL_IDX   = 3'b100;  // A ← index (RR[x] shifted per operand size)

// ---------------------------------------------------------------------------
// D source select constants
// ---------------------------------------------------------------------------
localparam D_SEL_C    = 2'b00;   // D ← C_mux
localparam D_SEL_CC   = 2'b01;   // D ← CC
localparam D_SEL_IMM  = 2'b10;   // D ← sign-extended immediate

// ---------------------------------------------------------------------------
// P source select constants
// ---------------------------------------------------------------------------
localparam P_SEL_EA   = 2'b00;   // P[15:31] ← EA (from ALU), P[32:33] unchanged
localparam P_SEL_Q    = 2'b01;   // P[15:31] ← Q
localparam P_SEL_INC  = 2'b10;   // P ← P + 4

// ---------------------------------------------------------------------------
// CC type constants (which encoding to use)
// ---------------------------------------------------------------------------
localparam CC_ARITH   = 3'b000;  // arithmetic/load/logical
localparam CC_COMPARE = 3'b001;  // compare
localparam CC_ABS     = 3'b010;  // load absolute
localparam CC_COMP    = 3'b011;  // load complement
localparam CC_BYTE    = 3'b100;  // byte (CC3 only, CC4 never set)
localparam CC_ARITH_DW  = 3'b101; // doubleword arithmetic
localparam CC_COMPARE_DW = 3'b110; // doubleword compare
localparam CC_LCFI    = 3'b111;  // direct load from D[24:27]

// ---------------------------------------------------------------------------
// Control signal wires — driven by control unit
// ---------------------------------------------------------------------------

// Phase control
reg        phase_load_r;
reg [0:18] phase_target_r;
assign phase_load   = phase_load_r;
assign phase_target = phase_target_r;

// ENDE signal
reg ende;

// Register load enables and selects
reg        A_load;   reg [0:2] A_sel;
reg        B_load;
reg        C_load_r; reg [0:31] C_in_r;
reg        D_load;   reg [0:1]  D_sel;
reg        E_load;
reg        O_load;
reg        R_load;
reg        P_load;   reg [0:1]  P_sel;
reg        Q_load;
reg        CC_load;  reg [0:2]  CC_type;
reg        AWZ_load; reg        AWZ_in;
reg        RR_load;

// ALU operation
reg [0:3] alu_op;

// Bus control
reg [15:33] addr_r;
reg [0:31]  data_w_r;
reg         write_r;
reg [0:1]   size_r;

assign C_load        = C_load_r;
assign C_in          = C_in_r;
assign cpu_bus_addr  = addr_r;
assign cpu_bus_data_w = data_w_r;
assign cpu_bus_write = write_r;
assign cpu_bus_size  = size_r;

// ---------------------------------------------------------------------------
// Computed values used by control unit
// ---------------------------------------------------------------------------

// Effective address — A + inst_addr (word index), used in PREP3
wire [15:31] ea_word = A[15:31] + {14'b0, inst_addr};
wire [15:33] ea      = {ea_word, P[32:33]};  // preserve byte offset

// Sign-extended immediate (20-bit: inst_x concatenated with inst_addr)
wire [0:31] imm20 = {{12{C_mux[12]}}, C_mux[12:31]};

// Index value for A setup during ENDE — based on next instruction's x field
// Operand size determined by next instruction's opcode (from C_mux)
wire [0:31] idx_raw = RR[inst_x];
wire [0:31] idx_val =
    // Doubleword instructions: shift left 1 (multiply word index by 2)
    (inst_op == OP_AD  || inst_op == OP_SD  || inst_op == OP_CD  ||
     inst_op == OP_LD  || inst_op == OP_STD || inst_op == OP_LCD ||
     inst_op == OP_LAD) ? {idx_raw[1:31], 1'b0} :
    // Halfword instructions: shift right 1 (divide byte index by 2)
    (inst_op == OP_AH  || inst_op == OP_SH  || inst_op == OP_CH  ||
     inst_op == OP_LH  || inst_op == OP_STH || inst_op == OP_LCH ||
     inst_op == OP_LAH || inst_op == OP_MTH) ? {1'b0, idx_raw[0:30]} :
    // Byte instructions: shift right 2 (divide byte index by 4)
    (inst_op == OP_LB  || inst_op == OP_STB || inst_op == OP_CB  ||
     inst_op == OP_MTB) ? {2'b00, idx_raw[0:29]} :
    // Word instructions and default: no shift
    idx_raw;

// RR read port — combinatorial, used when A_sel = A_SEL_RR
wire [0:31] rr_read = RR[inst_r];

// ---------------------------------------------------------------------------
// ALU — combinatorial
// Inputs: A, D  Output: S
// ---------------------------------------------------------------------------
reg [0:31] S;
reg        alu_carry;
reg        alu_overflow;

always @(*) begin
    alu_carry    = 1'b0;
    alu_overflow = 1'b0;
    case (alu_op)
        ALU_ADD: begin
            {alu_carry, S} = {1'b0, A} + {1'b0, D};
            alu_overflow   = (A[0] == D[0]) && (S[0] != A[0]);
        end
        ALU_SUB: begin
            {alu_carry, S} = {1'b0, A} + {1'b0, ~D} + 33'b1;
            alu_overflow   = (A[0] != D[0]) && (S[0] != A[0]);
        end
        ALU_AND:   S = A & D;
        ALU_OR:    S = A | D;
        ALU_XOR:   S = A ^ D;
        ALU_INV:   S = ~A;
        ALU_SHL1:  S = {A[1:31], 1'b0};
        ALU_SHR1:  S = {1'b0, A[0:30]};
        ALU_SHL4:  S = {A[4:31], 4'b0};
        ALU_SHR4:  S = {4'b0, A[0:27]};
        ALU_UALB:  S = {A[24:31], A[24:31], A[24:31], A[24:31]};
        ALU_UALH:  S = {A[16:31], A[16:31]};
        ALU_PASSA: S = A;
        ALU_PASSD: S = D;
        default:   S = 32'b0;
    endcase
end

// ---------------------------------------------------------------------------
// Register file write — synchronous
// RR written when RR_load asserted and address in RR range
// ---------------------------------------------------------------------------
always @(posedge clock) begin
    if (RR_load && rr_access)
        RR[rr_index] <= S;
end

// ---------------------------------------------------------------------------
// Register updates — synchronous
// ---------------------------------------------------------------------------
always @(posedge clock) begin
    if (reset) begin
        A   <= 32'b0;
        B   <= 32'b0;
        // Initialize C and D with LCFI 0,0 (0x02000000) — executes as no-op
        // When ENDE fires, fetches real first instruction from M[Q=0]
        C   <= 32'h02000000;
        D   <= 32'h02000000;
        E   <= 8'b0;
        O   <= 7'h02;        // LCFI opcode
        R   <= 4'h0;
        P   <= 19'b0;
        Q   <= 17'b0;
        CC  <= 4'b0;
        AWZ <= 1'b0;
        // Initialize RR file to zero
        begin : rr_reset
            integer i;
            for (i = 0; i < 16; i = i + 1)
                RR[i] <= 32'b0;
        end
    end else begin
        // A register
        if (A_load) begin
            case (A_sel)
                A_SEL_RR:   A <= rr_read;
                A_SEL_S:    A <= S;
                A_SEL_C:    A <= C_mux;
                A_SEL_ZERO: A <= 32'b0;
                A_SEL_IDX:  A <= idx_val;  // index setup during ENDE
                default:    A <= A;
            endcase
        end

        // B register
        if (B_load) B <= A;

        // D register
        if (D_load) begin
            case (D_sel)
                D_SEL_C:   D <= C_mux;
                D_SEL_CC:  D <= {28'b0, CC};
                D_SEL_IMM: D <= imm20;
                default:   D <= D;
            endcase
        end

        // E register
        if (E_load) E <= S[24:31];

        // O register — loaded from C_mux on ENDE
        if (O_load) O <= C_mux[1:7];

        // R register — loaded from C_mux on ENDE
        if (R_load) R <= C_mux[8:11];

        // P register
        if (P_load) begin
            case (P_sel)
                P_SEL_EA:  P[15:31] <= ea_word;  // P[32:33] unchanged
                P_SEL_Q:   P[15:31] <= Q;
                P_SEL_INC: P        <= P + 19'd4;
                default:   P <= P;
            endcase
        end

        // Q register — loaded from P[15:31] in PREP1
        if (Q_load) Q <= P[15:31];

        // AWZ flip-flop
        if (AWZ_load) AWZ <= AWZ_in;
    end
end

// ---------------------------------------------------------------------------
// CC update — synchronous, separate always block for clarity
// ---------------------------------------------------------------------------
always @(posedge clock) begin
    if (reset) begin
        CC <= 4'b0;
    end else if (CC_load) begin
        case (CC_type)
            CC_ARITH: begin
                CC[1] <= alu_carry;
                CC[2] <= alu_overflow;
                CC[3] <= !S[0] && |S;       // positive: bit0=0 and nonzero
                CC[4] <= S[0];              // negative: bit0=1
            end
            CC_COMPARE: begin
                CC[1] <= 1'b0;
                CC[2] <= |(A & D);          // bits compare: AND nonzero
                CC[3] <= !S[0] && |S;       // reg > operand
                CC[4] <= S[0];              // reg < operand
            end
            CC_ABS: begin
                CC[1] <= 1'b0;
                CC[2] <= alu_overflow;
                CC[3] <= |S && !alu_overflow;
                CC[4] <= alu_overflow;
            end
            CC_COMP: begin
                CC[1] <= alu_carry;
                CC[2] <= alu_overflow;
                CC[3] <= !S[0] && |S && !alu_overflow;
                CC[4] <= S[0] || alu_overflow;
            end
            CC_BYTE: begin
                CC[1] <= 1'b0;
                CC[2] <= 1'b0;
                CC[3] <= |S[24:31];         // byte nonzero
                CC[4] <= 1'b0;              // never set for byte
            end
            CC_ARITH_DW: begin
                CC[1] <= alu_carry;
                CC[2] <= alu_overflow;
                CC[3] <= !S[0] && (|S || !AWZ);  // hi positive, or lo nonzero
                CC[4] <= S[0];
            end
            CC_COMPARE_DW: begin
                CC[1] <= 1'b0;
                CC[2] <= |(A & D);
                CC[3] <= !S[0] && |S;
                CC[4] <= S[0];
            end
            CC_LCFI: begin
                CC <= D[24:27];   // direct load from instruction bits 24-27
            end
            default: CC <= CC;
        endcase
    end
end

// ---------------------------------------------------------------------------
// Control unit — combinatorial
// case(phase) outer, case(O) inner
// All control signals default to inactive at top, then set per phase/opcode
// ---------------------------------------------------------------------------
always @(*) begin
    // ------------------------------------------------------------------
    // Defaults — all signals inactive
    // ------------------------------------------------------------------
    phase_load_r  = 1'b0;
    phase_target_r = PREP1;
    ende          = 1'b0;
    A_load        = 1'b0;  A_sel   = A_SEL_RR;
    B_load        = 1'b0;
    C_load_r      = 1'b0;  C_in_r  = 32'b0;
    D_load        = 1'b0;  D_sel   = D_SEL_C;
    E_load        = 1'b0;
    O_load        = 1'b0;
    R_load        = 1'b0;
    P_load        = 1'b0;  P_sel   = P_SEL_EA;
    Q_load        = 1'b0;
    CC_load       = 1'b0;  CC_type = CC_ARITH;
    AWZ_load      = 1'b0;  AWZ_in  = 1'b0;
    RR_load       = 1'b0;
    alu_op        = ALU_PASSA;
    addr_r        = {Q, 2'b00};   // default: present Q for instruction fetch
    data_w_r      = 32'b0;
    write_r       = 1'b0;
    size_r        = SIZE_WORD;

    // ------------------------------------------------------------------
    // ENDE actions — fired at last execute phase of each instruction
    // Loads next instruction fields from C_mux (already fetched via Q)
    // Sets up A and P[32:33] for next instruction's EA calculation
    // ------------------------------------------------------------------
    if (ende) begin
        O_load   = 1'b1;              // O ← C_mux[1:7]
        R_load   = 1'b1;              // R ← C_mux[8:11]
        C_load_r = 1'b1;              // C ← M[Q]
        C_in_r   = mem_data_in;
        P_load   = 1'b1;
        P_sel    = P_SEL_INC;         // P ← P + 4
        // A and P[32:33] setup based on next instruction's x field
        // (inst_x comes from C_mux which holds next instruction)
        if (inst_x == 3'b000) begin
            A_load = 1'b1;
            A_sel  = A_SEL_ZERO;      // no indexing
        end else begin
            A_load = 1'b1;
            A_sel  = A_SEL_IDX;       // index register (shift applied in datapath)
        end
    end

    // ------------------------------------------------------------------
    // Phase/opcode decode
    // ------------------------------------------------------------------
    case (1'b1)

        // --------------------------------------------------------------
        // PREP1 — save Q, set up mem_addr for indirect or EA
        // Common to all memory-reference instructions
        // --------------------------------------------------------------
        phase[0]: begin
            Q_load = 1'b1;            // Q ← P[15:31]
            // Present address field as indirect pointer (in case i=1)
            addr_r = {C_mux[15:31], 2'b00};
            if (!inst_i) begin
                phase_load_r   = 1'b1;
                phase_target_r = PREP3;  // skip PREP2 if not indirect
            end
        end

        // --------------------------------------------------------------
        // PREP2 — indirect resolution (only reached if i=1)
        // --------------------------------------------------------------
        phase[1]: begin
            C_load_r = 1'b1;
            C_in_r   = mem_data_in;   // C ← M[C[15:31]] (indirect word)
            D_load   = 1'b1;
            D_sel    = D_SEL_C;       // D ← C (instruction still in D)
            addr_r   = ea;            // present EA for EX1
        end

        // --------------------------------------------------------------
        // PREP3 — compute EA, load into P, present to memory
        // --------------------------------------------------------------
        phase[2]: begin
            P_load = 1'b1;
            P_sel  = P_SEL_EA;        // P[15:31] ← A + D[15:31], P[32:33] unchanged
            addr_r = ea;              // present EA one cycle early for EX1
        end

        // --------------------------------------------------------------
        // EX1 — first execute phase, varies by opcode
        // --------------------------------------------------------------
        phase[3]: begin
            case (O)
                // Arithmetic: load A from register file
                // Word: AW, SW, CW
                // Halfword: AH, SH, CH (mem fetch and compute in EX2)
                // Logical: AND, OR, EOR
                OP_AW, OP_SW, OP_CW,
                OP_AH, OP_SH, OP_CH,
                OP_AND, OP_OR, OP_EOR: begin
                    A_load = 1'b1;
                    A_sel  = A_SEL_RR;    // A ← RR[r]
                    addr_r = {Q, 2'b00};  // prepare next fetch
                end

                // Immediate: load A from register, D from immediate
                OP_AI, OP_CI: begin
                    A_load = 1'b1;  A_sel = A_SEL_RR;
                    D_load = 1'b1;  D_sel = D_SEL_IMM;
                    addr_r = {Q, 2'b00};
                end

                // Load immediate: A ← C_mux (immediate already in C)
                OP_LI: begin
                    A_load = 1'b1;
                    A_sel  = A_SEL_C;
                    addr_r = {Q, 2'b00};
                end

                // LCFI: if bit 10 set, load CC from bits 24-27
                // Otherwise no-op — CC_load=0 means CC unchanged
                OP_LCFI: begin
                    addr_r = {Q, 2'b00};
                end

                // Word load: C ← M[P], A ← C
                OP_LW, OP_LCW, OP_LAW: begin
                    C_load_r = 1'b1;
                    C_in_r   = mem_data_in;
                    A_load   = 1'b1;
                    A_sel    = A_SEL_C;
                    addr_r   = {Q, 2'b00};
                end

                // Halfword load: C ← M.H[P], sign extend to 32 bits
                // AH/SH/CH handled above with word arithmetic group
                OP_LH, OP_LCH, OP_LAH,
                OP_MTH: begin
                    C_load_r = 1'b1;
                    // Sign extend halfword from mem_data_in[16:31]
                    C_in_r   = {{16{mem_data_in[16]}}, mem_data_in[16:31]};
                    addr_r   = {Q, 2'b00};
                end

                // Byte load: C ← M.B[P], zero extend
                OP_LB, OP_CB, OP_MTB: begin
                    C_load_r = 1'b1;
                    C_in_r   = {24'b0, mem_data_in[24:31]};
                    addr_r   = {Q, 2'b00};
                end

                // Stores: load register to A
                OP_STW, OP_STH, OP_STB: begin
                    A_load = 1'b1;
                    A_sel  = A_SEL_RR;
                    addr_r = {Q, 2'b00};
                end

                // Doubleword load low word first
                OP_LD, OP_LCD, OP_LAD,
                OP_AD, OP_SD, OP_CD: begin
                    C_load_r = 1'b1;
                    C_in_r   = mem_data_in;  // low word (P+4)
                    addr_r   = {Q, 2'b00};
                end

                default: addr_r = {Q, 2'b00};
            endcase
        end

        // --------------------------------------------------------------
        // EX2 — second execute phase
        // --------------------------------------------------------------
        phase[4]: begin
            case (O)
                // LCFI: CC_load gated by bit 10, then ENDE
                OP_LCFI: begin
                    CC_load = D[10];
                    CC_type = CC_LCFI;
                    ende    = 1'b1;
                    addr_r  = {Q, 2'b00};
                end

                // Word arithmetic: fetch mem operand, compute, write back
                OP_AW: begin
                    C_load_r = 1'b1; C_in_r = mem_data_in;
                    D_load   = 1'b1; D_sel  = D_SEL_C;
                    alu_op   = ALU_ADD;
                    A_load   = 1'b1; A_sel  = A_SEL_S;
                    RR_load  = 1'b1;
                    addr_r   = {Q, 2'b00};
                end

                OP_SW: begin
                    C_load_r = 1'b1; C_in_r = mem_data_in;
                    D_load   = 1'b1; D_sel  = D_SEL_C;
                    alu_op   = ALU_SUB;
                    A_load   = 1'b1; A_sel  = A_SEL_S;
                    RR_load  = 1'b1;
                    addr_r   = {Q, 2'b00};
                end

                OP_CW: begin
                    C_load_r = 1'b1; C_in_r = mem_data_in;
                    D_load   = 1'b1; D_sel  = D_SEL_C;
                    alu_op   = ALU_SUB;
                    A_load   = 1'b1; A_sel  = A_SEL_S;
                    addr_r   = {Q, 2'b00};
                end

                // Immediate arithmetic
                OP_AI: begin
                    alu_op  = ALU_ADD;
                    A_load  = 1'b1; A_sel = A_SEL_S;
                    RR_load = 1'b1;
                    addr_r  = {Q, 2'b00};
                end

                OP_CI: begin
                    alu_op = ALU_SUB;
                    A_load = 1'b1; A_sel = A_SEL_S;
                    addr_r = {Q, 2'b00};
                end

                OP_LI: begin
                    alu_op  = ALU_PASSA;
                    RR_load = 1'b1;
                    addr_r  = {Q, 2'b00};
                end

                // Word load: route to register
                OP_LW: begin
                    alu_op  = ALU_PASSA;
                    RR_load = 1'b1;
                    P_load  = 1'b1; P_sel = P_SEL_Q;  // P[15:31] ← Q
                    addr_r  = {Q, 2'b00};
                end

                // Word store: write A to memory
                OP_STW: begin
                    alu_op  = ALU_PASSA;
                    write_r = 1'b1;
                    size_r  = SIZE_WORD;
                    data_w_r = A;
                    addr_r  = {Q, 2'b00};
                    ende    = 1'b1;   // STW ends here (no CC update)
                end

                // Load complemented word
                OP_LCW: begin
                    D_load  = 1'b1; D_sel = D_SEL_C;
                    alu_op  = ALU_SUB;   // ~D+1 via SUB with A=0
                    A_load  = 1'b1; A_sel = A_SEL_ZERO;
                    addr_r  = {Q, 2'b00};
                end

                // Load absolute word
                OP_LAW: begin
                    D_load = 1'b1; D_sel = D_SEL_C;
                    if (C_mux[0]) begin  // negative
                        alu_op = ALU_SUB;
                        A_load = 1'b1; A_sel = A_SEL_ZERO;
                    end else begin       // positive — pass through
                        alu_op = ALU_PASSD;
                        A_load = 1'b1; A_sel = A_SEL_S;
                        RR_load = 1'b1;
                        phase_load_r   = 1'b1;
                        phase_target_r = EX4;  // skip EX3, goto EX4
                    end
                    addr_r = {Q, 2'b00};
                end

                // Logical
                OP_AND: begin
                    C_load_r = 1'b1; C_in_r = mem_data_in;
                    D_load   = 1'b1; D_sel  = D_SEL_C;
                    alu_op   = ALU_AND;
                    A_load   = 1'b1; A_sel  = A_SEL_S;
                    RR_load  = 1'b1;
                    addr_r   = {Q, 2'b00};
                end

                OP_OR: begin
                    C_load_r = 1'b1; C_in_r = mem_data_in;
                    D_load   = 1'b1; D_sel  = D_SEL_C;
                    alu_op   = ALU_OR;
                    A_load   = 1'b1; A_sel  = A_SEL_S;
                    RR_load  = 1'b1;
                    addr_r   = {Q, 2'b00};
                end

                OP_EOR: begin
                    C_load_r = 1'b1; C_in_r = mem_data_in;
                    D_load   = 1'b1; D_sel  = D_SEL_C;
                    alu_op   = ALU_XOR;
                    A_load   = 1'b1; A_sel  = A_SEL_S;
                    RR_load  = 1'b1;
                    addr_r   = {Q, 2'b00};
                end

                // Halfword arithmetic: fetch halfword, sign extend, compute
                OP_AH: begin
                    C_load_r = 1'b1;
                    C_in_r   = {{16{mem_data_in[16]}}, mem_data_in[16:31]};
                    D_load   = 1'b1; D_sel = D_SEL_C;
                    alu_op   = ALU_ADD;
                    A_load   = 1'b1; A_sel = A_SEL_S;
                    RR_load  = 1'b1;
                    addr_r   = {Q, 2'b00};
                end

                OP_SH: begin
                    C_load_r = 1'b1;
                    C_in_r   = {{16{mem_data_in[16]}}, mem_data_in[16:31]};
                    D_load   = 1'b1; D_sel = D_SEL_C;
                    alu_op   = ALU_SUB;
                    A_load   = 1'b1; A_sel = A_SEL_S;
                    RR_load  = 1'b1;
                    addr_r   = {Q, 2'b00};
                end

                OP_CH: begin
                    C_load_r = 1'b1;
                    C_in_r   = {{16{mem_data_in[16]}}, mem_data_in[16:31]};
                    D_load   = 1'b1; D_sel = D_SEL_C;
                    alu_op   = ALU_SUB;
                    A_load   = 1'b1; A_sel = A_SEL_S;
                    addr_r   = {Q, 2'b00};
                end

                // Halfword load: sign extend, write to register
                OP_LH: begin
                    alu_op  = ALU_PASSA;
                    RR_load = 1'b1;
                    addr_r  = {Q, 2'b00};
                end

                // Halfword store
                OP_STH: begin
                    alu_op   = ALU_UALH;
                    write_r  = 1'b1;
                    size_r   = SIZE_HALFWORD;
                    data_w_r = S;
                    addr_r   = {Q, 2'b00};
                    ende     = 1'b1;
                end

                // Byte load: write to register
                OP_LB: begin
                    alu_op  = ALU_PASSA;
                    RR_load = 1'b1;
                    addr_r  = {Q, 2'b00};
                end

                // Byte store
                OP_STB: begin
                    alu_op   = ALU_UALB;
                    write_r  = 1'b1;
                    size_r   = SIZE_BYTE;
                    data_w_r = S;
                    addr_r   = {Q, 2'b00};
                    ende     = 1'b1;
                end

                default: addr_r = {Q, 2'b00};
            endcase
        end

        // --------------------------------------------------------------
        // EX3 — third execute phase (CC update + ENDE for most instructions)
        // --------------------------------------------------------------
        phase[5]: begin
            case (O)
                // Arithmetic/logical: update CC and end
                OP_AW, OP_SW, OP_AI: begin
                    CC_load = 1'b1; CC_type = CC_ARITH;
                    ende    = 1'b1;
                end

                OP_CW, OP_CI: begin
                    CC_load = 1'b1; CC_type = CC_COMPARE;
                    ende    = 1'b1;
                end

                OP_LI, OP_LW: begin
                    CC_load = 1'b1; CC_type = CC_ARITH;
                    ende    = 1'b1;
                end

                OP_AND, OP_OR, OP_EOR: begin
                    CC_load = 1'b1; CC_type = CC_ARITH;
                    ende    = 1'b1;
                end

                OP_AH, OP_SH: begin
                    CC_load = 1'b1; CC_type = CC_ARITH;
                    ende    = 1'b1;
                end

                OP_CH: begin
                    CC_load = 1'b1; CC_type = CC_COMPARE;
                    ende    = 1'b1;
                end

                OP_LH: begin
                    CC_load = 1'b1; CC_type = CC_ARITH;
                    ende    = 1'b1;
                end

                OP_LB: begin
                    CC_load = 1'b1; CC_type = CC_BYTE;
                    ende    = 1'b1;
                end

                // LCW: result in A, write to RR
                OP_LCW: begin
                    A_load  = 1'b1; A_sel  = A_SEL_S;
                    RR_load = 1'b1;
                    addr_r  = {Q, 2'b00};
                end

                // LAW negative case: write result to RR
                OP_LAW: begin
                    A_load  = 1'b1; A_sel  = A_SEL_S;
                    RR_load = 1'b1;
                    addr_r  = {Q, 2'b00};
                end

                default: addr_r = {Q, 2'b00};
            endcase
        end

        // --------------------------------------------------------------
        // EX4 — LCW CC update; LAW CC update (both paths)
        // --------------------------------------------------------------
        phase[6]: begin
            case (O)
                OP_LCW: begin
                    CC_load = 1'b1; CC_type = CC_COMP;
                    ende    = 1'b1;
                end

                OP_LAW: begin
                    CC_load = 1'b1; CC_type = CC_ABS;
                    ende    = 1'b1;
                end

                default: addr_r = {Q, 2'b00};
            endcase
        end

        default: addr_r = {Q, 2'b00};

    endcase
end

endmodule