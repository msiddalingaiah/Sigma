// Sigma 7 Verilog testbench wrapper for cocotb
// Instantiates Sigma7System and provides clock and reset ports

`timescale 1ns/1ps

module Sigma7TB;

reg clock;
reg reset;

// Generate clock — 10ns period (100MHz)
initial clock = 0;
always #5 clock = ~clock;

Sigma7System sys (
    .clock (clock),
    .reset (reset)
);

// Dump waveforms
initial begin
    $dumpfile({`PROJ_DIR, "/vcd/sigma.vcd"});
    $dumpvars(0, Sigma7TB);
end

endmodule