`timescale 1ns/1ps

// 3x3 non-maximum suppression for the dense score raster produced by
// orb_fast9_stream.  The FAST input coordinates cover x=3..WIDTH-4 and
// y=3..HEIGHT-4.  This module emits the one-pixel-smaller raster and marks the
// locally selected points with m_keep.
//
// Equal-score plateaus use a deterministic raster-order tie break: the center
// must be strictly greater than the four already-seen neighbours and greater
// than or equal to the four later neighbours.  Thus equal adjacent candidates
// never produce an unstable set of duplicate keypoints.
module orb_fast9_nms #(
    parameter integer WIDTH = 1280,
    parameter integer HEIGHT = 720,
    parameter integer X_WIDTH = (WIDTH <= 2) ? 1 : $clog2(WIDTH),
    parameter integer Y_WIDTH = (HEIGHT <= 2) ? 1 : $clog2(HEIGHT),
    parameter integer SCORE_LINE_WIDTH = WIDTH - 6,
    parameter integer ADDR_WIDTH = (SCORE_LINE_WIDTH <= 2)
                                   ? 1 : $clog2(SCORE_LINE_WIDTH)
) (
    input  wire                     clk,
    input  wire                     rst,

    input  wire [X_WIDTH-1:0]       s_x,
    input  wire [Y_WIDTH-1:0]       s_y,
    input  wire [7:0]               s_score,
    input  wire                     s_corner,
    input  wire                     s_valid,
    output wire                     s_ready,

    output reg  [X_WIDTH-1:0]       m_x,
    output reg  [Y_WIDTH-1:0]       m_y,
    output reg  [7:0]               m_score,
    output reg                      m_keep,
    output reg                      m_sof,
    output reg                      m_eol,
    output reg                      m_valid,
    input  wire                     m_ready
);

    localparam [X_WIDTH-1:0] LAST_SCORE_INPUT_X = WIDTH - 4;

    wire ce = !m_valid || m_ready;
    assign s_ready = ce;
    wire input_fire = s_valid && s_ready;
    wire [ADDR_WIDTH-1:0] input_col = s_x - 3;
    wire [8:0] input_word = {s_corner, s_score};

    (* ram_style = "block" *) reg [8:0] line1 [0:SCORE_LINE_WIDTH-1];
    (* ram_style = "block" *) reg [8:0] line2 [0:SCORE_LINE_WIDTH-1];

    reg [8:0] row0_q, row1_q, row2_q;
    reg [X_WIDTH-1:0] score_x_q;
    reg [Y_WIDTH-1:0] score_y_q;
    reg score_valid_q;

    // Register the two halves of the maximum comparison before the final
    // keep decision.  Besides adding one cycle of latency, this breaks the
    // BRAM/read-history -> max tree -> two comparisons -> m_keep path that
    // otherwise limits the integrated design clock frequency.
    reg [X_WIDTH-1:0] select_x_q;
    reg [Y_WIDTH-1:0] select_y_q;
    reg [7:0] select_center_q;
    reg [7:0] select_earlier_max_q;
    reg [7:0] select_later_max_q;
    reg select_center_valid_q;
    reg select_sof_q;
    reg select_eol_q;
    reg select_valid_q;

    // Previous one and two columns for each active row.
    reg [8:0] hist0 [0:1];
    reg [8:0] hist1 [0:1];
    reg [8:0] hist2 [0:1];

    wire window_valid = score_valid_q
                        && (score_x_q >= 5)
                        && (score_y_q >= 5);

    function [7:0] max2;
        input [7:0] left;
        input [7:0] right;
        begin
            max2 = (left > right) ? left : right;
        end
    endfunction

    wire [7:0] top_left     = hist2[1][7:0];
    wire [7:0] top          = hist2[0][7:0];
    wire [7:0] top_right    = row2_q[7:0];
    wire [7:0] left         = hist1[1][7:0];
    wire [7:0] center       = hist1[0][7:0];
    wire       center_valid = hist1[0][8];
    wire [7:0] right        = row1_q[7:0];
    wire [7:0] bottom_left  = hist0[1][7:0];
    wire [7:0] bottom       = hist0[0][7:0];
    wire [7:0] bottom_right = row0_q[7:0];

    wire [7:0] earlier_max = max2(
        max2(top_left, top), max2(top_right, left)
    );
    wire [7:0] later_max = max2(
        max2(right, bottom_left), max2(bottom, bottom_right)
    );
    wire selected = select_center_valid_q
                    && (select_center_q > select_earlier_max_q)
                    && (select_center_q >= select_later_max_q);

    // Data memories and histories are guarded by score_valid_q and need no
    // reset.  Keeping resets off these arrays preserves BRAM inference.
    always @(posedge clk) begin
        if (ce) begin
            if (input_fire) begin
                row0_q <= input_word;
                row1_q <= line1[input_col];
                row2_q <= line2[input_col];
                line1[input_col] <= input_word;
                line2[input_col] <= line1[input_col];
                score_x_q <= s_x;
                score_y_q <= s_y;
            end

            if (score_valid_q) begin
                hist0[1] <= hist0[0];
                hist1[1] <= hist1[0];
                hist2[1] <= hist2[0];
                hist0[0] <= row0_q;
                hist1[0] <= row1_q;
                hist2[0] <= row2_q;
            end

            if (window_valid) begin
                select_x_q <= score_x_q - 1'b1;
                select_y_q <= score_y_q - 1'b1;
                select_center_q <= center;
                select_earlier_max_q <= earlier_max;
                select_later_max_q <= later_max;
                select_center_valid_q <= center_valid;
                select_sof_q <= (score_x_q == 5) && (score_y_q == 5);
                select_eol_q <= (score_x_q == LAST_SCORE_INPUT_X);
            end

            if (select_valid_q) begin
                m_x <= select_x_q;
                m_y <= select_y_q;
                m_score <= select_center_q;
                m_keep <= selected;
                m_sof <= select_sof_q;
                m_eol <= select_eol_q;
            end
        end
    end

    always @(posedge clk) begin
        if (rst) begin
            score_valid_q <= 1'b0;
            select_valid_q <= 1'b0;
            m_valid <= 1'b0;
        end else if (ce) begin
            score_valid_q <= input_fire;
            select_valid_q <= window_valid;
            m_valid <= select_valid_q;
        end
    end

endmodule
