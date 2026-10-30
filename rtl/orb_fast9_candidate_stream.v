`timescale 1ns/1ps

// Retained FAST-9/NMS pipeline with a compact candidate-list output.
//
// The dense NMS raster remains internal.  Only retained points cross the
// subsystem boundary, so a later AXI stream-to-memory mover writes a few
// thousand 64-bit records instead of a full score frame.
module orb_fast9_candidate_stream #(
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

    output wire [63:0]              m_candidate_data,
    output wire                     m_candidate_valid,
    input  wire                     m_candidate_ready,

    output reg                      m_frame_done,
    output reg  [31:0]              m_candidate_count
);

    localparam [Y_WIDTH-1:0] LAST_NMS_Y = HEIGHT - 5;

    wire [X_WIDTH-1:0] nms_x;
    wire [Y_WIDTH-1:0] nms_y;
    wire [7:0] nms_score;
    wire nms_keep;
    wire nms_sof;
    wire nms_eol;
    wire nms_valid;
    wire nms_ready;

    // A discarded dense item never needs to wait for the sparse consumer.
    // A retained item obeys the ordinary ready/valid hold rule.
    assign nms_ready = !nms_keep || m_candidate_ready;
    assign m_candidate_valid = nms_valid && nms_keep;
    assign m_candidate_data = {
        16'd0, nms_score, 8'd0,
        {{(16-Y_WIDTH){1'b0}}, nms_y},
        {{(16-X_WIDTH){1'b0}}, nms_x}
    };

    wire dense_fire = nms_valid && nms_ready;
    wire candidate_fire = m_candidate_valid && m_candidate_ready;
    wire final_dense_item = dense_fire && nms_eol && (nms_y == LAST_NMS_Y);

    reg [31:0] running_count;

    always @(posedge clk) begin
        if (rst) begin
            running_count <= 0;
            m_candidate_count <= 0;
            m_frame_done <= 1'b0;
        end else begin
            m_frame_done <= 1'b0;

            if (dense_fire && nms_sof)
                running_count <= candidate_fire ? 32'd1 : 32'd0;
            else if (candidate_fire)
                running_count <= running_count + 1'b1;

            if (final_dense_item) begin
                m_candidate_count <= running_count
                    + ((candidate_fire && !nms_sof) ? 32'd1 : 32'd0);
                m_frame_done <= 1'b1;
            end
        end
    end

    orb_fast9_nms_pipeline #(
        .WIDTH(WIDTH),
        .HEIGHT(HEIGHT),
        .THRESHOLD(THRESHOLD),
        .X_WIDTH(X_WIDTH),
        .Y_WIDTH(Y_WIDTH)
    ) pipeline_i (
        .clk(clk),
        .rst(rst),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .s_axis_tuser(s_axis_tuser),
        .s_axis_tlast(s_axis_tlast),
        .m_x(nms_x),
        .m_y(nms_y),
        .m_score(nms_score),
        .m_keep(nms_keep),
        .m_sof(nms_sof),
        .m_eol(nms_eol),
        .m_valid(nms_valid),
        .m_ready(nms_ready)
    );

endmodule
