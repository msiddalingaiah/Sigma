
`include "Sequencer.v"
`include "CodeROM.v"

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
    //  mx - sequencer d_in mux: 0 = pipeline, 1 = instruction, 2, 3 = unused
    // 7:27 - control 21 bits
    //     register write enables (10)
    //     p inc (1)
    //     memory address mux (2)
    //     memory write enable (1)
    //     ALU op (4)
    reg [0:39] pipeline;
    wire [0:1] pipeline_op = pipeline[2:3];
    wire [0:2] condition = pipeline[4:6];
    // See datapath pp 3-7

    wire [0:20] control = pipeline[7:27];
    wire [0:3] sxop = control[0:3];
    wire ende = control[4];
    wire testa = control[5];
    wire axc = control[6];
    wire rrxa = control[7];
    wire wd_en = control[8];
    wire dxm1 = control[9];
    wire axrr = control[10];
    wire axs = control[11];
    wire exconst8 = control[12];
    wire [0:1] e_count = control[13:14];
    wire pxqxp = control[15];
    wire pxd = control[16];
    wire rrxs = control[17];
    wire uc_debug = control[20];

    wire [0:7] const8 = pipeline[32:39];
    wire [0:11] jump_address = pipeline[28:39];

    reg branch;

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
    reg [15:31] p;
    // Phase register, one-hot encoded
    reg [0:7] phase;
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

    // Signals

    // Guideline #3: When modeling combinational logic with an "always" 
    //              block, use blocking assignments.
    always @(*) begin
        // Sequencer d_in mux
        case (pipeline[0:1])
            0: uc_din = jump_address; // jump or call
            1: uc_din = o; // instruction op code
            2: uc_din = 0; // not used
            3: uc_din = 0; // not used
        endcase
        case (condition)
            0: branch = 0; // branch unconditionally
            1: branch = e == 0; // COND_EQ_ZERO
            2: branch = ~(s[0] | (s == 0)); // COND_S_GT_ZERO
            3: branch = 0;
            4: branch = 0;
            5: branch = 0;
            6: branch = 0;
            7: branch = 0;
        endcase
        uc_op = pipeline_op;
        case (pipeline_op)
            0: uc_op = { 1'h0, branch }; // next, invert selected branch condition
            1: uc_op = { 1'h0, ~branch }; // jump
            2: ; // call
            3: ; // return
        endcase
        s = 0;
        case (sxop)
            0: s = a+d;
        endcase
        lb = p;
    end

    // Guideline #1: When modeling sequential logic, use nonblocking 
    //              assignments.
    always @(posedge clock, posedge reset) begin
        if (reset == 1) begin
            a <= 0;
            b <= 0;
            c <= 0;
            cc <= 0;
            d <= 0;
            o <= 0;
            p <= 0;
            q <= 0;
            r <= 0;
            e <= 0;
            pipeline <= 0;
        end else begin
            pipeline <= uc_rom_data;
            if (exconst8 == 1) e <= const8;
            case (e_count)
                0: ;
                1: e <= e + 1;
                2: e <= e - 1;
                3: ;
            endcase
            if (ende == 1) begin
                c <= c_in; d <= c_in; o <= c_in[1:7]; r <= c_in[8:11]; p <= p + 1;
            end
            if (axc == 1) begin a <= { {12{c[12]}}, c[12:31] }; end
            if (axs == 1) begin a <= s; end
            if (axrr == 1) begin a <= rr[r]; end
            if (rrxa == 1) begin rr[r] <= a; end
            if (rrxs == 1) begin rr[r] <= s; end
            if (testa == 1) begin cc[3] <= (~a[0]) & (a != 0); cc[4] <= a[0]; end
            if (dxm1 == 1) begin d <= 32'hffffffff; end
            if (pxqxp == 1) begin p <= q; q <= p; end
            if (pxd == 1) begin p <= d[15:31]; end
            if (wd_en == 1) begin
                // $display("wd_en, d[24:31] = %x, r = %x, rr[r][25:31]", d[24:31], r, rr[r][25:31]);
                if ((d[24:31] == 0) && (r != 0)) begin
                    $write("%s", rr[r][25:31]);
                end
            end
            if (uc_debug == 1) begin
                $display("%4d: op %1d, branch: %1d, s %x", seq.pc-1, seq.op, branch, s);
            end
        end
    end
endmodule
