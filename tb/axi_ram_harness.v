`timescale 1ns/1ps

// Signal-only harness used to unit-test the cocotb AXI RAM model.  The ports
// are driven through VPI by the Python testbench; declaring them as top-level
// ports prevents an HDL compiler from optimizing them away.
module axi_ram_harness (
    input wire        clk,
    input wire        rst,
    input wire [31:0] m_axi_awaddr,
    input wire [7:0]  m_axi_awlen,
    input wire [2:0]  m_axi_awsize,
    input wire [1:0]  m_axi_awburst,
    input wire        m_axi_awvalid,
    input wire        m_axi_awready,
    input wire [31:0] m_axi_wdata,
    input wire [3:0]  m_axi_wstrb,
    input wire        m_axi_wlast,
    input wire        m_axi_wvalid,
    input wire        m_axi_wready,
    input wire [1:0]  m_axi_bresp,
    input wire        m_axi_bvalid,
    input wire        m_axi_bready,
    input wire [31:0] m_axi_araddr,
    input wire [7:0]  m_axi_arlen,
    input wire [2:0]  m_axi_arsize,
    input wire [1:0]  m_axi_arburst,
    input wire        m_axi_arvalid,
    input wire        m_axi_arready,
    input wire [31:0] m_axi_rdata,
    input wire [1:0]  m_axi_rresp,
    input wire        m_axi_rlast,
    input wire        m_axi_rvalid,
    input wire        m_axi_rready
);
endmodule

