`timescale 1ns/1ps

`define INPUT_PIXELS_HEX "panorama/build/pl_fast_batch_320x180/input_pixels.hex"
`define OUTPUT_CANDIDATES_HEX "panorama/build/pl_fast_batch_320x180/candidates.hex"
`define OUTPUT_COUNTS_HEX "panorama/build/pl_fast_batch_320x180/counts.hex"
`include "fast_candidate_batch_harness.v"

// A native-HDL clock/reset/start wrapper avoids a Python/VPI wake-up on every
// clock and lets Verilator compile the complete fourteen-frame milestone test
// into one executable.
module fast_candidate_native_batch;
    reg clk = 1'b0;
    reg rst = 1'b1;
    reg start = 1'b0;
    wire batch_done;

    always #5 clk = ~clk;

    fast_candidate_batch_harness #(
        .WIDTH(320),
        .HEIGHT(180),
        .FRAME_COUNT(14),
        .MAX_CANDIDATES(8192),
        .THRESHOLD(20)
    ) harness (
        .clk(clk),
        .rst(rst),
        .start(start),
        .batch_done(batch_done)
    );

    initial begin
        repeat (5) @(posedge clk);
        @(negedge clk); rst = 1'b0;
        @(negedge clk); start = 1'b1;
        @(negedge clk); start = 1'b0;
        wait (batch_done);
        $display("NATIVE_FAST_BATCH_COMPLETE");
        $finish;
    end
endmodule
