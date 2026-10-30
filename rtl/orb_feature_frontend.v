`timescale 1ns/1ps

// DMA-facing ORB candidate front end.  The input is one raw grayscale frame
// packet (TLAST only on the final byte); the output is a bounded list of
// 64-bit candidates followed by one terminal record with TLAST asserted.
module orb_feature_frontend #(
    parameter integer WIDTH = 1280,
    parameter integer HEIGHT = 720,
    parameter integer THRESHOLD = 20,
    parameter integer MAX_CANDIDATES = 8192
) (
    input  wire         aclk,
    input  wire         aresetn,

    input  wire [7:0]   s_axis_tdata,
    input  wire         s_axis_tvalid,
    output wire         s_axis_tready,
    input  wire         s_axis_tlast,

    output wire [63:0]  m_axis_tdata,
    output wire [7:0]   m_axis_tkeep,
    output wire         m_axis_tvalid,
    input  wire         m_axis_tready,
    output wire         m_axis_tlast,

    output wire         packet_done,
    output wire [31:0]  candidate_count,
    output wire         overflow,
    output wire         frame_error
);

    wire rst = !aresetn;
    wire [7:0] video_data;
    wire video_valid;
    wire video_ready;
    wire video_user;
    wire video_last;
    wire raw_frame_done;
    wire raw_frame_error;

    wire [63:0] candidate_data;
    wire candidate_valid;
    wire candidate_ready;
    wire fast_frame_done;
    wire [31:0] fast_candidate_count;

    reg retained_frame_error;
    always @(posedge aclk) begin
        if (rst)
            retained_frame_error <= 1'b0;
        else begin
            if (raw_frame_done)
                retained_frame_error <= raw_frame_error;
            if (packet_done)
                retained_frame_error <= 1'b0;
        end
    end
    assign frame_error = retained_frame_error;

    axis_video_framer #(
        .WIDTH(WIDTH),
        .HEIGHT(HEIGHT)
    ) framer_i (
        .clk(aclk),
        .rst(rst),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .s_axis_tlast(s_axis_tlast),
        .m_axis_tdata(video_data),
        .m_axis_tvalid(video_valid),
        .m_axis_tready(video_ready),
        .m_axis_tuser(video_user),
        .m_axis_tlast(video_last),
        .frame_done(raw_frame_done),
        .frame_error(raw_frame_error)
    );

    orb_fast9_candidate_stream #(
        .WIDTH(WIDTH),
        .HEIGHT(HEIGHT),
        .THRESHOLD(THRESHOLD)
    ) fast_i (
        .clk(aclk),
        .rst(rst),
        .s_axis_tdata(video_data),
        .s_axis_tvalid(video_valid),
        .s_axis_tready(video_ready),
        .s_axis_tuser(video_user),
        .s_axis_tlast(video_last),
        .m_candidate_data(candidate_data),
        .m_candidate_valid(candidate_valid),
        .m_candidate_ready(candidate_ready),
        .m_frame_done(fast_frame_done),
        .m_candidate_count(fast_candidate_count)
    );

    orb_candidate_packetizer #(
        .MAX_CANDIDATES(MAX_CANDIDATES)
    ) packetizer_i (
        .clk(aclk),
        .rst(rst),
        .s_candidate_data(candidate_data),
        .s_candidate_valid(candidate_valid),
        .s_candidate_ready(candidate_ready),
        .s_frame_done(fast_frame_done),
        .s_frame_error(retained_frame_error),
        .m_axis_tdata(m_axis_tdata),
        .m_axis_tkeep(m_axis_tkeep),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tready(m_axis_tready),
        .m_axis_tlast(m_axis_tlast),
        .packet_done(packet_done),
        .candidate_count(candidate_count),
        .overflow(overflow)
    );

endmodule
