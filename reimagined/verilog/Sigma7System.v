// SDS/Xerox Sigma 7 System
// Top-level module wiring CPU, IOP, BusArbiter and Memory together
// Big-endian: bit 0 is MSB throughout

module Sigma7System (
    input wire clock,
    input wire reset
);

// ---------------------------------------------------------------------------
// Shared bus signals
// ---------------------------------------------------------------------------
wire [15:33] bus_addr;      // shared address (tri-state)
wire [0:31]  bus_data_r;    // memory read data (driven by Memory)
wire [0:31]  bus_data_w;    // shared write data (tri-state)
wire         bus_write;     // OR of cpu_write and iop_write
wire [0:1]   bus_size;      // shared size (tri-state)

// ---------------------------------------------------------------------------
// Arbiter signals
// ---------------------------------------------------------------------------
wire cpu_grant;
wire cpu_release;
wire iop_grant;

// ---------------------------------------------------------------------------
// Individual write strobes (ORed for bus_write)
// ---------------------------------------------------------------------------
wire cpu_write;
wire iop_write;
assign bus_write = cpu_write | iop_write;

// ---------------------------------------------------------------------------
// Module instantiations
// ---------------------------------------------------------------------------

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

IOProcessor iop (
    .clock      (clock),
    .reset      (reset),
    .iop_grant  (iop_grant),
    .bus_addr   (bus_addr),
    .bus_data_r (bus_data_r),
    .bus_data_w (bus_data_w),
    .iop_write  (iop_write),
    .bus_size   (bus_size)
);

BusArbiter #(
    .RELEASE_CYCLES (16)
) arbiter (
    .clock       (clock),
    .reset       (reset),
    .cpu_release (cpu_release),
    .cpu_grant   (cpu_grant),
    .iop_grant   (iop_grant)
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