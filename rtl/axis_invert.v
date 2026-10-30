`timescale 1ns/1ps

// Minimal AXI4-Stream image-processing example.
//
// One 8-bit grayscale pixel is accepted whenever s_axis_tvalid and
// s_axis_tready are both high.  The example operation is pixel inversion:
// output = 255 - input.  Replace this operation with a real pipeline while
// keeping the ready/valid behavior unchanged.
module axis_invert (
    input  wire       clk,
    input  wire       rst,

    input  wire [7:0] s_axis_tdata,
    input  wire       s_axis_tvalid,
    output wire       s_axis_tready,
    input  wire       s_axis_tuser,  // start of frame
    input  wire       s_axis_tlast,  // end of line

    output reg  [7:0] m_axis_tdata,
    output reg        m_axis_tvalid,
    input  wire       m_axis_tready,
    output reg        m_axis_tuser,
    output reg        m_axis_tlast
);

    // A one-entry elastic output register.  It can accept new data whenever
    // it is empty or its current item is being consumed in this cycle.
    assign s_axis_tready = ~m_axis_tvalid | m_axis_tready;

    always @(posedge clk) begin
        if (rst) begin
            m_axis_tdata  <= 8'd0;
            m_axis_tvalid <= 1'b0;
            m_axis_tuser  <= 1'b0;
            m_axis_tlast  <= 1'b0;
        end else if (s_axis_tready) begin
            m_axis_tvalid <= s_axis_tvalid;
            if (s_axis_tvalid) begin
                m_axis_tdata <= 8'hff - s_axis_tdata;
                m_axis_tuser <= s_axis_tuser;
                m_axis_tlast <= s_axis_tlast;
            end
        end
    end

endmodule

