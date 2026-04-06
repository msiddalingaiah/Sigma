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

// CPU always has grant for now
assign cpu_grant = 1'b1;
assign bus_write = cpu_write;

// Route read data: I/O or memory depending on io_select
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
    .mem_write  (bus_write & ~io_select),  // suppress memory write during I/O
    .mem_size   (bus_size)
);

Console console (
    .clock      (clock),
    .reset      (reset),
    .io_select  (io_select),
    .io_addr    (bus_addr),
    .io_data_w  (bus_data_w),
    .io_write   (bus_write),
    .io_data_r  (io_data_r)
);

endmodule