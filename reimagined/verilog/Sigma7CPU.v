// SDS/Xerox Sigma 7 CPU — Minimal implementation: LCFI and LW only
// Synchronous memory: address presented on cycle N, data valid on cycle N+1
// Big-endian: bit 0 is MSB throughout

module Sigma7CPU (
    input  wire        clock,
    input  wire        reset,
    input  wire        cpu_grant,
    output wire        cpu_release,
    output reg  [15:33] bus_addr,
    input  wire [0:31] bus_data_r,
    output wire [0:31] bus_data_w,
    output wire        cpu_write,
    output wire [0:1]  bus_size
);

localparam OP_LCFI = 7'h02;
localparam OP_LW   = 7'h32;
localparam OP_STW  = 7'h35;
localparam OP_LI   = 7'h22;

// ---------------------------------------------------------------------------
// Phase register (one-hot, bit 0 = PCP5 = MSB)
// ---------------------------------------------------------------------------
reg [0:19] phase;

localparam PCP5  = 20'b10000000000000000000;
localparam PREP1 = 20'b01000000000000000000;
localparam PREP2 = 20'b00100000000000000000;
localparam PREP3 = 20'b00010000000000000000;
localparam EX1   = 20'b00001000000000000000;
localparam EX2   = 20'b00000100000000000000;
localparam EX3   = 20'b00000010000000000000;

// Phase name string for GTKWave ASCII display
// Right-click signal → Data Format → ASCII
reg [0:63] phase_name;  // 8 characters × 8 bits
always @(*) begin
    casez (phase)
        20'b1???????????????????: phase_name = "PCP5    ";
        20'b01??????????????????: phase_name = "PREP1   ";
        20'b001?????????????????: phase_name = "PREP2   ";
        20'b0001????????????????: phase_name = "PREP3   ";
        20'b00001???????????????: phase_name = "EX1     ";
        20'b000001??????????????: phase_name = "EX2     ";
        20'b0000001?????????????: phase_name = "EX3     ";
        default:                  phase_name = "UNKNOWN ";
    endcase
end

// ---------------------------------------------------------------------------
// Internal registers
// ---------------------------------------------------------------------------
reg [0:31]  A;
reg [0:31]  C;          // memory interface register (transparent latch)
reg [0:31]  D;          // current instruction word
reg [1:7]   O;          // opcode
reg [8:11]  R;          // register field
reg [15:33] P;          // effective byte address
reg [15:31] Q;          // next instruction word address
reg [0:31]  RR [0:15];  // user register file

initial begin
    A = 32'b0;
    C = 32'h02000000;   // LCFI no-op
    D = 32'h02000000;   // LCFI no-op
    O = 7'h02;
    R = 4'h0;
    P = 19'h00094;      // byte address 0x94 = {word 0x25, 2'b00}
    Q = 17'h25;         // word address 0x25 → p_inc = 0x98 = word 0x26
end

// ---------------------------------------------------------------------------
// C register — synchronous with transparent mux
// When C_load=1, C_mux presents bus_data_r immediately (before clock edge)
// On clock edge, C is latched with bus_data_r
// ---------------------------------------------------------------------------
reg C_load;
wire [0:31] C_mux = C_load ? bus_data_r : C;

// ---------------------------------------------------------------------------
// RR file — NOR decode for addresses 0-15
// ---------------------------------------------------------------------------
wire        rr_access  = ~|bus_addr[15:29];
wire [0:3]  rr_index   = bus_addr[30:33];
// mem_data_in: RR file or external memory (registered output)
wire [0:31] mem_data_in = rr_access ? RR[rr_index] : bus_data_r;

