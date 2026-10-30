`timescale 1ns/1ps

module orb_list_descriptor_native_batch;
    localparam integer FRAME_COUNT = 14;
    localparam integer IMAGE_BYTES = 320 * 180;
    localparam integer TOTAL_IMAGE_BYTES = FRAME_COUNT * IMAGE_BYTES;
    localparam integer TOTAL_CANDIDATE_BYTES = 142104;
    localparam integer OUTPUT_STRIDE = 16'h6000;
    localparam integer TOTAL_OUTPUT_BYTES = FRAME_COUNT * OUTPUT_STRIDE;
    localparam [31:0] IMAGE_BASE = 32'h0010_0000;
    localparam [31:0] CANDIDATE_BASE = 32'h0030_0000;
    localparam [31:0] OUTPUT_BASE = 32'h0050_0000;

    reg ap_clk = 1'b0;
    reg ap_rst_n = 1'b0;
    always #5 ap_clk = ~ap_clk;

    reg [7:0] image_mem [0:TOTAL_IMAGE_BYTES-1];
    reg [7:0] candidate_mem [0:TOTAL_CANDIDATE_BYTES-1];
    reg [7:0] output_mem [0:TOTAL_OUTPUT_BYTES-1];
    reg [31:0] candidate_counts [0:FRAME_COUNT-1];
    reg [31:0] candidate_offsets [0:FRAME_COUNT-1];

    wire g0_arvalid;
    wire g0_arready;
    wire [31:0] g0_araddr;
    wire [7:0] g0_arlen;
    reg g0_rvalid = 1'b0;
    wire g0_rready;
    reg [63:0] g0_rdata = 64'b0;
    reg g0_rlast = 1'b0;

    wire g1_awvalid;
    wire g1_awready;
    wire [31:0] g1_awaddr;
    wire [7:0] g1_awlen;
    wire g1_wvalid;
    wire g1_wready;
    wire [63:0] g1_wdata;
    wire [7:0] g1_wstrb;
    wire g1_wlast;
    reg g1_bvalid = 1'b0;
    wire g1_bready;

    reg s_awvalid = 1'b0;
    wire s_awready;
    reg [6:0] s_awaddr = 7'b0;
    reg s_wvalid = 1'b0;
    wire s_wready;
    reg [31:0] s_wdata = 32'b0;
    reg [3:0] s_wstrb = 4'hf;
    reg s_bready = 1'b0;
    wire s_bvalid;
    reg s_arvalid = 1'b0;
    wire s_arready;
    reg [6:0] s_araddr = 7'b0;
    wire s_rvalid;
    reg s_rready = 1'b0;
    wire [31:0] s_rdata;

    orb_list_descriptor_accel dut (
        .ap_clk(ap_clk), .ap_rst_n(ap_rst_n),

        .m_axi_gmem0_AWREADY(1'b0), .m_axi_gmem0_WREADY(1'b0),
        .m_axi_gmem0_ARVALID(g0_arvalid), .m_axi_gmem0_ARREADY(g0_arready),
        .m_axi_gmem0_ARADDR(g0_araddr), .m_axi_gmem0_ARLEN(g0_arlen),
        .m_axi_gmem0_RVALID(g0_rvalid), .m_axi_gmem0_RREADY(g0_rready),
        .m_axi_gmem0_RDATA(g0_rdata), .m_axi_gmem0_RLAST(g0_rlast),
        .m_axi_gmem0_RID(1'b0), .m_axi_gmem0_RUSER(1'b0),
        .m_axi_gmem0_RRESP(2'b00), .m_axi_gmem0_BVALID(1'b0),
        .m_axi_gmem0_BRESP(2'b00), .m_axi_gmem0_BID(1'b0),
        .m_axi_gmem0_BUSER(1'b0),

        .m_axi_gmem1_AWVALID(g1_awvalid), .m_axi_gmem1_AWREADY(g1_awready),
        .m_axi_gmem1_AWADDR(g1_awaddr), .m_axi_gmem1_AWLEN(g1_awlen),
        .m_axi_gmem1_WVALID(g1_wvalid), .m_axi_gmem1_WREADY(g1_wready),
        .m_axi_gmem1_WDATA(g1_wdata), .m_axi_gmem1_WSTRB(g1_wstrb),
        .m_axi_gmem1_WLAST(g1_wlast), .m_axi_gmem1_ARREADY(1'b0),
        .m_axi_gmem1_RVALID(1'b0), .m_axi_gmem1_RDATA(64'b0),
        .m_axi_gmem1_RLAST(1'b0), .m_axi_gmem1_RID(1'b0),
        .m_axi_gmem1_RUSER(1'b0), .m_axi_gmem1_RRESP(2'b00),
        .m_axi_gmem1_BVALID(g1_bvalid), .m_axi_gmem1_BREADY(g1_bready),
        .m_axi_gmem1_BRESP(2'b00), .m_axi_gmem1_BID(1'b0),
        .m_axi_gmem1_BUSER(1'b0),

        .s_axi_control_AWVALID(s_awvalid), .s_axi_control_AWREADY(s_awready),
        .s_axi_control_AWADDR(s_awaddr), .s_axi_control_WVALID(s_wvalid),
        .s_axi_control_WREADY(s_wready), .s_axi_control_WDATA(s_wdata),
        .s_axi_control_WSTRB(s_wstrb), .s_axi_control_BVALID(s_bvalid),
        .s_axi_control_BREADY(s_bready),
        .s_axi_control_ARVALID(s_arvalid), .s_axi_control_ARREADY(s_arready),
        .s_axi_control_ARADDR(s_araddr), .s_axi_control_RVALID(s_rvalid),
        .s_axi_control_RREADY(s_rready), .s_axi_control_RDATA(s_rdata)
    );

    function automatic [7:0] read_input_byte(input [31:0] address);
        integer index;
        begin
            if (address >= IMAGE_BASE && address < IMAGE_BASE + TOTAL_IMAGE_BYTES) begin
                index = address - IMAGE_BASE;
                read_input_byte = image_mem[index];
            end else if (address >= CANDIDATE_BASE &&
                         address < CANDIDATE_BASE + TOTAL_CANDIDATE_BYTES) begin
                index = address - CANDIDATE_BASE;
                read_input_byte = candidate_mem[index];
            end else begin
                read_input_byte = 8'b0;
            end
        end
    endfunction

    reg g0_active = 1'b0;
    reg [31:0] g0_address = 32'b0;
    reg [7:0] g0_beats_left = 8'b0;
    integer read_lane;
    integer g0_ar_transactions = 0;
    integer g0_r_beats = 0;
    assign g0_arready = !g0_active;
    always @(posedge ap_clk) begin
        if (!ap_rst_n) begin
            g0_active <= 1'b0;
            g0_rvalid <= 1'b0;
            g0_rlast <= 1'b0;
        end else begin
            if (g0_arvalid && g0_arready) begin
                g0_active <= 1'b1;
                g0_address <= g0_araddr;
                g0_beats_left <= g0_arlen;
                g0_ar_transactions <= g0_ar_transactions + 1;
            end
            if (g0_rvalid && g0_rready) begin
                g0_r_beats <= g0_r_beats + 1;
                g0_rvalid <= 1'b0;
                if (g0_rlast) begin
                    g0_active <= 1'b0;
                end else begin
                    g0_address <= g0_address + 8;
                    g0_beats_left <= g0_beats_left - 1'b1;
                end
            end else if (g0_active && !g0_rvalid) begin
                for (read_lane = 0; read_lane < 8; read_lane = read_lane + 1)
                    g0_rdata[read_lane*8 +: 8] <= read_input_byte(g0_address + read_lane);
                g0_rlast <= (g0_beats_left == 0);
                g0_rvalid <= 1'b1;
            end
        end
    end

    reg g1_active = 1'b0;
    reg [31:0] g1_address = 32'b0;
    integer write_lane;
    integer output_index;
    assign g1_awready = !g1_active && !g1_bvalid;
    assign g1_wready = g1_active;
    always @(posedge ap_clk) begin
        if (!ap_rst_n) begin
            g1_active <= 1'b0;
            g1_bvalid <= 1'b0;
        end else begin
            if (g1_awvalid && g1_awready) begin
                g1_active <= 1'b1;
                g1_address <= g1_awaddr;
            end
            if (g1_wvalid && g1_wready) begin
                for (write_lane = 0; write_lane < 8; write_lane = write_lane + 1) begin
                    output_index = g1_address + write_lane - OUTPUT_BASE;
                    if (g1_wstrb[write_lane] && output_index >= 0 &&
                        output_index < TOTAL_OUTPUT_BYTES)
                        output_mem[output_index] <= g1_wdata[write_lane*8 +: 8];
                end
                g1_address <= g1_address + 8;
                if (g1_wlast) begin
                    g1_active <= 1'b0;
                    g1_bvalid <= 1'b1;
                end
            end
            if (g1_bvalid && g1_bready)
                g1_bvalid <= 1'b0;
        end
    end

    task automatic axil_write(input [6:0] address, input [31:0] value);
        integer guard;
        begin
            @(negedge ap_clk);
            s_awaddr = address; s_awvalid = 1'b1;
            guard = 0;
            while (!s_awready) begin
                @(negedge ap_clk);
                guard = guard + 1;
                if (guard > 100) $fatal(1, "AXI-Lite write address timeout at %x", address);
            end
            @(posedge ap_clk);
            @(negedge ap_clk);
            s_awvalid = 1'b0;
            s_wdata = value; s_wvalid = 1'b1; s_wstrb = 4'hf;
            guard = 0;
            while (!s_wready) begin
                @(negedge ap_clk);
                guard = guard + 1;
                if (guard > 100) $fatal(1, "AXI-Lite write data timeout at %x", address);
            end
            @(posedge ap_clk);
            @(negedge ap_clk);
            s_wvalid = 1'b0;
            s_bready = 1'b1;
            guard = 0;
            while (!s_bvalid) begin
                @(negedge ap_clk);
                guard = guard + 1;
                if (guard > 100) $fatal(1, "AXI-Lite write response timeout at %x", address);
            end
            @(negedge ap_clk);
            s_bready = 1'b0;
        end
    endtask

    task automatic axil_read(input [6:0] address, output [31:0] value);
        integer guard;
        begin
            @(negedge ap_clk);
            s_araddr = address; s_arvalid = 1'b1;
            guard = 0;
            while (!s_arready) begin
                @(negedge ap_clk);
                guard = guard + 1;
                if (guard > 100) $fatal(1, "AXI-Lite read address timeout at %x", address);
            end
            @(negedge ap_clk);
            s_arvalid = 1'b0; s_rready = 1'b1;
            guard = 0;
            while (!s_rvalid) begin
                @(negedge ap_clk);
                guard = guard + 1;
                if (guard > 100) $fatal(1, "AXI-Lite read response timeout at %x", address);
            end
            value = s_rdata;
            @(negedge ap_clk);
            s_rready = 1'b0;
        end
    endtask

    integer frame;
    integer initialize_index;
    integer elapsed;
    reg [31:0] status;
    reg [31:0] image_pointer;
    reg [31:0] candidate_pointer;
    reg [31:0] output_pointer;
    initial begin
        $display("NATIVE_HLS_BATCH_START");
        $readmemh("panorama/build/native_hls_descriptor/images.hex", image_mem);
        $readmemh("panorama/build/native_hls_descriptor/candidates.hex", candidate_mem);
        $readmemh("panorama/build/native_hls_descriptor/counts.hex", candidate_counts);
        $readmemh("panorama/build/native_hls_descriptor/offsets.hex", candidate_offsets);
        for (initialize_index = 0; initialize_index < TOTAL_OUTPUT_BYTES;
             initialize_index = initialize_index + 1)
            output_mem[initialize_index] = 8'b0;

        repeat (10) @(posedge ap_clk);
        ap_rst_n = 1'b1;
        repeat (5) @(posedge ap_clk);
        for (frame = 0; frame < FRAME_COUNT; frame = frame + 1) begin
            $display("NATIVE_HLS_CONFIG frame=%0d", frame + 1);
            image_pointer = IMAGE_BASE + frame * IMAGE_BYTES;
            candidate_pointer = CANDIDATE_BASE + candidate_offsets[frame];
            output_pointer = OUTPUT_BASE + frame * OUTPUT_STRIDE;
            axil_write(7'h10, image_pointer);
            axil_write(7'h18, candidate_pointer);
            axil_write(7'h20, output_pointer);
            axil_write(7'h28, 180);
            axil_write(7'h30, 320);
            axil_write(7'h38, candidate_counts[frame]);
            axil_write(7'h40, 512);
            axil_write(7'h00, 1);
            $display("NATIVE_HLS_STARTED frame=%0d", frame + 1);
            status = 0;
            elapsed = 0;
            while (!status[1] && elapsed < 2_000_000) begin
                repeat (1000) @(posedge ap_clk);
                elapsed = elapsed + 1000;
                axil_read(7'h00, status);
            end
            if (!status[1]) begin
                $display("TIMEOUT status=%08x fsm=%x candidate_count=%0d select_done=%b select_ready=%b select_idle=%b ar_tx=%0d r_beats=%0d g0_arv=%b g0_arr=%b g0_rv=%b g0_rr=%b g0_active=%b g0_addr=%x g1_awv=%b g1_awr=%b g1_wv=%b g1_wr=%b g1_bv=%b g1_br=%b",
                         status, dut.ap_CS_fsm, dut.candidate_count,
                         dut.grp_orb_list_descriptor_accel_Pipeline_select_candidates_fu_353_ap_done,
                         dut.grp_orb_list_descriptor_accel_Pipeline_select_candidates_fu_353_ap_ready,
                         dut.grp_orb_list_descriptor_accel_Pipeline_select_candidates_fu_353_ap_idle,
                         g0_ar_transactions, g0_r_beats,
                         g0_arvalid, g0_arready, g0_rvalid, g0_rready,
                         g0_active, g0_address,
                         g1_awvalid, g1_awready, g1_wvalid, g1_wready,
                         g1_bvalid, g1_bready);
                $fatal(1, "frame %0d timeout", frame + 1);
            end
            $display("NATIVE_HLS_FRAME frame=%0d candidates=%0d cycles<=%0d",
                     frame + 1, candidate_counts[frame], elapsed);
        end
        $writememh("panorama/build/native_hls_descriptor/output.hex", output_mem);
        $display("NATIVE_HLS_BATCH_COMPLETE");
        $finish;
    end
endmodule
