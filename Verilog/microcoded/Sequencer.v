
/**
 * This module implements a simplified microprogram sequencer inspired by the AMD 2909.
 *
 * There are a few differences:
 *   1. Fixed width vs. bit slice
 *   2. Four sequence operations: next, jump, call, return
 *   3. Remove OR inputs
 *   4. Relative jump, call
 *
 * See https://github.com/Nakazoto/CenturionComputer/blob/main/Computer/CPU6%20Board/Datasheets/am2909_am2911.pdf
 */

module Sequencer(input wire reset, input wire clock, input wire active, input wire [1:0] op, input wire [11:0] din, output reg [11:0] yout);

    reg [11:0] pc;
    reg [1:0] sp, stackAddr;
    reg [11:0] mux;
    reg stackWr;
    reg [11:0] stack[0:3];

    integer i;
    initial begin
        pc = 0;
        sp = 3;
        yout = 0;
        mux = 0;
        stackWr = 0;
        for (i=0;i<4;i=i+1) stack[i] = 0;
    end

    // Guideline #3: When modeling combinational logic with an "always" 
    //              block, use blocking assignments.
    always @(*) begin        
        stackWr = 0;
        stackAddr = sp;
        case (op)
            0: mux = pc;  // next
            1: begin mux = din+pc; end // jump
            2: begin mux = din+pc; stackAddr = sp + 1; stackWr = 1; end // call
            3: mux = stack[stackAddr]; // return
        endcase
        yout = mux;
    end

    // Guideline #1: When modeling sequential logic, use nonblocking 
    //              assignments.
    always @(posedge clock, posedge reset) begin
		if (reset == 1) begin
            pc = 0;
            sp = 3;
		end else begin
            if (active) begin
                if (stackWr == 1) begin
                    stack[stackAddr] <= pc;
                end
                case (op)
                    0: ;  // next
                    1: ;  // jump
                    2: sp <= sp + 1; // call
                    3: sp <= sp - 1; // return
                endcase
                pc <= yout + 1;
            end
		end
    end
endmodule
