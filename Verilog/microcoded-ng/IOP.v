
/*
Memory is word addressed, 17 bits

X'001' IOP 0, device controller 1, keyboard/printer
X'002' IOP 0, device controller 2, line printer
X'003' IOP 0, device controller 3, card reader
X'004' IOP 0, device controller 4, card punch
X'005' IOP 0, device controller 5, paper tape reader/punch 

*/

module ConsoleIOP(input wire reset, input wire clock, input wire active, output wire [15:31] memory_address,
    input wire [0:31] memory_data_in, output [0:31] memory_data_out, output [0:3] wr_enables,
    input wire [0:2] iop_func, input wire [21:31] iop_device, output [0:1] iop_cc);

    // memory address lines
    reg [15:31] lb;
    // memory output data
    reg [0:31] mb;
    // memory write enables
    reg [0:3] wr_en;
    // Condition codes
    reg [0:1] cc;

    assign memory_address = active ? lb : 17'bZ;
    assign memory_data_out = active ? mb : 32'bZ;
    assign wr_enables = active ? wr_en : 4'bZ;
    assign iop_cc = active ? cc : 2'bZ;

    reg [0:3] phase;
    reg [0:2] iop;
    reg [0:7] device;
    reg [15:33] p;
    reg [0:31] a;
    reg [0:7] count;

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
                wr_en <= 0;
                if (phase == 0) begin
                    $display("IOP %x, Device %x: Console", iop, device);
                    lb <= 17'h20;
                    phase <= 1;
                end
                if (phase == 1) begin
                    lb <= { memory_data_in[16:31], 1'h1 };
                    phase <= 2;
                end
                if (phase == 2) begin
                    p[15:33] = memory_data_in[13:31];
                    lb <= memory_data_in[16:31];
                    phase <= 3;
                end
                // TODO: stopped here
                if (phase == 3) begin
                end
                if (phase == 4) begin
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
        end
    end
endmodule

module PapertapeIOP(input wire reset, input wire clock, input wire active, output wire [15:31] memory_address,
    input wire [0:31] memory_data_in, output [0:31] memory_data_out, output [0:3] wr_enables,
    input wire [0:2] iop_func, input wire [21:31] iop_device, output reg [0:1] iop_cc);

    localparam MAX_WORD_LEN = 1024;

    // memory address lines
    reg [15:31] lb;
    // memory output data
    reg [0:31] mb;
    // memory write enables
    reg [0:3] wr_en;
    reg [0:31] tape[0:MAX_WORD_LEN-1];

    assign memory_address = active ? lb : 17'bZ;
    assign memory_data_out = active ? mb : 32'bZ;
    assign wr_enables = active ? wr_en : 4'bZ;

    reg [0:3] phase;
    reg [0:2] iop;
    reg [0:7] device;

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
                wr_en <= 0;
                if (phase == 0) begin
                    $display("IOP %x, Device %x: Papertape", iop, device);
                    lb <= 17'h29;
                    phase <= 1;
                end
                if (phase == 1) begin
                    mb <= tape[lb+1];
                    wr_en <= 4'hf;
                    if (lb == 17'h70) phase <= 2;
                    lb <= lb + 1;
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
        end
    end
endmodule

module IOP(input wire reset, input wire clock, input wire active, output wire [15:31] memory_address,
    input wire [0:31] memory_data_in, output [0:31] memory_data_out, output [0:3] wr_enables,
    input wire [0:2] iop_func, input wire [21:31] iop_device, output [0:1] iop_cc);

    // memory address lines
    wire [15:31] lb;
    // memory output data
    wire [0:31] mb;
    // memory write enables
    wire [0:3] wr_en;

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

    reg console_active;
    reg papertape_active;

    ConsoleIOP console(reset, clock, console_active, lb, memory_data_in, mb, wr_en,
        iop_func, iop_device, iop_cc);
    PapertapeIOP papertape(reset, clock, papertape_active, lb, memory_data_in, mb, wr_en,
        iop_func, iop_device, iop_cc);

    // Guideline #3: When modeling combinational logic with an "always" block, use blocking assignments ( = ).
    // Order matters here!!!
    always @(*) begin
        iop = iop_device[21:23];
        device = iop_device[24:31];
        console_active = 0;
        papertape_active = 0;
        case (device)
            1: console_active = active;
            5: papertape_active = active;
        endcase
    end

    // Guideline #1: When modeling sequential logic, use nonblocking assignments ( <= ).
    always @(posedge clock, posedge reset) begin
        if (reset == 1) begin
            phase <= 0;
        end else begin
            if (active) begin
                if (iop_func == FNC_SIO) begin
                end
                if (iop_func == FNC_TIO) begin
                end
            end
        end
    end
endmodule