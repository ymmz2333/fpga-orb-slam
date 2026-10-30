`timescale 1ns/1ps

// Functional AXI4 memory-mapped DMA/accelerator example.
//
// The engine reads one 32-bit word from src_addr, inverts all four grayscale
// pixels, and writes the result to dst_addr.  It repeats until byte_count bytes
// have been processed.
//
// Deliberately simple: one transaction is outstanding and every transaction is
// a single beat.  This makes the control logic easy to study and verify.  It is
// NOT the high-throughput DMA architecture to use for a final competition
// design.  The supplied AXI RAM model supports bursts so this module can later
// be replaced by a burst/FIFO/double-buffered engine without changing the test
// environment.
module axi_image_invert_dma #(
    parameter ADDR_WIDTH = 32,
    parameter DATA_WIDTH = 32
) (
    input  wire                  clk,
    input  wire                  rst,

    input  wire                  start,
    input  wire [ADDR_WIDTH-1:0] src_addr,
    input  wire [ADDR_WIDTH-1:0] dst_addr,
    input  wire [31:0]           byte_count,
    output reg                   busy,
    output reg                   done,
    output reg                   error,

    output reg  [ADDR_WIDTH-1:0] m_axi_awaddr,
    output wire [7:0]            m_axi_awlen,
    output wire [2:0]            m_axi_awsize,
    output wire [1:0]            m_axi_awburst,
    output reg                   m_axi_awvalid,
    input  wire                  m_axi_awready,

    output reg  [DATA_WIDTH-1:0] m_axi_wdata,
    output wire [DATA_WIDTH/8-1:0] m_axi_wstrb,
    output wire                  m_axi_wlast,
    output reg                   m_axi_wvalid,
    input  wire                  m_axi_wready,

    input  wire [1:0]            m_axi_bresp,
    input  wire                  m_axi_bvalid,
    output reg                   m_axi_bready,

    output reg  [ADDR_WIDTH-1:0] m_axi_araddr,
    output wire [7:0]            m_axi_arlen,
    output wire [2:0]            m_axi_arsize,
    output wire [1:0]            m_axi_arburst,
    output reg                   m_axi_arvalid,
    input  wire                  m_axi_arready,

    input  wire [DATA_WIDTH-1:0] m_axi_rdata,
    input  wire [1:0]            m_axi_rresp,
    input  wire                  m_axi_rlast,
    input  wire                  m_axi_rvalid,
    output reg                   m_axi_rready
);

    localparam BYTES_PER_BEAT = DATA_WIDTH / 8;
    localparam SIZE_CODE = $clog2(BYTES_PER_BEAT);

    localparam ST_IDLE  = 3'd0;
    localparam ST_AR    = 3'd1;
    localparam ST_R     = 3'd2;
    localparam ST_W     = 3'd3;
    localparam ST_B     = 3'd4;

    reg [2:0] state;
    reg [31:0] bytes_left;

    assign m_axi_awlen   = 8'd0;
    assign m_axi_awsize  = SIZE_CODE[2:0];
    assign m_axi_awburst = 2'b01; // INCR
    assign m_axi_wstrb   = {DATA_WIDTH/8{1'b1}};
    assign m_axi_wlast   = 1'b1;

    assign m_axi_arlen   = 8'd0;
    assign m_axi_arsize  = SIZE_CODE[2:0];
    assign m_axi_arburst = 2'b01; // INCR

    always @(posedge clk) begin
        if (rst) begin
            state         <= ST_IDLE;
            busy          <= 1'b0;
            done          <= 1'b0;
            error         <= 1'b0;
            bytes_left    <= 32'd0;
            m_axi_awaddr  <= {ADDR_WIDTH{1'b0}};
            m_axi_awvalid <= 1'b0;
            m_axi_wdata   <= {DATA_WIDTH{1'b0}};
            m_axi_wvalid  <= 1'b0;
            m_axi_bready  <= 1'b0;
            m_axi_araddr  <= {ADDR_WIDTH{1'b0}};
            m_axi_arvalid <= 1'b0;
            m_axi_rready  <= 1'b0;
        end else begin
            done <= 1'b0;

            case (state)
                ST_IDLE: begin
                    busy          <= 1'b0;
                    m_axi_awvalid <= 1'b0;
                    m_axi_wvalid  <= 1'b0;
                    m_axi_bready  <= 1'b0;
                    m_axi_arvalid <= 1'b0;
                    m_axi_rready  <= 1'b0;

                    if (start) begin
                        error <= 1'b0;
                        if ((byte_count == 0) ||
                            (byte_count % BYTES_PER_BEAT != 0) ||
                            (src_addr % BYTES_PER_BEAT != 0) ||
                            (dst_addr % BYTES_PER_BEAT != 0)) begin
                            error <= (byte_count != 0);
                            done  <= 1'b1;
                        end else begin
                            busy          <= 1'b1;
                            bytes_left    <= byte_count;
                            m_axi_araddr  <= src_addr;
                            m_axi_awaddr  <= dst_addr;
                            m_axi_arvalid <= 1'b1;
                            state         <= ST_AR;
                        end
                    end
                end

                ST_AR: begin
                    if (m_axi_arvalid && m_axi_arready) begin
                        m_axi_arvalid <= 1'b0;
                        m_axi_rready  <= 1'b1;
                        state         <= ST_R;
                    end
                end

                ST_R: begin
                    if (m_axi_rvalid && m_axi_rready) begin
                        m_axi_rready <= 1'b0;
                        m_axi_wdata  <= ~m_axi_rdata;
                        if ((m_axi_rresp != 2'b00) || !m_axi_rlast)
                            error <= 1'b1;
                        m_axi_awvalid <= 1'b1;
                        m_axi_wvalid  <= 1'b1;
                        state         <= ST_W;
                    end
                end

                ST_W: begin
                    if (m_axi_awvalid && m_axi_awready)
                        m_axi_awvalid <= 1'b0;
                    if (m_axi_wvalid && m_axi_wready)
                        m_axi_wvalid <= 1'b0;

                    // Each channel may complete on a different cycle.
                    if ((!m_axi_awvalid || m_axi_awready) &&
                        (!m_axi_wvalid  || m_axi_wready)) begin
                        m_axi_bready <= 1'b1;
                        state        <= ST_B;
                    end
                end

                ST_B: begin
                    if (m_axi_bvalid && m_axi_bready) begin
                        m_axi_bready <= 1'b0;
                        if (m_axi_bresp != 2'b00)
                            error <= 1'b1;

                        if (bytes_left <= BYTES_PER_BEAT) begin
                            bytes_left <= 32'd0;
                            busy       <= 1'b0;
                            done       <= 1'b1;
                            state      <= ST_IDLE;
                        end else begin
                            bytes_left    <= bytes_left - BYTES_PER_BEAT;
                            m_axi_araddr  <= m_axi_araddr + BYTES_PER_BEAT;
                            m_axi_awaddr  <= m_axi_awaddr + BYTES_PER_BEAT;
                            m_axi_arvalid <= 1'b1;
                            state         <= ST_AR;
                        end
                    end
                end

                default: state <= ST_IDLE;
            endcase
        end
    end

endmodule

