`timescale 1ns/1ps

// Convert one raw AXI-Stream frame packet into the video-style framing used by
// the retained FAST core.  The input TLAST marks the end of the complete DMA
// transfer; the output TLAST marks the end of every image row and TUSER marks
// the first pixel of the frame.
module axis_video_framer #(
    parameter integer WIDTH = 1280,
    parameter integer HEIGHT = 720,
    parameter integer X_WIDTH = (WIDTH <= 2) ? 1 : $clog2(WIDTH),
    parameter integer Y_WIDTH = (HEIGHT <= 2) ? 1 : $clog2(HEIGHT)
) (
    input  wire                 clk,
    input  wire                 rst,

    input  wire [7:0]           s_axis_tdata,
    input  wire                 s_axis_tvalid,
    output wire                 s_axis_tready,
    input  wire                 s_axis_tlast,

    output wire [7:0]           m_axis_tdata,
    output wire                 m_axis_tvalid,
    input  wire                 m_axis_tready,
    output wire                 m_axis_tuser,
    output wire                 m_axis_tlast,

    output reg                  frame_done,
    output reg                  frame_error
);

    reg [X_WIDTH-1:0] x_count;
    reg [Y_WIDTH-1:0] y_count;
    reg active_error;
    reg [7:0] output_data;
    reg output_valid;
    reg output_user;
    reg output_last;
    reg output_final;

    localparam [X_WIDTH-1:0] LAST_X = WIDTH - 1;
    localparam [Y_WIDTH-1:0] LAST_Y = HEIGHT - 1;

    wire transfer = s_axis_tvalid && s_axis_tready;
    wire first_pixel = (x_count == 0) && (y_count == 0);
    wire end_of_line = (x_count == LAST_X);
    wire final_pixel = end_of_line && (y_count == LAST_Y);

    // One-word elastic output register.  Besides preserving full throughput,
    // this is an intentional timing boundary: the frame counters no longer
    // drive the FAST line-memory address through a combinational TUSER path.
    assign s_axis_tready = !output_valid || m_axis_tready;
    assign m_axis_tdata = output_data;
    assign m_axis_tvalid = output_valid;
    assign m_axis_tuser = output_user;
    assign m_axis_tlast = output_last;

    always @(posedge clk) begin
        if (rst) begin
            x_count <= 0;
            y_count <= 0;
            active_error <= 1'b0;
            frame_error <= 1'b0;
            frame_done <= 1'b0;
            output_data <= 8'd0;
            output_valid <= 1'b0;
            output_user <= 1'b0;
            output_last <= 1'b0;
            output_final <= 1'b0;
        end else begin
            // Completion means that the final registered pixel has actually
            // been accepted downstream, not merely accepted at the raw input.
            frame_done <= output_valid && m_axis_tready && output_final;

            // If the output is empty, or its current item is accepted, load
            // the next input item.  Backpressure holds all output fields.
            if (s_axis_tready) begin
                output_valid <= s_axis_tvalid;
                if (s_axis_tvalid) begin
                    output_data <= s_axis_tdata;
                    output_user <= first_pixel;
                    output_last <= end_of_line;
                    output_final <= final_pixel;
                end
            end

            if (transfer) begin
                // A raw DMA packet must assert TLAST only on the final pixel.
                if (first_pixel)
                    active_error <= s_axis_tlast && !final_pixel;
                else if (s_axis_tlast != final_pixel)
                    active_error <= 1'b1;

                if (final_pixel) begin
                    frame_error <= active_error || !s_axis_tlast;
                    x_count <= 0;
                    y_count <= 0;
                    active_error <= 1'b0;
                end else if (end_of_line) begin
                    x_count <= 0;
                    y_count <= y_count + 1'b1;
                end else begin
                    x_count <= x_count + 1'b1;
                end
            end
        end
    end

endmodule
