// SDS/Xerox Sigma 7 Memory
// Synchronous memory with byte/halfword/word read and write support
// Big-endian: bit 0 is MSB throughout
// Address space: 512KB (19-bit byte address, bits 15-33)
// Read data alignment:
//   Word:     full 32 bits in bits 0:31
//   Halfword: always in bits 16:31, bits 0:15 = 0
//   Byte:     always in bits 24:31, bits 0:23 = 0

module Memory #(
    parameter SIZE = 524288   // 512KB default
)(
    input  wire        clock,
    input  wire [15:33] mem_addr,
    output reg  [0:31] mem_data_r,
    input  wire [0:31] mem_data_w,
    input  wire        mem_write,
    input  wire [0:1]  mem_size    // 00=byte, 01=halfword, 10=word
);

localparam SIZE_BYTE     = 2'b00;
localparam SIZE_HALFWORD = 2'b01;
localparam SIZE_WORD     = 2'b10;

// Memory array — byte addressable, indexed by full 19-bit byte address
reg [0:7] mem [0:524287];

// Synchronous read — data valid next cycle
// Word:     full 32-bit word, word-aligned
// Halfword: always presented in bits 16:31, zero in bits 0:15
// Byte:     always presented in bits 24:31, zero in bits 0:23
always @(posedge clock) begin
    case (mem_size)
        SIZE_WORD: begin
            mem_data_r[0:7]   <= mem[{mem_addr[15:31], 2'b00}];
            mem_data_r[8:15]  <= mem[{mem_addr[15:31], 2'b01}];
            mem_data_r[16:23] <= mem[{mem_addr[15:31], 2'b10}];
            mem_data_r[24:31] <= mem[{mem_addr[15:31], 2'b11}];
        end
        SIZE_HALFWORD: begin
            // Present halfword in bits 16:31 regardless of which halfword
            // P[32] selects: 0 = high halfword (bytes 0-1), 1 = low halfword (bytes 2-3)
            mem_data_r[0:15]  <= 16'b0;
            mem_data_r[16:23] <= mem_addr[32] ?
                                  mem[{mem_addr[15:31], 2'b10}] :
                                  mem[{mem_addr[15:31], 2'b00}];
            mem_data_r[24:31] <= mem_addr[32] ?
                                  mem[{mem_addr[15:31], 2'b11}] :
                                  mem[{mem_addr[15:31], 2'b01}];
        end
        SIZE_BYTE: begin
            // Present byte in bits 24:31 regardless of which byte
            // P[32:33] selects which byte: 00=byte0, 01=byte1, 10=byte2, 11=byte3
            mem_data_r[0:23]  <= 24'b0;
            mem_data_r[24:31] <= mem[{mem_addr[15:31], mem_addr[32:33]}];
        end
        default: mem_data_r <= 32'b0;
    endcase
end

// Synchronous write — byte/halfword/word masked
// Big-endian byte ordering: byte 0 is most significant
// Write data alignment mirrors read:
//   Word:     data in bits 0:31
//   Halfword: data in bits 16:31, written to halfword selected by mem_addr[32]
//   Byte:     data in bits 24:31, written to byte selected by mem_addr[32:33]
always @(posedge clock) begin
    if (mem_write) begin
        case (mem_size)
            SIZE_WORD: begin
                mem[{mem_addr[15:31], 2'b00}] <= mem_data_w[0:7];
                mem[{mem_addr[15:31], 2'b01}] <= mem_data_w[8:15];
                mem[{mem_addr[15:31], 2'b10}] <= mem_data_w[16:23];
                mem[{mem_addr[15:31], 2'b11}] <= mem_data_w[24:31];
            end
            SIZE_HALFWORD: begin
                // Write halfword from bits 16:31 to selected halfword position
                mem[{mem_addr[15:31], mem_addr[32], 1'b0}] <= mem_data_w[16:23];
                mem[{mem_addr[15:31], mem_addr[32], 1'b1}] <= mem_data_w[24:31];
            end
            SIZE_BYTE: begin
                // Write byte from bits 24:31 to selected byte position
                mem[{mem_addr[15:31], mem_addr[32:33]}] <= mem_data_w[24:31];
            end
            default: ;
        endcase
    end
end

endmodule