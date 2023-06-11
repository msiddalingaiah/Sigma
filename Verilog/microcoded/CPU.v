
`include "Sequencer.v"
`include "CodeROM.v"
`include "MapROM.v"

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
    wire [0:39] uc_rom_data;
    CodeROM uc_rom(uc_rom_address, uc_rom_data);
    // Microcode pipeline register
    // 0       8       16      24      32      40
    // |-------|-------|-------|-------|-------|
    //    op                        | uc_din  |
    //  mx - 0 = pipeline, 1 = instruction map ROM, 2, 3 = unused
    // 4:27 - control 24 bits
    //     register write enables (10)
    //     p inc (1)
    //     memory address mux (2)
    //     memory write enable (1)
    //     ALU op (4)
    reg [0:39] pipeline;
    wire [0:2] branch_select = pipeline[4:6];
    reg branch;
    // See datapath pp 3-7
    wire [0:20] control = pipeline[7:27];
    wire [0:3] sxop = control[0:3];
    wire [0:1] lb_select = control[4:5];
    wire [0:2] p_count = control[6:8];
    wire cxm = control[9];
    wire orxm = control[10];
    wire qxp = control[11];

    // Instruction map ROM
    wire [0:6] op_rom_address = o;
    wire [0:11] op_rom_data;
    MapROM op_rom(op_rom_address, op_rom_data);

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

    // Guideline #3: When modeling combinational logic with an "always" 
    //              block, use blocking assignments.
    always @(*) begin
        // Sequencer d_in mux
        case (pipeline[0:1])
            0: uc_din = pipeline[28:39]; // jump or call
            1: uc_din = op_rom_data; // instruction map ROM
            2: uc_din = 0; // not used
            3: uc_din = 0; // not used
        endcase
        case (branch_select)
            0: branch = 1; // branch unconditionally
            1: branch = e == 1;
            2: branch = 1;
            3: branch = 1;
            4: branch = 1;
            5: branch = 1;
            6: branch = 1;
            7: branch = 1;
        endcase
        uc_op = pipeline[2:3];
        case (pipeline[2:3])
            0: uc_op = { 1'h0, ~branch }; // next, invert selected branch condition
            1: uc_op = { 1'h0, branch }; // jump
            2: ; // call
            3: ; // return
        endcase
    end

    // Guideline #1: When modeling sequential logic, use nonblocking 
    //              assignments.
    always @(posedge clock, posedge reset) begin
        if (reset == 1) begin
            a <= 0;
            b <= 0;
            c <= 0;
            d <= 0;
            o <= 0;
            p <= 0;
            q <= 0;
            r <= 0;
            e <= 0;
            pipeline <= 0;
        end else begin
            pipeline <= uc_rom_data;
            //o <= 1;
        end
    end
endmodule
