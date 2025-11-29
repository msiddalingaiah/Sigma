
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
    reg [0:7] a, count;

    // Guideline #3: When modeling combinational logic with an "always" block, use blocking assignments ( = ).
    // Order matters here!!!
    always @(*) begin
        iop = iop_device[21:23];
        device = iop_device[24:31];
        wr_en = 0;
        lb = p[15:31];
        mb = 0;
        case (phase)
            10: begin lb = 17'h21; mb = 32'h0E000000; wr_en = 4'hf; end
        endcase
        a = 8'h20;
        case (p[32:33])
            0: a = memory_data_in[0:7];
            1: a = memory_data_in[8:15];
            2: a = memory_data_in[16:23];
            3: a = memory_data_in[24:31];
        endcase
    end

    // Guideline #1: When modeling sequential logic, use nonblocking assignments ( <= ).
    always @(posedge clock, posedge reset) begin
        if (reset == 1) begin
            p <= 0;
            phase <= 0;
            count <= 0;
        end else begin
            if (active) begin
                phase <= phase + 1;
                case (phase)
                    0: begin
                        // $display("IOP %x, Device %x: Console", iop, device);
                        // Load pointer to command double word address
                        p <= { 17'h20, 2'h0 };
                    end
                    1: begin
                        // Load command double word address
                        p <= { memory_data_in[16:31], 3'h0 };
                    end
                    2: begin
                        // Load memory byte address
                        p <= memory_data_in[13:31];
                    end
                    4: begin
                        // TEXTC string, first byte contains count
                        count <= a;
                        p <= p + 1;
                    end
                    5: begin
                        $write("%c", a);
                        p <= p + 1;
                        count <= count - 1;
                    end
                    6: begin
                        if (count != 0) phase <= phase-1;
                    end
                endcase
            end else begin
                phase <= 0;
                count <= 0;
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
    reg [15:31] p;

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
        wr_en = 0;
        lb = p;
        mb = tape[lb];
        case (phase)
            0: ;
            1: begin wr_en = 4'hf; end
            2: begin lb = 17'h21; mb = 32'h0E000000; wr_en = 4'hf; end
        endcase
    end

    // Guideline #1: When modeling sequential logic, use nonblocking assignments ( <= ).
    always @(posedge clock, posedge reset) begin
        if (reset == 1) begin
            phase <= 0;
            p <= 17'h2a;
        end else begin
            if (active) begin
                phase <= phase + 1;
                case (phase)
                    0: begin
                        $display("IOP %x, Device %x: Papertape", iop, device);
                    end
                    1: begin
                        if (p != 17'h90) phase <= phase;
                        p <= p + 1;
                    end
                    2: begin
                        phase <= phase;
                    end
                endcase
                // if (wr_en) $display("PH%d: addr: %x, data: %x, p: %x", phase, lb, mb, p);
            end else begin
                phase <= 0;
                p <= 17'h2a;
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