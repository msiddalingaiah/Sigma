
/**
 * This module implements the Sigma microcode ROM.
 * Microcode is loaded from a text file, which is synthesizable.
 */
module CodeROM(input wire [11:0] address, output wire [39:0] data);
    reg [39:0] memory[0:4095];
    initial begin
        $readmemh("roms/microcode.txt", memory);
    end

    assign data = memory[address];
endmodule
