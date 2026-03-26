// SDS/Xerox Sigma 7 I/O Processor
// Minimal model for bus sharing validation.
// When granted the bus, performs simple sequential read/write cycles.
// Big-endian: bit 0 is MSB throughout

module IOProcessor (
    input  wire        clock,
    input  wire        reset,
    // Bus interface
    input  wire        iop_grant,       // arbiter grants bus to IOP
    output wire [15:33] bus_addr,       // memory address
    input  wire [0:31] bus_data_r,      // read data from memory
    output wire [0:31] bus_data_w,      // write data to memory
    output wire        iop_write,       // IOP write strobe
    output wire [0:1]  bus_size         // 00=byte, 01=halfword, 10=word
);

// ---------------------------------------------------------------------------
// IOP state machine — simple read then write cycle
// ---------------------------------------------------------------------------
localparam IOP_IDLE      = 2'b00;
localparam IOP_READ      = 2'b01;
localparam IOP_WRITE     = 2'b10;

reg [0:1]  iop_state;
reg [15:33] iop_addr;
reg [0:31]  iop_data;
reg         iop_write_r;

// IOP performs a read from address 0x100, then writes result to 0x200
localparam IOP_READ_ADDR  = 19'h00100;
localparam IOP_WRITE_ADDR = 19'h00200;

always @(posedge clock) begin
    if (reset) begin
        iop_state   <= IOP_IDLE;
        iop_addr    <= 19'b0;
        iop_data    <= 32'b0;
        iop_write_r <= 1'b0;
    end else begin
        iop_write_r <= 1'b0;   // default no write

        case (iop_state)
            IOP_IDLE: begin
                if (iop_grant) begin
                    // Start read cycle
                    iop_addr  <= IOP_READ_ADDR;
                    iop_state <= IOP_READ;
                end
            end

            IOP_READ: begin
                if (iop_grant) begin
                    // Capture read data (valid this cycle from previous address)
                    iop_data  <= bus_data_r;
                    // Set up write address
                    iop_addr  <= IOP_WRITE_ADDR;
                    iop_state <= IOP_WRITE;
                end else begin
                    iop_state <= IOP_IDLE;
                end
            end

            IOP_WRITE: begin
                if (iop_grant) begin
                    iop_write_r <= 1'b1;
                    iop_state   <= IOP_IDLE;
                end else begin
                    iop_state <= IOP_IDLE;
                end
            end

            default: iop_state <= IOP_IDLE;
        endcase
    end
end

// ---------------------------------------------------------------------------
// Bus tri-state — IOP drives bus only when granted
// ---------------------------------------------------------------------------
assign bus_addr   = iop_grant ? iop_addr  : 19'bz;
assign bus_data_w = iop_grant ? iop_data  : 32'bz;
assign iop_write  = iop_grant ? iop_write_r : 1'bz;
assign bus_size   = iop_grant ? 2'b10     : 2'bz;  // always word access

endmodule