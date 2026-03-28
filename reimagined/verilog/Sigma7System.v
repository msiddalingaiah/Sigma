// SDS/Xerox Sigma 7 System — simplified for CPU debugging (no IOP)
module Sigma7System (
    input wire clock,
    input wire reset
);

wire [15:33] bus_addr;
wire [0:31]  bus_data_r;
wire [0:31]  bus_data_w;
wire         bus_write;
wire [0:1]   bus_size;
wire         cpu_grant;
wire         cpu_release;
wire         cpu_write;

// CPU always has grant for now
assign cpu_grant = 1'b1;
assign bus_write = cpu_write;

Sigma7CPU cpu (
    .clock       (clock),
    .reset       (reset),
    .cpu_grant   (cpu_grant),
    .cpu_release (cpu_release),
    .bus_addr    (bus_addr),
    .bus_data_r  (bus_data_r),
    .bus_data_w  (bus_data_w),
    .cpu_write   (cpu_write),
    .bus_size    (bus_size)
);

Memory #(
    .SIZE (524288)
) memory (
    .clock      (clock),
    .mem_addr   (bus_addr),
    .mem_data_r (bus_data_r),
    .mem_data_w (bus_data_w),
    .mem_write  (bus_write),
    .mem_size   (bus_size)
);

endmodule