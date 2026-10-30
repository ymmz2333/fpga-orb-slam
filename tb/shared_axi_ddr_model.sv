`timescale 1ns/1ps

// Native-Verilator shared DDR model for the fast integration layer.  Three
// independently instrumented AXI ports and one direct DMA-emulation port all
// access the same byte array.  The LFSR deliberately inserts address, data,
// and response stalls so the integration test does not accidentally depend on
// a zero-latency memory.
module shared_axi_ddr_model #(
    parameter integer MEMORY_BYTES = 16 * 1024 * 1024
) (
    input  wire         clk,
    input  wire         rst_n,

    input  wire [31:0]  direct_raddr,
    output wire [7:0]   direct_rdata,
    input  wire         direct_we,
    input  wire [31:0]  direct_waddr,
    input  wire [63:0]  direct_wdata,
    input  wire [7:0]   direct_wstrb,

    input  wire         g0_arvalid,
    output wire         g0_arready,
    input  wire [63:0]  g0_araddr,
    input  wire [7:0]   g0_arlen,
    output reg          g0_rvalid,
    input  wire         g0_rready,
    output reg  [63:0]  g0_rdata,
    output reg          g0_rlast,

    input  wire         g1_awvalid,
    output wire         g1_awready,
    input  wire [63:0]  g1_awaddr,
    input  wire [7:0]   g1_awlen,
    input  wire         g1_wvalid,
    output wire         g1_wready,
    input  wire [63:0]  g1_wdata,
    input  wire [7:0]   g1_wstrb,
    input  wire         g1_wlast,
    output reg          g1_bvalid,
    input  wire         g1_bready,

    input  wire         h_arvalid,
    output wire         h_arready,
    input  wire [31:0]  h_araddr,
    input  wire [7:0]   h_arlen,
    output reg          h_rvalid,
    input  wire         h_rready,
    output reg  [63:0]  h_rdata,
    output reg          h_rlast,
    input  wire         h_awvalid,
    output wire         h_awready,
    input  wire [31:0]  h_awaddr,
    input  wire [7:0]   h_awlen,
    input  wire         h_wvalid,
    output wire         h_wready,
    input  wire [63:0]  h_wdata,
    input  wire [7:0]   h_wstrb,
    input  wire         h_wlast,
    output reg          h_bvalid,
    input  wire         h_bready,

    output reg  [63:0]  direct_write_bytes,
    output reg  [63:0]  g0_read_bytes,
    output reg  [63:0]  g0_read_bursts,
    output reg  [63:0]  g1_write_bytes,
    output reg  [63:0]  g1_write_bursts,
    output reg  [63:0]  h_read_bytes,
    output reg  [63:0]  h_read_bursts,
    output reg  [63:0]  h_write_bytes,
    output reg  [63:0]  h_write_bursts,
    output reg  [63:0]  stall_cycles
);

    reg [7:0] mem [0:MEMORY_BYTES-1];
    reg [31:0] lfsr;
    integer lane;

    assign direct_rdata = mem[direct_raddr];

    reg g0_active;
    reg [31:0] g0_address;
    reg [7:0] g0_beats_left;
    assign g0_arready = !g0_active && !g0_rvalid && lfsr[0];

    reg g1_active;
    reg [31:0] g1_address;
    reg [7:0] g1_beats_left;
    assign g1_awready = !g1_active && !g1_bvalid && lfsr[2];
    assign g1_wready = g1_active && lfsr[3];

    reg h_read_active;
    reg [31:0] h_read_address;
    reg [7:0] h_read_beats_left;
    assign h_arready = !h_read_active && !h_rvalid && lfsr[4];

    reg h_write_active;
    reg [31:0] h_write_address;
    reg [7:0] h_write_beats_left;
    assign h_awready = !h_write_active && !h_bvalid && lfsr[6];
    assign h_wready = h_write_active && lfsr[7];

    always @(posedge clk) begin
        if (!rst_n) begin
            lfsr <= 32'h51a7_d3c9;
            g0_active <= 1'b0;
            g0_rvalid <= 1'b0;
            g0_rlast <= 1'b0;
            g1_active <= 1'b0;
            g1_bvalid <= 1'b0;
            h_read_active <= 1'b0;
            h_rvalid <= 1'b0;
            h_rlast <= 1'b0;
            h_write_active <= 1'b0;
            h_bvalid <= 1'b0;
            direct_write_bytes <= 0;
            g0_read_bytes <= 0;
            g0_read_bursts <= 0;
            g1_write_bytes <= 0;
            g1_write_bursts <= 0;
            h_read_bytes <= 0;
            h_read_bursts <= 0;
            h_write_bytes <= 0;
            h_write_bursts <= 0;
            stall_cycles <= 0;
        end else begin
            lfsr <= {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};

            if ((g0_arvalid && !g0_arready) ||
                (g0_rvalid && !g0_rready) ||
                (g1_awvalid && !g1_awready) ||
                (g1_wvalid && !g1_wready) ||
                (h_arvalid && !h_arready) ||
                (h_rvalid && !h_rready) ||
                (h_awvalid && !h_awready) ||
                (h_wvalid && !h_wready))
                stall_cycles <= stall_cycles + 1'b1;

            if (direct_we) begin
                for (lane = 0; lane < 8; lane = lane + 1)
                    if (direct_wstrb[lane])
                        mem[direct_waddr + lane] <= direct_wdata[lane*8 +: 8];
                direct_write_bytes <= direct_write_bytes +
                    direct_wstrb[0] + direct_wstrb[1] + direct_wstrb[2] +
                    direct_wstrb[3] + direct_wstrb[4] + direct_wstrb[5] +
                    direct_wstrb[6] + direct_wstrb[7];
            end

            if (g0_arvalid && g0_arready) begin
                g0_active <= 1'b1;
                g0_address <= g0_araddr[31:0];
                g0_beats_left <= g0_arlen;
                g0_read_bursts <= g0_read_bursts + 1'b1;
            end
            if (g0_rvalid && g0_rready) begin
                g0_read_bytes <= g0_read_bytes + 8;
                g0_rvalid <= 1'b0;
                if (g0_rlast)
                    g0_active <= 1'b0;
                else begin
                    g0_address <= g0_address + 8;
                    g0_beats_left <= g0_beats_left - 1'b1;
                end
            end else if (g0_active && !g0_rvalid && lfsr[1]) begin
                for (lane = 0; lane < 8; lane = lane + 1)
                    g0_rdata[lane*8 +: 8] <= mem[g0_address + lane];
                g0_rlast <= (g0_beats_left == 0);
                g0_rvalid <= 1'b1;
            end

            if (g1_awvalid && g1_awready) begin
                g1_active <= 1'b1;
                g1_address <= g1_awaddr[31:0];
                g1_beats_left <= g1_awlen;
                g1_write_bursts <= g1_write_bursts + 1'b1;
            end
            if (g1_wvalid && g1_wready) begin
                for (lane = 0; lane < 8; lane = lane + 1)
                    if (g1_wstrb[lane])
                        mem[g1_address + lane] <= g1_wdata[lane*8 +: 8];
                g1_write_bytes <= g1_write_bytes + 8;
                g1_address <= g1_address + 8;
                g1_beats_left <= g1_beats_left - 1'b1;
                if (g1_wlast) begin
                    g1_active <= 1'b0;
                    g1_bvalid <= 1'b1;
                end
            end
            if (g1_bvalid && g1_bready)
                g1_bvalid <= 1'b0;

            if (h_arvalid && h_arready) begin
                h_read_active <= 1'b1;
                h_read_address <= h_araddr;
                h_read_beats_left <= h_arlen;
                h_read_bursts <= h_read_bursts + 1'b1;
            end
            if (h_rvalid && h_rready) begin
                h_read_bytes <= h_read_bytes + 8;
                h_rvalid <= 1'b0;
                if (h_rlast)
                    h_read_active <= 1'b0;
                else begin
                    h_read_address <= h_read_address + 8;
                    h_read_beats_left <= h_read_beats_left - 1'b1;
                end
            end else if (h_read_active && !h_rvalid && lfsr[5]) begin
                for (lane = 0; lane < 8; lane = lane + 1)
                    h_rdata[lane*8 +: 8] <= mem[h_read_address + lane];
                h_rlast <= (h_read_beats_left == 0);
                h_rvalid <= 1'b1;
            end

            if (h_awvalid && h_awready) begin
                h_write_active <= 1'b1;
                h_write_address <= h_awaddr;
                h_write_beats_left <= h_awlen;
                h_write_bursts <= h_write_bursts + 1'b1;
            end
            if (h_wvalid && h_wready) begin
                for (lane = 0; lane < 8; lane = lane + 1)
                    if (h_wstrb[lane])
                        mem[h_write_address + lane] <= h_wdata[lane*8 +: 8];
                h_write_bytes <= h_write_bytes + 8;
                h_write_address <= h_write_address + 8;
                h_write_beats_left <= h_write_beats_left - 1'b1;
                if (h_wlast) begin
                    h_write_active <= 1'b0;
                    h_bvalid <= 1'b1;
                end
            end
            if (h_bvalid && h_bready)
                h_bvalid <= 1'b0;
        end
    end

endmodule
