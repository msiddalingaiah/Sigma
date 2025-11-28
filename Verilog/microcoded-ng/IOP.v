
/*
Memory is word addressed, 17 bits
*/
module IOP(input wire reset, input wire clock, input wire active, output wire [15:31] memory_address,
    input wire [0:31] memory_data_in, output [0:31] memory_data_out, output [0:3] wr_enables,
    input wire [0:2] iop_func, input wire [0:2] iop_addr, output reg [0:1] iop_cc);

    // memory address lines
    reg [15:31] lb;
    // memory output data
    reg [0:31] mb;
    // memory write enables
    reg [0:3] wr_en;

    assign memory_address = active ? lb : 17'bZ;
    assign memory_data_out = active ? mb : 32'bZ;
    assign wr_enables = active ? wr_en : 4'bZ;

    // Guideline #3: When modeling combinational logic with an "always" block, use blocking assignments ( = ).
    // Order matters here!!!
    always @(*) begin
        lb = 17'h0;
        wr_en = 4'h0;
    end

    // Guideline #1: When modeling sequential logic, use nonblocking assignments ( <= ).
    always @(posedge clock, posedge reset) begin
        if (reset == 1) begin
        end else begin
            if (active) begin
            end
        end
    end
endmodule