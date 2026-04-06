// SDS/Xerox Sigma 7 Console I/O
// Device 0x1001: data register (RD reads char, WD writes char)
// Device 0x1002: status register (bit 31=RX ready, bit 30=TX ready)
// Simulation only — uses $fgetc/$fputc for stdin/stdout

module Console (
    input  wire        clock,
    input  wire        reset,
    input  wire        io_select,
    input  wire [15:33] io_addr,
    input  wire [0:31] io_data_w,
    input  wire        io_write,
    output reg  [0:31] io_data_r
);

localparam ADDR_DATA   = 17'h1001;
localparam ADDR_STATUS = 17'h1002;

reg        rx_ready;
reg [7:0]  rx_data;
reg        rx_read;   // strobed when CPU reads data register

// ---------------------------------------------------------------------------
// Receive: blocking $fgetc in separate thread
// Only active when CONSOLE_INPUT is defined (e.g. for interactive use)
// ---------------------------------------------------------------------------
`ifdef CONSOLE_INPUT
initial begin
    rx_ready = 1'b0;
    rx_data  = 8'h00;
    forever begin
        rx_data  = $fgetc('h8000_0000);
        if ($feof('h8000_0000)) begin
            rx_data  = 8'h00;
            rx_ready = 1'b0;
            #1000000;
        end else begin
            rx_ready = 1'b1;
            @(posedge rx_read);
            rx_ready = 1'b0;
        end
    end
end
`else
initial begin
    rx_ready = 1'b0;
    rx_data  = 8'h00;
end
`endif

// ---------------------------------------------------------------------------
// Read data: combinatorial decode of device address
// ---------------------------------------------------------------------------
always @(*) begin
    io_data_r = 32'b0;
    if (io_select) begin
        case (io_addr[15:31])
            ADDR_DATA:   io_data_r = {24'b0, rx_data};        // char in bits 24:31
            ADDR_STATUS: io_data_r = {29'b0, 1'b1, rx_ready}; // TX always ready
            default:     io_data_r = 32'b0;
        endcase
    end
end

// ---------------------------------------------------------------------------
// rx_read strobe: fires one cycle when CPU reads data register
// ---------------------------------------------------------------------------
always @(posedge clock) begin
    rx_read <= io_select & ~io_write & (io_addr[15:31] == ADDR_DATA) & rx_ready;
end

// ---------------------------------------------------------------------------
// Write: $fputc when CPU writes to data register
// Also write to capture file for test verification
// ---------------------------------------------------------------------------
integer stdout_fd;
integer capture_fd;

initial begin
    stdout_fd  = 'h8000_0001;  // stdout
    capture_fd = $fopen("console_output.txt", "w");
end

always @(posedge clock) begin
    if (io_select & io_write & (io_addr[15:31] == ADDR_DATA)) begin
        $fwrite(stdout_fd,  "%c", io_data_w[24:31]);
        $fwrite(capture_fd, "%c", io_data_w[24:31]);
        $fflush(capture_fd);
    end
end

endmodule