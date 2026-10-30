`timescale 1ns/1ps

// ORB descriptor matcher core.
//
// One 256-bit query descriptor is loaded, followed by a stream of candidate
// descriptors.  The core evaluates one candidate per clock after the pipeline
// fills and returns the smallest and second-smallest Hamming distances.
//
// This is deliberately a compute core, not a complete database controller:
// AXI DMA/DDR logic can later provide the candidate stream without changing
// the matching pipeline.
module orb_hamming_matcher #(
    parameter integer DESCRIPTOR_BITS = 256,
    parameter integer INDEX_WIDTH = 16,
    // Used only by the fault-injection wrapper in rtl/mutants.
    parameter IGNORE_MSB = 1'b0
) (
    input  wire                         clk,
    input  wire                         rst,

    input  wire [DESCRIPTOR_BITS-1:0]   q_desc,
    input  wire                         q_valid,
    output wire                         q_ready,

    input  wire [DESCRIPTOR_BITS-1:0]   s_desc,
    input  wire [INDEX_WIDTH-1:0]       s_index,
    input  wire                         s_last,
    input  wire                         s_valid,
    output wire                         s_ready,

    output reg  [INDEX_WIDTH-1:0]       m_best_index,
    output reg  [8:0]                   m_best_distance,
    output reg  [INDEX_WIDTH-1:0]       m_second_index,
    output reg  [8:0]                   m_second_distance,
    output reg                          m_match_valid,
    input  wire                         m_match_ready
);

    localparam [1:0] IDLE = 2'd0;
    localparam [1:0] SCAN = 2'd1;
    localparam [1:0] RESULT = 2'd2;

    reg [1:0] state;
    reg [DESCRIPTOR_BITS-1:0] query_reg;
    reg input_done;

    reg [8:0] best_distance;
    reg [8:0] second_distance;
    reg [INDEX_WIDTH-1:0] best_index;
    reg [INDEX_WIDTH-1:0] second_index;

    wire input_fire = s_valid && s_ready;
    wire [DESCRIPTOR_BITS-1:0] xor_raw = s_desc ^ query_reg;
    wire [DESCRIPTOR_BITS-1:0] xor_bits =
        (IGNORE_MSB == 1'b1)
            ? (xor_raw & {1'b0, {(DESCRIPTOR_BITS-1){1'b1}}})
            : xor_raw;

    assign q_ready = (state == IDLE) && !m_match_valid;
    assign s_ready = (state == SCAN) && !input_done;

    function [3:0] popcount8;
        input [7:0] value;
        integer bit_index;
        begin
            popcount8 = 4'd0;
            for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1)
                popcount8 = popcount8 + value[bit_index];
        end
    endfunction

    // A registered XOR plus a balanced four-stage adder tree limits the
    // combinational depth.  The arrays describe 32 byte counts -> 8 groups ->
    // 2 groups -> one result.
    reg [DESCRIPTOR_BITS-1:0] stage0_xor;
    reg [3:0] stage1_count [0:31];
    reg [5:0] stage2_count [0:7];
    reg [7:0] stage3_count [0:1];
    reg [8:0] stage4_distance;

    reg stage0_valid, stage1_valid, stage2_valid, stage3_valid, stage4_valid;
    reg stage0_last;
    reg stage1_last, stage2_last, stage3_last, stage4_last;
    reg [INDEX_WIDTH-1:0] stage1_index;
    reg [INDEX_WIDTH-1:0] stage0_index;
    reg [INDEX_WIDTH-1:0] stage2_index;
    reg [INDEX_WIDTH-1:0] stage3_index;
    reg [INDEX_WIDTH-1:0] stage4_index;

    // Datapath registers intentionally have no reset.  Their values are
    // ignored whenever the matching valid bit is low.  This avoids turning a
    // single reset net into a high-fanout enable for hundreds of flip-flops.
    integer i;
    always @(posedge clk) begin
        if (q_valid && q_ready)
            query_reg <= q_desc;

        if (input_fire) begin
            stage0_xor <= xor_bits;
            stage0_index <= s_index;
            stage0_last <= s_last;
        end

        if (stage0_valid) begin
            for (i = 0; i < 32; i = i + 1)
                stage1_count[i] <= popcount8(stage0_xor[i*8 +: 8]);
            stage1_index <= stage0_index;
            stage1_last <= stage0_last;
        end

        if (stage1_valid) begin
            for (i = 0; i < 8; i = i + 1)
                stage2_count[i] <= {2'b0, stage1_count[i*4]}
                                 + {2'b0, stage1_count[i*4+1]}
                                 + {2'b0, stage1_count[i*4+2]}
                                 + {2'b0, stage1_count[i*4+3]};
            stage2_index <= stage1_index;
            stage2_last <= stage1_last;
        end

        if (stage2_valid) begin
            stage3_count[0] <= {2'b0, stage2_count[0]}
                             + {2'b0, stage2_count[1]}
                             + {2'b0, stage2_count[2]}
                             + {2'b0, stage2_count[3]};
            stage3_count[1] <= {2'b0, stage2_count[4]}
                             + {2'b0, stage2_count[5]}
                             + {2'b0, stage2_count[6]}
                             + {2'b0, stage2_count[7]};
            stage3_index <= stage2_index;
            stage3_last <= stage2_last;
        end

        if (stage3_valid) begin
            stage4_distance <= {1'b0, stage3_count[0]}
                             + {1'b0, stage3_count[1]};
            stage4_index <= stage3_index;
            stage4_last <= stage3_last;
        end
    end

    // Only control/valid state is reset.  Output data is meaningful only while
    // m_match_valid is asserted, so resetting wide output buses is unnecessary.
    always @(posedge clk) begin
        if (rst) begin
            state <= IDLE;
            input_done <= 1'b0;
            m_match_valid <= 1'b0;
            stage0_valid <= 1'b0;
            stage1_valid <= 1'b0;
            stage2_valid <= 1'b0;
            stage3_valid <= 1'b0;
            stage4_valid <= 1'b0;
        end else begin
            // Pipeline the validity marker alongside the datapath registers.
            stage0_valid <= input_fire;
            stage1_valid <= stage0_valid;
            stage2_valid <= stage1_valid;
            stage3_valid <= stage2_valid;
            stage4_valid <= stage3_valid;

            case (state)
                IDLE: begin
                    m_match_valid <= 1'b0;
                    input_done <= 1'b0;
                    if (q_valid && q_ready) begin
                        best_distance <= 9'h1ff;
                        second_distance <= 9'h1ff;
                        best_index <= {INDEX_WIDTH{1'b0}};
                        second_index <= {INDEX_WIDTH{1'b0}};
                        state <= SCAN;
                    end
                end

                SCAN: begin
                    if (input_fire && s_last)
                        input_done <= 1'b1;

                    if (stage4_valid) begin
                        if (stage4_distance < best_distance) begin
                            best_distance <= stage4_distance;
                            best_index <= stage4_index;
                            second_distance <= best_distance;
                            second_index <= best_index;
                        end else if (stage4_distance < second_distance) begin
                            second_distance <= stage4_distance;
                            second_index <= stage4_index;
                        end

                        if (stage4_last) begin
                            // Include the final candidate in the returned result;
                            // nonblocking state updates above are not visible yet.
                            if (stage4_distance < best_distance) begin
                                m_best_distance <= stage4_distance;
                                m_best_index <= stage4_index;
                                m_second_distance <= best_distance;
                                m_second_index <= best_index;
                            end else if (stage4_distance < second_distance) begin
                                m_best_distance <= best_distance;
                                m_best_index <= best_index;
                                m_second_distance <= stage4_distance;
                                m_second_index <= stage4_index;
                            end else begin
                                m_best_distance <= best_distance;
                                m_best_index <= best_index;
                                m_second_distance <= second_distance;
                                m_second_index <= second_index;
                            end
                            m_match_valid <= 1'b1;
                            state <= RESULT;
                        end
                    end
                end

                RESULT: begin
                    if (m_match_valid && m_match_ready) begin
                        m_match_valid <= 1'b0;
                        state <= IDLE;
                    end
                end

                default: state <= IDLE;
            endcase
        end
    end

endmodule
