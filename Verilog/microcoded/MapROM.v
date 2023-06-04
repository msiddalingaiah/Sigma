
/**
 * This module implements the Sigma opcode mapping ROM.
 * Mapping code is loaded from a text file, which is synthesizable.
 */
module MapROM(input wire [6:0] address, output wire [11:0] data_out);
    reg [11:0] memory[0:127];
    initial begin
        $readmemh("roms/instruction_map.txt", memory);
    end

    assign data_out = memory[address];
endmodule