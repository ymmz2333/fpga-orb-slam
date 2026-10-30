`timescale 1ns/1ps

`ifndef INPUT_PIXELS_HEX
`define INPUT_PIXELS_HEX "input_pixels.hex"
`endif
`ifndef OUTPUT_CANDIDATES_HEX
`define OUTPUT_CANDIDATES_HEX "candidates.hex"
`endif
`ifndef OUTPUT_COUNTS_HEX
`define OUTPUT_COUNTS_HEX "counts.hex"
`endif

// Native-HDL batch driver.  Cocotb waits only for batch_done, avoiding one
// Python coroutine wake-up for every pixel while the actual RTL still runs
// every clock for every supplied frame.
module fast_candidate_batch_harness #(
    parameter integer WIDTH = 320,
    parameter integer HEIGHT = 180,
    parameter integer FRAME_COUNT = 14,
    parameter integer MAX_CANDIDATES = 8192,
    parameter integer THRESHOLD = 20,
    parameter integer FRAME_PIXELS = WIDTH * HEIGHT,
    parameter integer TOTAL_PIXELS = FRAME_PIXELS * FRAME_COUNT
) (
    input  wire clk,
    input  wire rst,
    input  wire start,
    output reg  batch_done
);

    reg [7:0] pixel_mem [0:TOTAL_PIXELS-1];
    reg [63:0] candidate_mem [0:FRAME_COUNT*MAX_CANDIDATES-1];
    reg [31:0] count_mem [0:FRAME_COUNT-1];

    initial begin
        $readmemh(`INPUT_PIXELS_HEX, pixel_mem);
    end

    reg running;
    reg waiting_for_frame;
    reg dump_pending;
    integer frame_index;
    integer pixel_index;
    integer candidate_index;

    wire [7:0] pixel_data = pixel_mem[frame_index * FRAME_PIXELS + pixel_index];
    wire pixel_valid = running && !waiting_for_frame;
    wire pixel_ready;
    wire pixel_sof = pixel_index == 0;
    wire pixel_eol = (pixel_index % WIDTH) == WIDTH - 1;

    wire [63:0] candidate_data;
    wire candidate_valid;
    wire candidate_ready = 1'b1;
    wire frame_done;
    wire [31:0] candidate_count;

    orb_fast9_candidate_stream #(
        .WIDTH(WIDTH),
        .HEIGHT(HEIGHT),
        .THRESHOLD(THRESHOLD)
    ) dut_i (
        .clk(clk),
        .rst(rst),
        .s_axis_tdata(pixel_data),
        .s_axis_tvalid(pixel_valid),
        .s_axis_tready(pixel_ready),
        .s_axis_tuser(pixel_sof),
        .s_axis_tlast(pixel_eol),
        .m_candidate_data(candidate_data),
        .m_candidate_valid(candidate_valid),
        .m_candidate_ready(candidate_ready),
        .m_frame_done(frame_done),
        .m_candidate_count(candidate_count)
    );

    always @(posedge clk) begin
        if (rst) begin
            running <= 1'b0;
            waiting_for_frame <= 1'b0;
            dump_pending <= 1'b0;
            batch_done <= 1'b0;
            frame_index <= 0;
            pixel_index <= 0;
            candidate_index <= 0;
        end else begin
            if (start && !running && !batch_done)
                running <= 1'b1;

            if (pixel_valid && pixel_ready) begin
                if (pixel_index == FRAME_PIXELS - 1) begin
                    waiting_for_frame <= 1'b1;
                end else begin
                    pixel_index <= pixel_index + 1;
                end
            end

            if (candidate_valid && candidate_ready) begin
                if (candidate_index >= MAX_CANDIDATES)
                    $fatal(1, "candidate list overflow on frame %0d", frame_index);
                candidate_mem[frame_index * MAX_CANDIDATES + candidate_index]
                    <= candidate_data;
                candidate_index <= candidate_index + 1;
            end

            if (frame_done) begin
                count_mem[frame_index] <= candidate_count;
                if (candidate_count != candidate_index)
                    $fatal(1, "candidate count mismatch on frame %0d", frame_index);
                if (frame_index == FRAME_COUNT - 1) begin
                    running <= 1'b0;
                    dump_pending <= 1'b1;
                end else begin
                    frame_index <= frame_index + 1;
                    pixel_index <= 0;
                    candidate_index <= 0;
                    waiting_for_frame <= 1'b0;
                end
            end

            // Delay file output one clock so the final nonblocking candidate
            // and count writes are visible to $writememh.
            if (dump_pending) begin
                $writememh(`OUTPUT_CANDIDATES_HEX, candidate_mem);
                $writememh(`OUTPUT_COUNTS_HEX, count_mem);
                dump_pending <= 1'b0;
                batch_done <= 1'b1;
            end
        end
    end

endmodule
