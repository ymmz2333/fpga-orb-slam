`timescale 1ns/1ps

// Streaming FAST-9 detector for an 8-bit grayscale raster.
//
// The input is one pixel per accepted clock in row-major order.  Six line
// buffers and horizontal shift registers form the 7x7 neighbourhood required
// by the radius-three FAST circle.  The output contains every interior pixel
// (the three-pixel image border is omitted), its FAST score, and a thresholded
// corner flag.  Emitting every score makes the following 3x3 non-maximum
// suppression stage deterministic and independently testable.
//
// FAST score used here:
//   max over all 16 circular starts and both polarities of
//   min over 9 consecutive pixels of the bright/dark intensity margin.
// A pixel is a corner when score > THRESHOLD.
module orb_fast9_stream #(
    parameter integer WIDTH = 1280,
    parameter integer HEIGHT = 720,
    parameter integer THRESHOLD = 20,
    parameter integer X_WIDTH = (WIDTH <= 2) ? 1 : $clog2(WIDTH),
    parameter integer Y_WIDTH = (HEIGHT <= 2) ? 1 : $clog2(HEIGHT)
) (
    input  wire                     clk,
    input  wire                     rst,

    input  wire [7:0]               s_axis_tdata,
    input  wire                     s_axis_tvalid,
    output wire                     s_axis_tready,
    input  wire                     s_axis_tuser,
    input  wire                     s_axis_tlast,

    output reg  [X_WIDTH-1:0]       m_x,
    output reg  [Y_WIDTH-1:0]       m_y,
    output reg  [7:0]               m_score,
    output reg                      m_corner,
    output reg                      m_sof,
    output reg                      m_eol,
    output reg                      m_valid,
    input  wire                     m_ready
);

    localparam [7:0] THRESHOLD_VALUE = THRESHOLD;
    localparam [X_WIDTH-1:0] LAST_INTERIOR_X = WIDTH - 4;

    // Stalling the output stalls the whole window generator and score
    // pipeline.  This preserves every pixel without a large output FIFO.
    wire ce = !m_valid || m_ready;
    assign s_axis_tready = ce;
    wire input_fire = s_axis_tvalid && s_axis_tready;

    reg [X_WIDTH-1:0] input_x;
    reg [Y_WIDTH-1:0] input_y;
    wire [X_WIDTH-1:0] accepted_x = s_axis_tuser
                                   ? {X_WIDTH{1'b0}} : input_x;
    wire [Y_WIDTH-1:0] accepted_y = s_axis_tuser
                                   ? {Y_WIDTH{1'b0}} : input_y;

    // Each memory delays the stream by one complete row.  The read-before-
    // write pattern is supported by Xilinx block RAM and avoids a 1280-byte
    // register chain for each stored line.
    (* ram_style = "block" *) reg [7:0] line1 [0:WIDTH-1];
    (* ram_style = "block" *) reg [7:0] line2 [0:WIDTH-1];
    (* ram_style = "block" *) reg [7:0] line3 [0:WIDTH-1];
    (* ram_style = "block" *) reg [7:0] line4 [0:WIDTH-1];
    (* ram_style = "block" *) reg [7:0] line5 [0:WIDTH-1];
    (* ram_style = "block" *) reg [7:0] line6 [0:WIDTH-1];

    reg [7:0] row0_q, row1_q, row2_q, row3_q;
    reg [7:0] row4_q, row5_q, row6_q;
    reg [X_WIDTH-1:0] pixel_x_q;
    reg [Y_WIDTH-1:0] pixel_y_q;
    reg pixel_valid_q;

    // Index zero is x-1 and index five is x-6 before the current sample is
    // shifted in.  There is one history for each of the seven active rows.
    reg [7:0] hist0 [0:5];
    reg [7:0] hist1 [0:5];
    reg [7:0] hist2 [0:5];
    reg [7:0] hist3 [0:5];
    reg [7:0] hist4 [0:5];
    reg [7:0] hist5 [0:5];
    reg [7:0] hist6 [0:5];

    wire window_valid = pixel_valid_q
                        && (pixel_x_q >= 6)
                        && (pixel_y_q >= 6);

    function [7:0] min2;
        input [7:0] left;
        input [7:0] right;
        begin
            min2 = (left < right) ? left : right;
        end
    endfunction

    function [7:0] max2;
        input [7:0] left;
        input [7:0] right;
        begin
            max2 = (left > right) ? left : right;
        end
    endfunction

    // First half of the pipelined nine-value minimum: two comparison levels
    // reduce each group of four.  A later stage combines the two group minima
    // with the ninth value, keeping either stage to two comparison levels.
    function [7:0] min4;
        input [31:0] values;
        reg [7:0] m01, m23;
        begin
            m01 = min2(values[7:0],   values[15:8]);
            m23 = min2(values[23:16], values[31:24]);
            min4 = min2(m01, m23);
        end
    endfunction

    // Stage A: center and the 16 radius-three circle pixels.
    reg [7:0] center_a;
    reg [7:0] circle_a [0:15];
    reg [X_WIDTH-1:0] x_a;
    reg [Y_WIDTH-1:0] y_a;

    // Stage B: unsigned bright and dark margins.
    reg [7:0] bright_b [0:15];
    reg [7:0] dark_b [0:15];
    reg [X_WIDTH-1:0] x_b;
    reg [Y_WIDTH-1:0] y_b;

    wire [127:0] bright_b_packed;
    wire [127:0] dark_b_packed;
    genvar packed_index;
    generate
        for (packed_index = 0; packed_index < 16;
             packed_index = packed_index + 1) begin : pack_margins
            assign bright_b_packed[packed_index*8 +: 8] = bright_b[packed_index];
            assign dark_b_packed[packed_index*8 +: 8] = dark_b[packed_index];
        end
    endgenerate
    wire [255:0] bright_b_twice = {bright_b_packed, bright_b_packed};
    wire [255:0] dark_b_twice = {dark_b_packed, dark_b_packed};

    // Stage C0: reduce the first and second groups of four pixels in every
    // nine-pixel arc, and carry the ninth pixel into the next stage.
    reg [7:0] bright_c0_left [0:15];
    reg [7:0] bright_c0_right [0:15];
    reg [7:0] bright_c0_last [0:15];
    reg [7:0] dark_c0_left [0:15];
    reg [7:0] dark_c0_right [0:15];
    reg [7:0] dark_c0_last [0:15];
    reg [X_WIDTH-1:0] x_c0;
    reg [Y_WIDTH-1:0] y_c0;

    // Stage C: finish the minimum margin for every possible nine-pixel arc.
    reg [7:0] bright_c [0:15];
    reg [7:0] dark_c [0:15];
    reg [X_WIDTH-1:0] x_c;
    reg [Y_WIDTH-1:0] y_c;

    // Stages D-F: balanced maximum reduction over the 16 arcs.
    reg [7:0] bright_d [0:7];
    reg [7:0] dark_d [0:7];
    reg [7:0] bright_e [0:3];
    reg [7:0] dark_e [0:3];
    reg [7:0] bright_f [0:1];
    reg [7:0] dark_f [0:1];
    reg [X_WIDTH-1:0] x_d, x_e, x_f;
    reg [Y_WIDTH-1:0] y_d, y_e, y_f;

    reg valid_a, valid_b, valid_c0, valid_c, valid_d, valid_e, valid_f;
    integer i;

    // Memories and wide datapath registers intentionally have no reset.  All
    // of their consumers are qualified by valid bits, greatly reducing reset
    // fanout and allowing the line arrays to infer block RAM.
    always @(posedge clk) begin
        if (ce) begin
            if (input_fire) begin
                row0_q <= s_axis_tdata;
                row1_q <= line1[accepted_x];
                row2_q <= line2[accepted_x];
                row3_q <= line3[accepted_x];
                row4_q <= line4[accepted_x];
                row5_q <= line5[accepted_x];
                row6_q <= line6[accepted_x];

                line1[accepted_x] <= s_axis_tdata;
                line2[accepted_x] <= line1[accepted_x];
                line3[accepted_x] <= line2[accepted_x];
                line4[accepted_x] <= line3[accepted_x];
                line5[accepted_x] <= line4[accepted_x];
                line6[accepted_x] <= line5[accepted_x];
                pixel_x_q <= accepted_x;
                pixel_y_q <= accepted_y;
            end

            if (pixel_valid_q) begin
                for (i = 5; i > 0; i = i - 1) begin
                    hist0[i] <= hist0[i-1];
                    hist1[i] <= hist1[i-1];
                    hist2[i] <= hist2[i-1];
                    hist3[i] <= hist3[i-1];
                    hist4[i] <= hist4[i-1];
                    hist5[i] <= hist5[i-1];
                    hist6[i] <= hist6[i-1];
                end
                hist0[0] <= row0_q;
                hist1[0] <= row1_q;
                hist2[0] <= row2_q;
                hist3[0] <= row3_q;
                hist4[0] <= row4_q;
                hist5[0] <= row5_q;
                hist6[0] <= row6_q;
            end

            if (window_valid) begin
                center_a <= hist3[2];
                // Clockwise from the top of the FAST circle.
                circle_a[0]  <= hist6[2];
                circle_a[1]  <= hist6[1];
                circle_a[2]  <= hist5[0];
                circle_a[3]  <= row4_q;
                circle_a[4]  <= row3_q;
                circle_a[5]  <= row2_q;
                circle_a[6]  <= hist1[0];
                circle_a[7]  <= hist0[1];
                circle_a[8]  <= hist0[2];
                circle_a[9]  <= hist0[3];
                circle_a[10] <= hist1[4];
                circle_a[11] <= hist2[5];
                circle_a[12] <= hist3[5];
                circle_a[13] <= hist4[5];
                circle_a[14] <= hist5[4];
                circle_a[15] <= hist6[3];
                x_a <= pixel_x_q - 3;
                y_a <= pixel_y_q - 3;
            end

            if (valid_a) begin
                for (i = 0; i < 16; i = i + 1) begin
                    bright_b[i] <= (circle_a[i] > center_a)
                                   ? circle_a[i] - center_a : 8'd0;
                    dark_b[i] <= (circle_a[i] < center_a)
                                 ? center_a - circle_a[i] : 8'd0;
                end
                x_b <= x_a;
                y_b <= y_a;
            end

            if (valid_b) begin
                for (i = 0; i < 16; i = i + 1) begin
                    bright_c0_left[i] <= min4(
                        bright_b_twice[i*8 +: 32]
                    );
                    bright_c0_right[i] <= min4(
                        bright_b_twice[i*8+32 +: 32]
                    );
                    bright_c0_last[i] <= bright_b_twice[i*8+64 +: 8];
                    dark_c0_left[i] <= min4(
                        dark_b_twice[i*8 +: 32]
                    );
                    dark_c0_right[i] <= min4(
                        dark_b_twice[i*8+32 +: 32]
                    );
                    dark_c0_last[i] <= dark_b_twice[i*8+64 +: 8];
                end
                x_c0 <= x_b;
                y_c0 <= y_b;
            end

            if (valid_c0) begin
                for (i = 0; i < 16; i = i + 1) begin
                    bright_c[i] <= min2(
                        min2(bright_c0_left[i], bright_c0_right[i]),
                        bright_c0_last[i]
                    );
                    dark_c[i] <= min2(
                        min2(dark_c0_left[i], dark_c0_right[i]),
                        dark_c0_last[i]
                    );
                end
                x_c <= x_c0;
                y_c <= y_c0;
            end

            if (valid_c) begin
                for (i = 0; i < 8; i = i + 1) begin
                    bright_d[i] <= max2(bright_c[i*2], bright_c[i*2+1]);
                    dark_d[i] <= max2(dark_c[i*2], dark_c[i*2+1]);
                end
                x_d <= x_c;
                y_d <= y_c;
            end

            if (valid_d) begin
                for (i = 0; i < 4; i = i + 1) begin
                    bright_e[i] <= max2(bright_d[i*2], bright_d[i*2+1]);
                    dark_e[i] <= max2(dark_d[i*2], dark_d[i*2+1]);
                end
                x_e <= x_d;
                y_e <= y_d;
            end

            if (valid_e) begin
                for (i = 0; i < 2; i = i + 1) begin
                    bright_f[i] <= max2(bright_e[i*2], bright_e[i*2+1]);
                    dark_f[i] <= max2(dark_e[i*2], dark_e[i*2+1]);
                end
                x_f <= x_e;
                y_f <= y_e;
            end

            if (valid_f) begin
                m_score <= max2(
                    max2(bright_f[0], bright_f[1]),
                    max2(dark_f[0], dark_f[1])
                );
                m_corner <= (max2(
                    max2(bright_f[0], bright_f[1]),
                    max2(dark_f[0], dark_f[1])
                ) > THRESHOLD_VALUE);
                m_x <= x_f;
                m_y <= y_f;
                m_sof <= (x_f == 3) && (y_f == 3);
                m_eol <= (x_f == LAST_INTERIOR_X);
            end
        end
    end

    // Coordinate and validity control are the only resettable state in the
    // high-fanout streaming path.
    always @(posedge clk) begin
        if (rst) begin
            input_x <= {X_WIDTH{1'b0}};
            input_y <= {Y_WIDTH{1'b0}};
            pixel_valid_q <= 1'b0;
            valid_a <= 1'b0;
            valid_b <= 1'b0;
            valid_c0 <= 1'b0;
            valid_c <= 1'b0;
            valid_d <= 1'b0;
            valid_e <= 1'b0;
            valid_f <= 1'b0;
            m_valid <= 1'b0;
        end else if (ce) begin
            pixel_valid_q <= input_fire;
            valid_a <= window_valid;
            valid_b <= valid_a;
            valid_c0 <= valid_b;
            valid_c <= valid_c0;
            valid_d <= valid_c;
            valid_e <= valid_d;
            valid_f <= valid_e;
            m_valid <= valid_f;

            if (input_fire) begin
                if (s_axis_tlast) begin
                    input_x <= {X_WIDTH{1'b0}};
                    input_y <= accepted_y + 1'b1;
                end else begin
                    input_x <= accepted_x + 1'b1;
                    input_y <= accepted_y;
                end
            end
        end
    end

endmodule
