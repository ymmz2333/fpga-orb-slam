`timescale 1ns/1ps

// Turn the sparse FAST candidate channel into one bounded AXI-Stream packet.
// A terminal record is always emitted, including for an empty frame, so S2MM
// DMA can report the actual packet length without knowing the corner count in
// advance.
module orb_candidate_packetizer #(
    parameter integer MAX_CANDIDATES = 8192
) (
    input  wire         clk,
    input  wire         rst,

    input  wire [63:0]  s_candidate_data,
    input  wire         s_candidate_valid,
    output wire         s_candidate_ready,
    input  wire         s_frame_done,
    input  wire         s_frame_error,

    output reg  [63:0]  m_axis_tdata,
    output reg  [7:0]   m_axis_tkeep,
    output reg          m_axis_tvalid,
    input  wire         m_axis_tready,
    output reg          m_axis_tlast,

    output reg          packet_done,
    output reg  [31:0]  candidate_count,
    output reg          overflow
);

    localparam [1:0] RUN = 2'd0;
    localparam [1:0] TERMINAL_PENDING = 2'd1;
    localparam [1:0] TERMINAL_OUTPUT = 2'd2;

    reg [1:0] state;
    reg [31:0] terminal_count;
    reg [7:0] terminal_status;

    wire output_available = !m_axis_tvalid || m_axis_tready;
    assign s_candidate_ready = (state == RUN) &&
        ((candidate_count >= MAX_CANDIDATES) || output_available);
    wire candidate_fire = s_candidate_valid && s_candidate_ready;
    wire candidate_kept = candidate_fire &&
        (candidate_count < MAX_CANDIDATES);
    wire overflow_next = overflow ||
        (candidate_fire && (candidate_count >= MAX_CANDIDATES));

    always @(posedge clk) begin
        if (rst) begin
            state <= RUN;
            m_axis_tdata <= 0;
            m_axis_tkeep <= 8'hff;
            m_axis_tvalid <= 1'b0;
            m_axis_tlast <= 1'b0;
            packet_done <= 1'b0;
            candidate_count <= 0;
            terminal_count <= 0;
            terminal_status <= 0;
            overflow <= 1'b0;
        end else begin
            packet_done <= 1'b0;

            case (state)
                RUN: begin
                    if (m_axis_tvalid && m_axis_tready)
                        m_axis_tvalid <= 1'b0;

                    if (candidate_kept) begin
                        m_axis_tdata <= s_candidate_data;
                        m_axis_tkeep <= 8'hff;
                        m_axis_tvalid <= 1'b1;
                        m_axis_tlast <= 1'b0;
                        candidate_count <= candidate_count + 1'b1;
                    end

                    if (candidate_fire &&
                        (candidate_count >= MAX_CANDIDATES))
                        overflow <= 1'b1;

                    if (s_frame_done) begin
                        terminal_count <= candidate_count +
                            (candidate_kept ? 32'd1 : 32'd0);
                        terminal_status <= {
                            6'd0, s_frame_error, overflow_next
                        };
                        state <= TERMINAL_PENDING;
                    end
                end

                TERMINAL_PENDING: begin
                    // Wait until the final ordinary candidate has transferred,
                    // then place the terminal record in the same output slot.
                    if (!m_axis_tvalid || m_axis_tready) begin
                        m_axis_tdata <= {
                            16'hffff, terminal_status, 8'd0, terminal_count
                        };
                        m_axis_tkeep <= 8'hff;
                        m_axis_tvalid <= 1'b1;
                        m_axis_tlast <= 1'b1;
                        state <= TERMINAL_OUTPUT;
                    end
                end

                TERMINAL_OUTPUT: begin
                    if (m_axis_tvalid && m_axis_tready) begin
                        m_axis_tvalid <= 1'b0;
                        m_axis_tlast <= 1'b0;
                        packet_done <= 1'b1;
                        candidate_count <= 0;
                        overflow <= 1'b0;
                        state <= RUN;
                    end
                end

                default: state <= RUN;
            endcase
        end
    end

endmodule
