// SDS/Xerox Sigma 7 — Standalone Interactive Simulation
// Compile with:
//   iverilog -o sim -DMONITOR_HEX='"monitor.hex"' -DCONSOLE_INPUT \
//            Sigma7Sim.v Sigma7System.v Sigma7CPU.v Memory.v Console.v \
//            BusArbiter.v IOProcessor.v
// Run with:
//   vvp sim

`timescale 1ns/1ps

module Sigma7Sim;

reg clock;
reg reset;

// 10ns clock period = 100MHz
initial clock = 0;
always #5 clock = ~clock;

// Reset for 4 cycles then release
initial begin
    reset = 1;
    repeat (4) @(posedge clock);
    reset = 0;
end

// Instantiate system
Sigma7System sys (
    .clock (clock),
    .reset (reset)
);

// Run until $finish — simulation runs indefinitely for interactive use
// Halt detection: LCFI (opcode 0x02) with all-zero fields acts as halt.
// We detect it by watching the phase return to PCP4 after executing LCFI.
// Alternatively just let the user Ctrl-C to stop.
initial begin
    // Optional: dump waveforms
`ifdef VCD
    $dumpfile("sim.vcd");
    $dumpvars(0, Sigma7Sim);
`endif

    // Run indefinitely — Ctrl-C to stop, or $finish from console
    // In non-interactive mode (no CONSOLE_INPUT), finish after timeout
`ifndef CONSOLE_INPUT
    #500000;  // 500us timeout for non-interactive use
    $finish;
`endif
end

endmodule