// ---------------------------------------------------------------------------
// Computed values
// ---------------------------------------------------------------------------
wire [15:33] p_inc   = P + 19'd4;
wire [15:31] ea_word = A[15:31] + {14'b0, D[15:31]};
wire [15:33] ea      = {ea_word, P[32:33]};
wire [0:31]  imm20   = {{12{D[12]}}, D[12:31]};  // sign-extended 20-bit immediate

// ---------------------------------------------------------------------------
// Bus outputs
// ---------------------------------------------------------------------------
reg         write_r;
reg [0:31]  data_w_r;
reg [0:1]   size_r;

assign bus_data_w  = data_w_r;
assign cpu_write   = write_r;
assign bus_size    = size_r;
assign cpu_release = 1'b0;

// ---------------------------------------------------------------------------
// Control signals
// ---------------------------------------------------------------------------
reg        ende;
reg        phase_jump;
reg [0:19] phase_target;
reg        D_load;
reg        O_load;
reg        R_load;
reg        A_load;   reg [0:31]  A_in;
reg        P_load;   reg [15:33] P_in;
reg        Q_load;
reg        rr_write;
// rr_data declared above with RR file write block

// ---------------------------------------------------------------------------
// Phase sequencer
// ---------------------------------------------------------------------------
always @(posedge clock) begin
    if (reset)
        phase <= PCP5;
    else if (!cpu_grant)
        phase <= phase;          // stall
    else if (phase_jump)
        phase <= phase_target;   // jump (includes ENDE → PREP1)
    else if (!phase[0])          // only shift if not in PCP5
        phase <= {1'b0, phase[0:18]};
    // else stay in PCP5
end

// ---------------------------------------------------------------------------
// Register updates
// ---------------------------------------------------------------------------
always @(posedge clock) begin
    if (reset) begin
        A <= 32'b0;
        C <= 32'h02000000;
        D <= 32'h02000000;
        O <= 7'h02;
        R <= 4'h0;
        P <= 19'h00094;   // byte 0x94 so p_inc = 0x98 = word 0x26
        Q <= 17'h25;      // word 0x25
    end else begin
        if (C_load) C <= bus_data_r;       // C latches memory data
        if (D_load) D <= C_mux;            // D ← C_mux (transparent)
        if (O_load) O <= C_mux[1:7];       // O ← C_mux (transparent)
        if (R_load) R <= C_mux[8:11];      // R ← C_mux (transparent)
        if (A_load) A <= A_in;
        if (P_load) P <= P_in;
        if (Q_load) Q <= P[15:31];
    end
end

// RR file write
reg [0:31] rr_data;  // data to write to RR file

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
//
// Synchronous memory timing:
//   Address on bus_addr in phase N → data in mem_data_in in phase N+1
//
// Phase sequence for LCFI (no indirect):
//   ENDE:  bus_addr=p_inc → instruction arrives at PREP1
//   PREP1: read instr (mem_data_in=M[p_inc]), load D/O/R/Q
//          bus_addr={D[15:31],0} → not used (no indirect), present for PREP2
//          jump to PREP3 (not indirect)
//   PREP3: bus_addr=ea → M[ea] arrives at EX1 (not needed for LCFI)
//          P ← ea
//   EX1:   bus_addr={Q,0} → next instr arrives at PREP1 of next instruction
//   EX2:   ende=1 → P←p_inc, bus_addr=p_inc (next instr addr)
//
// Phase sequence for LW (no indirect):
//   Same PREP1/PREP3 as above
//   EX1:   A ← mem_data_in = M[ea] (from PREP3 address), bus_addr={Q,0}
//   EX2:   RR[r] ← A, bus_addr={Q,0}
//   EX3:   ende=1 → P←p_inc, bus_addr=p_inc
// ---------------------------------------------------------------------------
always @(*) begin
    // Defaults
    ende         = 1'b0;
    rr_write     = 1'b0;
    rr_data      = A;     // default: write A to RR
    write_r      = 1'b0;
    data_w_r     = 32'b0;
    size_r       = 2'b10;  // word
    phase_jump   = 1'b0;
    phase_target = PREP1;
    C_load       = 1'b0;
    D_load       = 1'b0;
    O_load       = 1'b0;
    R_load       = 1'b0;
    A_load       = 1'b0;  A_in = 32'b0;
    P_load       = 1'b0;  P_in = P;
    Q_load       = 1'b0;
    bus_addr     = {Q, 2'b00};  // default: present Q so instruction ready next cycle

    case (1'b1)

        // ------------------------------------------------------------------
        // PCP5: assert ENDE only when not in reset
        // Holds here during reset, fires once reset is released
        // ------------------------------------------------------------------
        phase[0]: begin
            if (!reset) ende = 1'b1;
        end

        // ------------------------------------------------------------------
        // PREP1: bus_data_r = next instruction from memory
        // ------------------------------------------------------------------
        phase[1]: begin
            C_load = 1'b1;
            D_load = 1'b1;
            O_load = 1'b1;
            R_load = 1'b1;
            Q_load = 1'b1;
            A_load = 1'b1;
            A_in   = 32'b0;
            // bus_addr stays as default {Q,2'b00} — no need to change here
            // For indirect: PREP2 will present {D[15:31],2'b00} using registered D
            if (!bus_data_r[0]) begin
                phase_jump   = 1'b1;
                // Immediate instructions skip PREP3 EA calc
                if (bus_data_r[1:7] == OP_LCFI ||
                    bus_data_r[1:7] == OP_LI)
                    phase_target = EX1;
                else
                    phase_target = PREP3;
            end
        end

        // ------------------------------------------------------------------
        // PREP2: indirect resolution — D has instruction addr field
        // ------------------------------------------------------------------
        phase[2]: begin
            C_load   = 1'b1;
            D_load   = 1'b1;
            bus_addr = {D[15:31], 2'b00};     // D now registered from PREP1
        end

        // ------------------------------------------------------------------
        // PREP3: EA → P, present to memory so M[EA] ready at EX1
        // ------------------------------------------------------------------
        phase[3]: begin
            P_load   = 1'b1;
            P_in     = ea;
            bus_addr = ea;
        end

        // ------------------------------------------------------------------
        // EX1: bus_data_r = M[EA] (from PREP3)
        // ------------------------------------------------------------------
        phase[4]: begin
            case (O)
                OP_LCFI: bus_addr = {Q, 2'b00};
                OP_LI:   bus_addr = {Q, 2'b00};  // immediate in D, nothing to fetch
                OP_LW: begin
                    C_load   = 1'b1;
                    A_load   = 1'b1;
                    A_in     = C_mux;
                    bus_addr = {Q, 2'b00};
                end
                OP_STW: begin
                    A_load   = 1'b1;
                    A_in     = RR[R];
                    bus_addr = {Q, 2'b00};
                end
                default: bus_addr = {Q, 2'b00};
            endcase
        end

        // ------------------------------------------------------------------
        // EX2
        // ------------------------------------------------------------------
        phase[5]: begin
            case (O)
                OP_LCFI: ende = 1'b1;
                OP_LI: begin
                    rr_data  = imm20;         // RR[R] ← imm20 directly
                    rr_write = 1'b1;
                    ende     = 1'b1;
                end
                OP_LW: begin
                    rr_write = 1'b1;
                    P_load   = 1'b1;
                    P_in     = {Q, 2'b00};
                    bus_addr = {Q, 2'b00};
                end
                OP_STW: begin
                    write_r  = 1'b1;
                    data_w_r = A;
                    size_r   = 2'b10;
                    bus_addr = P;
                    P_load   = 1'b1;
                    P_in     = {Q, 2'b00};
                end
                default: bus_addr = {Q, 2'b00};
            endcase
        end

        // ------------------------------------------------------------------
        // EX3: LW and STW ENDE
        // ------------------------------------------------------------------
        phase[6]: begin
            case (O)
                OP_LW:   ende = 1'b1;
                OP_STW:  ende = 1'b1;
                default: bus_addr = {Q, 2'b00};
            endcase
        end

        default: bus_addr = {Q, 2'b00};

    endcase

    // ------------------------------------------------------------------
    // ENDE: P ← P+4, present p_inc → M[p_inc] ready at PREP1
    // ------------------------------------------------------------------
    if (ende) begin
        P_load       = 1'b1;
        P_in         = p_inc;
        bus_addr     = p_inc;
        phase_jump   = 1'b1;
        phase_target = PREP1;
    end

end

endmodule