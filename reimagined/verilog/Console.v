// SDS/Xerox Sigma 7 Console I/O
// Device 0x1001: data register (RD reads char, WD writes char)
// Device 0x1002: status register (bit 31=RX ready, bit 30=TX ready)
//
// RX: rx_data and rx_ready driven externally (by Python cocotb or $fgetc)
// TX: tx_valid pulses for one cycle when CPU writes a character; tx_char = char

module Console (
    input  wire        clock,
    input  wire        reset,
    input  wire        io_select,
    input  wire [15:33] io_addr,
    input  wire [0:31] io_data_w,
    input  wire        io_write,
    output reg  [0:31] io_data_r,
    // RX interface — driven by Python or $fgetc thread
    input  wire        rx_ready,
    input  wire [7:0]  rx_data,
    output reg         rx_read,   // strobed one cycle when CPU reads data reg
    // TX interface — monitored by Python or $fwrite
    output reg         tx_valid,  // pulses one cycle when char written
    output reg  [7:0]  tx_char    // character written by CPU
);

localparam ADDR_DATA   = 17'h1001;
localparam ADDR_STATUS = 17'h1002;

// ---------------------------------------------------------------------------
// Read data: combinatorial decode of device address
// ---------------------------------------------------------------------------
always @(*) begin
    io_data_r = 32'b0;
    if (io_select) begin
        case (io_addr[15:31])
            ADDR_DATA:   io_data_r = {24'b0, rx_data};
            ADDR_STATUS: io_data_r = {29'b0, 1'b1, rx_ready}; // TX always ready
            default:     io_data_r = 32'b0;
        endcase
    end
end

// ---------------------------------------------------------------------------
// rx_read strobe: fires one cycle when CPU reads data register
// ---------------------------------------------------------------------------
always @(posedge clock) begin
    if (reset)
        rx_read <= 1'b0;
    else
        rx_read <= io_select & ~io_write &
                   (io_addr[15:31] == ADDR_DATA) & rx_ready;
end

// ---------------------------------------------------------------------------
// TX: capture character written by CPU
// ---------------------------------------------------------------------------
always @(posedge clock) begin
    if (reset) begin
        tx_valid <= 1'b0;
        tx_char  <= 8'h00;
    end else if (io_select & io_write & (io_addr[15:31] == ADDR_DATA)) begin
        tx_valid <= 1'b1;
        tx_char  <= io_data_w[24:31];
    end else begin
        tx_valid <= 1'b0;
        tx_char  <= 8'h00;
    end
end

// ---------------------------------------------------------------------------
// Optional: $fgetc thread for non-Python simulation (Sigma7Sim.v)
// ---------------------------------------------------------------------------
`ifdef CONSOLE_INPUT
// In this mode rx_data/rx_ready are driven by the $fgetc thread below,
// but since they are now inputs to this module, this ifdef is handled
// in the top-level sim module instead.
`endif

endmodule