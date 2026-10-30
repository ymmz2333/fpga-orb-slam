`timescale 1ns/1ps

module orb_hamming_native_batch;
    localparam integer FRAME_COUNT = 14;
    localparam integer FRAME_STRIDE = 512;
    localparam integer PAIR_COUNT = 182;
    localparam integer RESULT_COUNT = PAIR_COUNT * FRAME_STRIDE;

    reg clk = 1'b0;
    reg rst = 1'b1;
    always #5 clk = ~clk;

    reg [255:0] descriptor_mem [0:FRAME_COUNT*FRAME_STRIDE-1];
    reg [15:0] descriptor_counts [0:FRAME_COUNT-1];
    reg [7:0] pair_mem [0:PAIR_COUNT-1];
    reg [63:0] result_mem [0:RESULT_COUNT-1];

    reg [255:0] q_desc = 0;
    reg q_valid = 0;
    wire q_ready;
    reg [255:0] s_desc = 0;
    reg [15:0] s_index = 0;
    reg s_last = 0;
    reg s_valid = 0;
    wire s_ready;
    wire [15:0] m_best_index;
    wire [8:0] m_best_distance;
    wire [15:0] m_second_index;
    wire [8:0] m_second_distance;
    wire m_match_valid;
    reg m_match_ready = 0;

    orb_hamming_matcher dut (
        .clk(clk), .rst(rst),
        .q_desc(q_desc), .q_valid(q_valid), .q_ready(q_ready),
        .s_desc(s_desc), .s_index(s_index), .s_last(s_last),
        .s_valid(s_valid), .s_ready(s_ready),
        .m_best_index(m_best_index), .m_best_distance(m_best_distance),
        .m_second_index(m_second_index), .m_second_distance(m_second_distance),
        .m_match_valid(m_match_valid), .m_match_ready(m_match_ready)
    );

    integer pair_index;
    integer query_index;
    integer candidate_index;
    integer source_frame;
    integer target_frame;
    integer initialize_index;
    initial begin
        $readmemh("panorama/build/native_hamming/descriptors.hex", descriptor_mem);
        $readmemh("panorama/build/native_hamming/counts.hex", descriptor_counts);
        $readmemh("panorama/build/native_hamming/pairs.hex", pair_mem);
        for (initialize_index = 0; initialize_index < RESULT_COUNT;
             initialize_index = initialize_index + 1)
            result_mem[initialize_index] = 64'b0;

        repeat (5) @(posedge clk);
        @(negedge clk); rst = 1'b0;
        for (pair_index = 0; pair_index < PAIR_COUNT; pair_index = pair_index + 1) begin
            source_frame = pair_mem[pair_index][7:4];
            target_frame = pair_mem[pair_index][3:0];
            for (query_index = 0; query_index < descriptor_counts[source_frame];
                 query_index = query_index + 1) begin
                while (!q_ready) @(negedge clk);
                q_desc = descriptor_mem[source_frame*FRAME_STRIDE + query_index];
                q_valid = 1'b1;
                @(posedge clk); @(negedge clk); q_valid = 1'b0;

                for (candidate_index = 0;
                     candidate_index < descriptor_counts[target_frame];
                     candidate_index = candidate_index + 1) begin
                    while (!s_ready) @(negedge clk);
                    s_desc = descriptor_mem[target_frame*FRAME_STRIDE + candidate_index];
                    s_index = candidate_index;
                    s_last = (candidate_index + 1 == descriptor_counts[target_frame]);
                    s_valid = 1'b1;
                    @(posedge clk); @(negedge clk);
                end
                s_valid = 1'b0; s_last = 1'b0;
                while (!m_match_valid) @(negedge clk);
                result_mem[pair_index*FRAME_STRIDE + query_index] = {
                    14'b0, m_second_distance, m_second_index,
                    m_best_distance, m_best_index
                };
                m_match_ready = 1'b1;
                @(posedge clk); @(negedge clk); m_match_ready = 1'b0;
            end
            $display("NATIVE_HAMMING_PAIR pair=%0d source=%0d target=%0d queries=%0d candidates=%0d",
                     pair_index, source_frame + 1, target_frame + 1,
                     descriptor_counts[source_frame], descriptor_counts[target_frame]);
        end
        $writememh("panorama/build/native_hamming/results.hex", result_mem);
        $display("NATIVE_HAMMING_BATCH_COMPLETE");
        $finish;
    end
endmodule
