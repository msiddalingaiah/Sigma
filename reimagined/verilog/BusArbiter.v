// SDS/Xerox Sigma 7 Bus Arbiter
// CPU has priority. When CPU releases bus, IOP gets it for RELEASE_CYCLES cycles.
// Big-endian: bit 0 is MSB throughout

module BusArbiter #(
    parameter RELEASE_CYCLES = 16   // number of cycles IOP holds bus when released
)(
    input  wire clock,
    input  wire reset,
    // CPU side
    input  wire cpu_release,    // CPU requests bus release to IOP
    output reg  cpu_grant,      // CPU has bus
    // IOP side
    output reg  iop_grant       // IOP has bus
);

// Release cycle counter
reg [0:4] release_count;   // 5 bits to count up to 16

always @(posedge clock) begin
    if (reset) begin
        cpu_grant      <= 1'b1;
        iop_grant      <= 1'b0;
        release_count  <= 5'b0;
    end else begin
        if (cpu_grant && cpu_release) begin
            // CPU releases bus to IOP
            cpu_grant     <= 1'b0;
            iop_grant     <= 1'b1;
            release_count <= RELEASE_CYCLES - 1;
        end else if (iop_grant) begin
            if (release_count == 5'b0) begin
                // IOP release period expired — return bus to CPU
                iop_grant <= 1'b0;
                cpu_grant <= 1'b1;
            end else begin
                release_count <= release_count - 1;
            end
        end
    end
end

endmodule