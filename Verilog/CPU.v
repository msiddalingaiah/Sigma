
// Memory is word addressed, 17 bits
module CPU(input wire reset, input wire clock, input wire [0:31] data, output reg [15:31] lb);
    // c is a transparent latch, see pp 3-38, receives data from memory
    // d always has a bit 71, maybe consider making these extension registers?
    reg [0:31] a, b, c, d;
    // e is a counting register
    reg [0:7] e;
    reg [1:4] cc;
    reg [0:33] cs;
    // opcode register
    reg [1:7] o;
    // p is a counting register, acts as the program counter in conjunction with q
    reg [15:33] p;
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
    wire lmxc, lmxq;

    // Memory address logic (no map), see pp 3-198
    lb[15:30] = p[15:30];
    if (lmxq == 1) begin
        lb[15:22] = q[15:22];
    end
    if (lmxc == 1) begin
        lb[15:30] = c[15:30];
    end
endmodule
