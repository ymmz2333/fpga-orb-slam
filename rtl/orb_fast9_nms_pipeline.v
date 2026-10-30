`timescale 1ns/1ps

// Integrated streaming FAST-9 plus deterministic 3x3 NMS candidate.
//
// This wrapper contains no buffering or arithmetic of its own.  It preserves
// the ready/valid backpressure contract between the two independently tested
// cores so the pair can be verified and implemented as one timing candidate.
module orb_fast9_nms_pipeline #(
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

    output wire [X_WIDTH-1:0]       m_x,
    output wire [Y_WIDTH-1:0]       m_y,
    output wire [7:0]               m_score,
    output wire                     m_keep,
    output wire                     m_sof,
    output wire                     m_eol,
    output wire                     m_valid,
    input  wire                     m_ready
);

    wire [X_WIDTH-1:0] fast_x;
    wire [Y_WIDTH-1:0] fast_y;
    wire [7:0] fast_score;
    wire fast_corner;
    wire fast_sof_unused;
    wire fast_eol_unused;
    wire fast_valid;
    wire fast_ready;

    orb_fast9_stream #(
        .WIDTH(WIDTH),
        .HEIGHT(HEIGHT),
        .THRESHOLD(THRESHOLD),
        .X_WIDTH(X_WIDTH),
        .Y_WIDTH(Y_WIDTH)
    ) fast_i (
        .clk(clk),
        .rst(rst),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .s_axis_tuser(s_axis_tuser),
        .s_axis_tlast(s_axis_tlast),
        .m_x(fast_x),
        .m_y(fast_y),
        .m_score(fast_score),
        .m_corner(fast_corner),
        .m_sof(fast_sof_unused),
        .m_eol(fast_eol_unused),
        .m_valid(fast_valid),
        .m_ready(fast_ready)
    );

    orb_fast9_nms #(
        .WIDTH(WIDTH),
        .HEIGHT(HEIGHT),
        .X_WIDTH(X_WIDTH),
        .Y_WIDTH(Y_WIDTH)
    ) nms_i (
        .clk(clk),
        .rst(rst),
        .s_x(fast_x),
        .s_y(fast_y),
        .s_score(fast_score),
        .s_corner(fast_corner),
        .s_valid(fast_valid),
        .s_ready(fast_ready),
        .m_x(m_x),
        .m_y(m_y),
        .m_score(m_score),
        .m_keep(m_keep),
        .m_sof(m_sof),
        .m_eol(m_eol),
        .m_valid(m_valid),
        .m_ready(m_ready)
    );

endmodule
