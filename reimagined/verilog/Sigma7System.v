// SDS/Xerox Sigma 7 System
module Sigma7System (
    input wire clock,
    input wire reset
);

wire [15:33] bus_addr;
wire [0:31]  bus_data_r;
wire [0:31]  bus_data_w;
wire [0:31]  mem_data_r;
wire [0:31]  io_data_r;
wire         bus_write;
wire [0:1]   bus_size;
wire         cpu_grant;
wire         cpu_release;
wire         cpu_write;
wire         io_select;

// Console RX — driven by top-level (Python cocotb or $fgetc thread)
reg          rx_ready;
reg  [7:0]   rx_data;
wire         rx_read;
wire         tx_valid;
wire [7:0]   tx_char;

initial begin
    rx_ready = 1'b0;
    rx_data  = 8'h00;
end

// CPU always has grant
assign cpu_grant = 1'b1;
assign bus_write = cpu_write;

// Route read data
assign bus_data_r = io_select ? io_data_r : mem_data_r;

Sigma7CPU cpu (
    .clock       (clock),
    .reset       (reset),
    .cpu_grant   (cpu_grant),
    .cpu_release (cpu_release),
    .bus_addr    (bus_addr),
    .bus_data_r  (bus_data_r),
    .bus_data_w  (bus_data_w),
    .cpu_write   (cpu_write),
    .bus_size    (bus_size),
    .io_select   (io_select)
);

Memory #(
    .SIZE (524288)
) memory (
    .clock      (clock),
    .mem_addr   (bus_addr),
    .mem_data_r (mem_data_r),
    .mem_data_w (bus_data_w),
    .mem_write  (bus_write & ~io_select),
    .mem_size   (bus_size)
);

Console console (
    .clock      (clock),
    .reset      (reset),
    .io_select  (io_select),
    .io_addr    (bus_addr),
    .io_data_w  (bus_data_w),
    .io_write   (bus_write),
    .io_data_r  (io_data_r),
    .rx_ready   (rx_ready),
    .rx_data    (rx_data),
    .rx_read    (rx_read),
    .tx_valid   (tx_valid),
    .tx_char    (tx_char)
);

// Optional $fgetc thread for standalone simulation
`ifdef CONSOLE_INPUT
initial begin : console_input_thread
    integer c;
    forever begin
        c = $fgetc('h8000_0000);
        if ($feof('h8000_0000)) begin
            #1000000;
        end else begin
            rx_data  = c[7:0];
            rx_ready = 1'b1;
            @(posedge rx_read);
            rx_ready = 1'b0;
        end
    end
end

// $fwrite output for standalone simulation
always @(posedge clock) begin
    if (tx_valid)
        $fwrite('h8000_0001, "%c", tx_char);
end
`endif

endmodule