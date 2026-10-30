`timescale 1ns/1ps

// Intentional functional bug: bit 255 is ignored during every comparison.
// The module is used to prove that synthesis/lint can accept wrong logic while
// the cocotb reference model still catches it.
module orb_hamming_matcher_bad_msb (
    input  wire         clk,
    input  wire         rst,
    input  wire [255:0] q_desc,
    input  wire         q_valid,
    output wire         q_ready,
    input  wire [255:0] s_desc,
    input  wire [15:0]  s_index,
    input  wire         s_last,
    input  wire         s_valid,
    output wire         s_ready,
    output wire [15:0]  m_best_index,
    output wire [8:0]   m_best_distance,
    output wire [15:0]  m_second_index,
    output wire [8:0]   m_second_distance,
    output wire         m_match_valid,
    input  wire         m_match_ready
);

    orb_hamming_matcher #(.IGNORE_MSB(1)) broken_core (.*);

endmodule
