
/*
Memory is word addressed, 17 bits

X'001' IOP 0, device controller 1, keyboard/printer
X'002' IOP 0, device controller 2, line printer
X'003' IOP 0, device controller 3, card reader
X'004' IOP 0, device controller 4, card punch
X'005' IOP 0, device controller 5, paper tape reader/punch 

*/
module IOP(input wire reset, input wire clock, input wire active, output wire [15:31] memory_address,
    input wire [0:31] memory_data_in, output [0:31] memory_data_out, output [0:3] wr_enables,
    input wire [0:2] iop_func, input wire [21:31] iop_device, output reg [0:1] iop_cc);

    // memory address lines
    reg [15:31] lb;
    // memory output data
    reg [0:31] mb;
    // memory write enables
    reg [0:3] wr_en;

    assign memory_address = active ? lb : 17'bZ;
    assign memory_data_out = active ? mb : 32'bZ;
    assign wr_enables = active ? wr_en : 4'bZ;

    reg [0:3] phase;
    reg [0:2] iop;
    reg [0:7] device;

    localparam FNC_SIO = 0;
    localparam FNC_TIO = 1;
    localparam FNC_TDV = 2;
    localparam FNC_HIO = 3;
    localparam FNC_AIO = 6;

    // Guideline #3: When modeling combinational logic with an "always" block, use blocking assignments ( = ).
    // Order matters here!!!
    always @(*) begin
        iop = iop_device[21:23];
        device = iop_device[24:31];
    end

    // Guideline #1: When modeling sequential logic, use nonblocking assignments ( <= ).
    always @(posedge clock, posedge reset) begin
        if (reset == 1) begin
            phase <= 0;
            wr_en <= 0;
            lb <= 0;
            mb <= 0;
        end else begin
            if (active) begin
                if (iop_func == FNC_SIO) begin
                    if (phase == 0) begin
                        $display("IOP %x, Device %x: Start IO", iop, device);
                        lb <= 17'h2a;
                        mb <= 32'h32100021;
                        wr_en <= 4'hf;
                        phase <= 1;
                    end
                    if (phase == 1) begin
                        wr_en <= 0;
                        phase <= 2;
                    end
                    if (phase == 2) begin
                        lb <= 17'h21;
                        mb <= 32'h0E000000;
                        wr_en <= 4'hf;
                        phase <= 3;
                    end
                    if (phase == 3) begin
                        wr_en <= 0;
                        phase <= 0;
                    end
                end
                if (iop_func == FNC_TIO) begin
                end
            end
        end
    end
endmodule