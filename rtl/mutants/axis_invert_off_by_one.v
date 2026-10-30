`timescale 1ns/1ps

// INTENTIONALLY WRONG: a functionally incorrect version used by
// scripts/demo_debug.py.  It keeps the protocol correct but computes
// 254-input instead of 255-input.
module axis_invert_off_by_one (
    input  wire       clk,
    input  wire       rst,
    input  wire [7:0] s_axis_tdata,
    input  wire       s_axis_tvalid,
    output wire       s_axis_tready,
    input  wire       s_axis_tuser,
    input  wire       s_axis_tlast,
    output reg  [7:0] m_axis_tdata,
    output reg        m_axis_tvalid,
    input  wire       m_axis_tready,
    output reg        m_axis_tuser,
    output reg        m_axis_tlast
);

    assign s_axis_tready = !m_axis_tvalid || m_axis_tready;

    always @(posedge clk) begin
        if (rst) begin
            m_axis_tdata  <= 8'd0;
            m_axis_tvalid <= 1'b0;
            m_axis_tuser  <= 1'b0;
            m_axis_tlast  <= 1'b0;
        end else if (s_axis_tready) begin
            m_axis_tvalid <= s_axis_tvalid;
            if (s_axis_tvalid) begin
                m_axis_tdata <= 8'hFE - s_axis_tdata; // deliberate bug
                m_axis_tuser <= s_axis_tuser;
                m_axis_tlast <= s_axis_tlast;
            end
        end
    end

endmodule
