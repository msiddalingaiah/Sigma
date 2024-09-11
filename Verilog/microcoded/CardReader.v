
module CardReader (input wire reset, input wire clock, output reg running, input wire active, input wire [0:31] memory_data_in,
    output reg [15:31] memory_address, output reg [0:31] memory_data_out, output reg [0:3] wr_enables,
    input wire sio, input wire tio, output reg [0:3] cc);

    localparam NUM_CARDS = 108;
    localparam WORDS_PER_CARD = 30;
    localparam NUM_WORDS = NUM_CARDS*WORDS_PER_CARD;

    reg [0:31] card_words[0:NUM_WORDS-1];
    reg [0:15] card_index;
    reg [0:7] word_count;
    reg [15:31] mem_address;

    always @(*) begin
        memory_data_out = card_words[card_index];
        memory_address = mem_address;
    end

    always @(posedge clock, posedge reset) begin
        if (reset == 1) begin
            card_index <= 0;
            mem_address <= 17'h2a;
        end else begin
            running <= 0;
            if (sio) begin
                word_count <= WORDS_PER_CARD;
                running <= 1;
            end
            cc <= 6; // Device controller or device is busy.
            if (tio & (word_count == 0)) begin
                cc <= 0; // I/O address recognized and acceptable SIO is currently possible.
            end
            if (active) begin
                wr_enables <= 0;
                if (word_count != 0) begin
                    wr_enables <= 4'b1111;
                    card_index <= card_index + 1;
                    word_count <= word_count - 1;
                    mem_address <= mem_address + 1;
                    // $display("Write 0x%x = 0x%x", mem_address, card_words[card_index]);
                end else begin
                    running <= 0;
                end
            end
        end
    end
endmodule
