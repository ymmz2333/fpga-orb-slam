`timescale 1ns/1ps

// Complete fast-layer PL integration.  Unlike the earlier milestone harnesses,
// this process never reloads candidates or descriptors from a stage file:
// FAST, generated HLS RTL, and the AXI Hamming controller communicate through
// one shared DDR byte array and are sequenced only through control registers.
module orb_multi_ip_native_batch;
    localparam integer FRAME_COUNT = 14;
    localparam integer WIDTH = 320;
    localparam integer HEIGHT = 180;
    localparam integer FRAME_PIXELS = WIDTH * HEIGHT;
    localparam integer TOTAL_IMAGE_BYTES = FRAME_COUNT * FRAME_PIXELS;
    localparam integer MAX_CANDIDATES = 8192;
    localparam integer CANDIDATE_STRIDE = 32'h0001_1000;
    localparam integer OUTPUT_STRIDE = 32'h0000_6000;
    localparam integer RESULT_STRIDE = 512 * 8;
    localparam integer PAIR_COUNT = FRAME_COUNT * (FRAME_COUNT - 1);
    localparam [31:0] IMAGE_BASE = 32'h0010_0000;
    localparam [31:0] CANDIDATE_BASE = 32'h0020_0000;
    localparam [31:0] OUTPUT_BASE = 32'h0040_0000;
    localparam [31:0] RESULT_BASE = 32'h0080_0000;
    localparam integer MEMORY_BYTES = 16 * 1024 * 1024;

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    always #5 clk = ~clk;
    reg [31:0] source_lfsr = 32'hc001_d00d;
    always @(posedge clk)
        if (rst_n)
            source_lfsr <= {source_lfsr[30:0],
                source_lfsr[31] ^ source_lfsr[21] ^ source_lfsr[1] ^ source_lfsr[0]};

    // ------------------------------------------------------------------
    // DMA-like source/sink around the complete FAST front end.
    // ------------------------------------------------------------------
    reg frontend_phase = 1'b0;
    integer front_frame = 0;
    integer front_pixel = 0;
    integer front_word = 0;
    integer frontend_cycles = 0;
    reg frontend_complete = 1'b0;
    reg [31:0] candidate_counts [0:FRAME_COUNT-1];

    wire [31:0] direct_raddr = IMAGE_BASE + front_frame * FRAME_PIXELS + front_pixel;
    wire [7:0] direct_rdata;
    // Hold VALID and DATA until accepted; stop exactly after rows*cols bytes.
    wire front_input_valid = frontend_phase && (front_pixel < FRAME_PIXELS);
    wire front_input_ready;
    wire front_input_last = (front_pixel == FRAME_PIXELS - 1);
    wire [63:0] front_output_data;
    wire [7:0] front_output_keep;
    wire front_output_valid;
    wire front_output_ready = frontend_phase && source_lfsr[2];
    wire front_output_last;
    wire front_packet_done;
    wire [31:0] front_count;
    wire front_overflow;
    wire front_frame_error;
    wire front_output_fire = front_output_valid && front_output_ready;
    wire direct_we = front_output_fire;
    wire [31:0] direct_waddr = CANDIDATE_BASE +
        front_frame * CANDIDATE_STRIDE + front_word * 8;

    orb_feature_frontend #(
        .WIDTH(WIDTH), .HEIGHT(HEIGHT), .THRESHOLD(20),
        .MAX_CANDIDATES(MAX_CANDIDATES)
    ) frontend_i (
        .aclk(clk), .aresetn(rst_n),
        .s_axis_tdata(direct_rdata),
        .s_axis_tvalid(front_input_valid),
        .s_axis_tready(front_input_ready),
        .s_axis_tlast(front_input_last),
        .m_axis_tdata(front_output_data),
        .m_axis_tkeep(front_output_keep),
        .m_axis_tvalid(front_output_valid),
        .m_axis_tready(front_output_ready),
        .m_axis_tlast(front_output_last),
        .packet_done(front_packet_done),
        .candidate_count(front_count),
        .overflow(front_overflow),
        .frame_error(front_frame_error)
    );

    always @(posedge clk) begin
        if (!rst_n) begin
            front_frame <= 0;
            front_pixel <= 0;
            front_word <= 0;
            frontend_complete <= 1'b0;
            frontend_cycles <= 0;
        end else if (frontend_phase) begin
            frontend_cycles <= frontend_cycles + 1;
            if (front_input_valid && front_input_ready)
                front_pixel <= front_pixel + 1;
            if (front_output_fire) begin
                if (front_output_keep != 8'hff)
                    $fatal(1, "candidate packet has invalid TKEEP");
                if (front_output_last) begin
                    if (front_output_data[63:48] != 16'hffff)
                        $fatal(1, "candidate terminal marker is corrupt");
                    if (front_output_data[47:40] != 0)
                        $fatal(1, "candidate terminal reports status %x",
                               front_output_data[47:40]);
                    candidate_counts[front_frame] <= front_output_data[31:0];
                end
                front_word <= front_word + 1;
            end
            if (front_packet_done) begin
                $display("INTEGRATED_FAST frame=%0d candidates=%0d words=%0d",
                         front_frame + 1, candidate_counts[front_frame], front_word);
                if (front_frame == FRAME_COUNT - 1) begin
                    frontend_phase <= 1'b0;
                    frontend_complete <= 1'b1;
                end else begin
                    front_frame <= front_frame + 1;
                    front_pixel <= 0;
                    front_word <= 0;
                end
            end
        end
    end

    // ------------------------------------------------------------------
    // Generated HLS descriptor RTL and its AXI-Lite control port.
    // ------------------------------------------------------------------
    wire g0_arvalid, g0_arready, g0_rready;
    wire [31:0] g0_araddr;
    wire [7:0] g0_arlen;
    wire g0_rvalid, g0_rlast;
    wire [63:0] g0_rdata;
    wire g1_awvalid, g1_awready, g1_wvalid, g1_wready, g1_wlast;
    wire [31:0] g1_awaddr;
    wire [63:0] g1_wdata;
    wire [7:0] g1_awlen, g1_wstrb;
    wire g1_bvalid, g1_bready;

    reg hls_awvalid = 1'b0;
    wire hls_awready;
    reg [6:0] hls_awaddr = 0;
    reg hls_wvalid = 1'b0;
    wire hls_wready;
    reg [31:0] hls_wdata = 0;
    reg [3:0] hls_wstrb = 4'hf;
    wire hls_bvalid;
    reg hls_bready = 1'b0;
    reg hls_arvalid = 1'b0;
    wire hls_arready;
    reg [6:0] hls_araddr = 0;
    wire hls_rvalid;
    reg hls_rready = 1'b0;
    wire [31:0] hls_rdata;

    orb_list_descriptor_accel descriptor_i (
        .ap_clk(clk), .ap_rst_n(rst_n),
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
        .s_axi_control_AWVALID(hls_awvalid), .s_axi_control_AWREADY(hls_awready),
        .s_axi_control_AWADDR(hls_awaddr), .s_axi_control_WVALID(hls_wvalid),
        .s_axi_control_WREADY(hls_wready), .s_axi_control_WDATA(hls_wdata),
        .s_axi_control_WSTRB(hls_wstrb), .s_axi_control_BVALID(hls_bvalid),
        .s_axi_control_BREADY(hls_bready),
        .s_axi_control_ARVALID(hls_arvalid), .s_axi_control_ARREADY(hls_arready),
        .s_axi_control_ARADDR(hls_araddr), .s_axi_control_RVALID(hls_rvalid),
        .s_axi_control_RREADY(hls_rready), .s_axi_control_RDATA(hls_rdata)
    );

    task automatic hls_axil_write(input [6:0] address, input [31:0] value);
        integer guard;
        begin
            @(negedge clk); hls_awaddr = address; hls_awvalid = 1'b1;
            guard = 0;
            while (!hls_awready) begin
                @(negedge clk); guard = guard + 1;
                if (guard > 200) $fatal(1, "HLS AW timeout at %x", address);
            end
            @(posedge clk); @(negedge clk); hls_awvalid = 1'b0;
            hls_wdata = value; hls_wvalid = 1'b1;
            guard = 0;
            while (!hls_wready) begin
                @(negedge clk); guard = guard + 1;
                if (guard > 200) $fatal(1, "HLS W timeout at %x", address);
            end
            @(posedge clk); @(negedge clk); hls_wvalid = 1'b0; hls_bready = 1'b1;
            guard = 0;
            while (!hls_bvalid) begin
                @(negedge clk); guard = guard + 1;
                if (guard > 200) $fatal(1, "HLS B timeout at %x", address);
            end
            @(negedge clk); hls_bready = 1'b0;
        end
    endtask

    task automatic hls_axil_read(input [6:0] address, output [31:0] value);
        integer guard;
        begin
            @(negedge clk); hls_araddr = address; hls_arvalid = 1'b1;
            guard = 0;
            while (!hls_arready) begin
                @(negedge clk); guard = guard + 1;
                if (guard > 200) $fatal(1, "HLS AR timeout at %x", address);
            end
            @(negedge clk); hls_arvalid = 1'b0; hls_rready = 1'b1;
            guard = 0;
            while (!hls_rvalid) begin
                @(negedge clk); guard = guard + 1;
                if (guard > 200) $fatal(1, "HLS R timeout at %x", address);
            end
            value = hls_rdata;
            @(negedge clk); hls_rready = 1'b0;
        end
    endtask

    // ------------------------------------------------------------------
    // AXI Hamming controller.  Its read and write ports share the same DDR.
    // ------------------------------------------------------------------
    reg ham_awvalid = 1'b0;
    wire ham_awready;
    reg [6:0] ham_awaddr = 0;
    reg ham_wvalid = 1'b0;
    wire ham_wready;
    reg [31:0] ham_wdata = 0;
    wire ham_bvalid;
    reg ham_bready = 1'b0;
    reg ham_arvalid = 1'b0;
    wire ham_arready;
    reg [6:0] ham_araddr = 0;
    wire ham_rvalid;
    reg ham_rready = 1'b0;
    wire [31:0] ham_rdata;
    wire [31:0] ham_m_awaddr, ham_m_araddr;
    wire [7:0] ham_m_awlen, ham_m_arlen;
    wire ham_m_awvalid, ham_m_awready, ham_m_wvalid, ham_m_wready;
    wire [63:0] ham_m_wdata, ham_m_rdata;
    wire [7:0] ham_m_wstrb;
    wire ham_m_wlast, ham_m_bvalid, ham_m_bready;
    wire ham_m_arvalid, ham_m_arready, ham_m_rvalid, ham_m_rready, ham_m_rlast;

    orb_hamming_axi_controller hamming_i (
        .clk(clk), .rst(!rst_n),
        .s_axi_control_awaddr(ham_awaddr), .s_axi_control_awvalid(ham_awvalid),
        .s_axi_control_awready(ham_awready), .s_axi_control_wdata(ham_wdata),
        .s_axi_control_wstrb(4'hf), .s_axi_control_wvalid(ham_wvalid),
        .s_axi_control_wready(ham_wready), .s_axi_control_bvalid(ham_bvalid),
        .s_axi_control_bready(ham_bready),
        .s_axi_control_araddr(ham_araddr), .s_axi_control_arvalid(ham_arvalid),
        .s_axi_control_arready(ham_arready), .s_axi_control_rdata(ham_rdata),
        .s_axi_control_rvalid(ham_rvalid), .s_axi_control_rready(ham_rready),
        .m_axi_awaddr(ham_m_awaddr), .m_axi_awlen(ham_m_awlen),
        .m_axi_awvalid(ham_m_awvalid), .m_axi_awready(ham_m_awready),
        .m_axi_wdata(ham_m_wdata), .m_axi_wstrb(ham_m_wstrb),
        .m_axi_wlast(ham_m_wlast), .m_axi_wvalid(ham_m_wvalid),
        .m_axi_wready(ham_m_wready), .m_axi_bresp(2'b00),
        .m_axi_bvalid(ham_m_bvalid), .m_axi_bready(ham_m_bready),
        .m_axi_araddr(ham_m_araddr), .m_axi_arlen(ham_m_arlen),
        .m_axi_arvalid(ham_m_arvalid), .m_axi_arready(ham_m_arready),
        .m_axi_rdata(ham_m_rdata), .m_axi_rresp(2'b00),
        .m_axi_rlast(ham_m_rlast), .m_axi_rvalid(ham_m_rvalid),
        .m_axi_rready(ham_m_rready)
    );

    task automatic ham_axil_write(input [6:0] address, input [31:0] value);
        integer guard;
        reg accepted;
        begin
            @(negedge clk);
            ham_awaddr = address; ham_wdata = value;
            ham_awvalid = 1'b1; ham_wvalid = 1'b1;
            guard = 0; accepted = 1'b0;
            while (!accepted) begin
                @(posedge clk);
                accepted = ham_awready && ham_wready;
                guard = guard + 1;
                if (guard > 200) $fatal(1, "Hamming AXIL write timeout at %x", address);
            end
            @(negedge clk);
            ham_awvalid = 1'b0; ham_wvalid = 1'b0; ham_bready = 1'b1;
            guard = 0;
            while (!ham_bvalid) begin
                @(negedge clk); guard = guard + 1;
                if (guard > 200) $fatal(1, "Hamming AXIL B timeout at %x", address);
            end
            @(negedge clk); ham_bready = 1'b0;
        end
    endtask

    task automatic ham_axil_read(input [6:0] address, output [31:0] value);
        integer guard;
        reg accepted;
        begin
            @(negedge clk); ham_araddr = address; ham_arvalid = 1'b1;
            guard = 0; accepted = 1'b0;
            while (!accepted) begin
                @(posedge clk);
                accepted = ham_arready;
                guard = guard + 1;
                if (guard > 200) $fatal(1, "Hamming AXIL AR timeout at %x", address);
            end
            @(negedge clk);
            ham_arvalid = 1'b0; ham_rready = 1'b1;
            guard = 0;
            while (!ham_rvalid) begin
                @(negedge clk); guard = guard + 1;
                if (guard > 200) $fatal(1, "Hamming AXIL R timeout at %x", address);
            end
            value = ham_rdata;
            @(posedge clk); @(negedge clk); ham_rready = 1'b0;
        end
    endtask

    // ------------------------------------------------------------------
    // The single shared DDR model and its counters.
    // ------------------------------------------------------------------
    wire [63:0] stat_direct_write_bytes, stat_g0_read_bytes, stat_g0_read_bursts;
    wire [63:0] stat_g1_write_bytes, stat_g1_write_bursts;
    wire [63:0] stat_h_read_bytes, stat_h_read_bursts;
    wire [63:0] stat_h_write_bytes, stat_h_write_bursts, stat_stall_cycles;

    shared_axi_ddr_model #(.MEMORY_BYTES(MEMORY_BYTES)) ddr_i (
        .clk(clk), .rst_n(rst_n),
        .direct_raddr(direct_raddr), .direct_rdata(direct_rdata),
        .direct_we(direct_we), .direct_waddr(direct_waddr),
        .direct_wdata(front_output_data), .direct_wstrb(front_output_keep),
        .g0_arvalid(g0_arvalid), .g0_arready(g0_arready),
        .g0_araddr(g0_araddr), .g0_arlen(g0_arlen),
        .g0_rvalid(g0_rvalid), .g0_rready(g0_rready),
        .g0_rdata(g0_rdata), .g0_rlast(g0_rlast),
        .g1_awvalid(g1_awvalid), .g1_awready(g1_awready),
        .g1_awaddr(g1_awaddr), .g1_awlen(g1_awlen),
        .g1_wvalid(g1_wvalid), .g1_wready(g1_wready),
        .g1_wdata(g1_wdata), .g1_wstrb(g1_wstrb), .g1_wlast(g1_wlast),
        .g1_bvalid(g1_bvalid), .g1_bready(g1_bready),
        .h_arvalid(ham_m_arvalid), .h_arready(ham_m_arready),
        .h_araddr(ham_m_araddr), .h_arlen(ham_m_arlen),
        .h_rvalid(ham_m_rvalid), .h_rready(ham_m_rready),
        .h_rdata(ham_m_rdata), .h_rlast(ham_m_rlast),
        .h_awvalid(ham_m_awvalid), .h_awready(ham_m_awready),
        .h_awaddr(ham_m_awaddr), .h_awlen(ham_m_awlen),
        .h_wvalid(ham_m_wvalid), .h_wready(ham_m_wready),
        .h_wdata(ham_m_wdata), .h_wstrb(ham_m_wstrb), .h_wlast(ham_m_wlast),
        .h_bvalid(ham_m_bvalid), .h_bready(ham_m_bready),
        .direct_write_bytes(stat_direct_write_bytes),
        .g0_read_bytes(stat_g0_read_bytes), .g0_read_bursts(stat_g0_read_bursts),
        .g1_write_bytes(stat_g1_write_bytes), .g1_write_bursts(stat_g1_write_bursts),
        .h_read_bytes(stat_h_read_bytes), .h_read_bursts(stat_h_read_bursts),
        .h_write_bytes(stat_h_write_bytes), .h_write_bursts(stat_h_write_bursts),
        .stall_cycles(stat_stall_cycles)
    );

    // ------------------------------------------------------------------
    // PS-like stage scheduler, register polling, and diagnostic dumps.
    // ------------------------------------------------------------------
    reg [31:0] descriptor_counts [0:FRAME_COUNT-1];
    reg [7:0] candidate_dump [0:FRAME_COUNT*CANDIDATE_STRIDE-1];
    reg [7:0] descriptor_dump [0:FRAME_COUNT*OUTPUT_STRIDE-1];
    reg [63:0] result_dump [0:PAIR_COUNT*512-1];
    reg [63:0] stats_dump [0:15];
    integer init_index;
    integer frame;
    integer left;
    integer right;
    integer pair_index;
    integer result_index;
    integer elapsed;
    reg [63:0] hls_total_cycles = 0;
    reg [63:0] hamming_total_cycles = 0;
    integer max_fifo_water = 0;
    reg [31:0] status;
    reg [63:0] before_cycles;
    reg [63:0] global_cycles = 0;
    always @(posedge clk) begin
        if (rst_n) global_cycles <= global_cycles + 1;
        if (rst_n && hamming_i.fifo_count > max_fifo_water)
            max_fifo_water <= hamming_i.fifo_count;
    end

    task automatic run_hamming(input integer source_frame,
                               input integer target_frame,
                               input integer selected_pair);
        integer poll_elapsed;
        begin
            ham_axil_write(7'h08, OUTPUT_BASE + source_frame * OUTPUT_STRIDE + 8);
            ham_axil_write(7'h0c, OUTPUT_BASE + target_frame * OUTPUT_STRIDE + 8);
            ham_axil_write(7'h10, RESULT_BASE + selected_pair * RESULT_STRIDE);
            ham_axil_write(7'h14, descriptor_counts[source_frame]);
            ham_axil_write(7'h18, descriptor_counts[target_frame]);
            before_cycles = global_cycles;
            ham_axil_write(7'h00, 1);
            status = 0;
            poll_elapsed = 0;
            while (!status[1] && poll_elapsed < 5_000_000) begin
                repeat (2000) @(posedge clk);
                poll_elapsed = poll_elapsed + 2000;
                ham_axil_read(7'h04, status);
            end
            if (!status[1] || status[3:2] != 0)
                $fatal(1, "Hamming task %0d->%0d failed status=%x",
                       source_frame + 1, target_frame + 1, status);
            hamming_total_cycles = hamming_total_cycles + global_cycles - before_cycles;
            $display("INTEGRATED_HAMMING pair=%0d source=%0d target=%0d q=%0d t=%0d cycles=%0d",
                     selected_pair, source_frame + 1, target_frame + 1,
                     descriptor_counts[source_frame], descriptor_counts[target_frame],
                     global_cycles - before_cycles);
        end
    endtask

    initial begin
        $display("INTEGRATED_MULTI_IP_START");
        // Only initialized regions are touched; no stage data is loaded.
        for (init_index = CANDIDATE_BASE;
             init_index < CANDIDATE_BASE + FRAME_COUNT*CANDIDATE_STRIDE;
             init_index = init_index + 1)
            ddr_i.mem[init_index] = 0;
        for (init_index = OUTPUT_BASE;
             init_index < OUTPUT_BASE + FRAME_COUNT*OUTPUT_STRIDE;
             init_index = init_index + 1)
            ddr_i.mem[init_index] = 0;
        for (init_index = RESULT_BASE;
             init_index < RESULT_BASE + PAIR_COUNT*RESULT_STRIDE;
             init_index = init_index + 1)
            ddr_i.mem[init_index] = 0;
        $readmemh("panorama/build/native_multi_ip/images.hex", ddr_i.mem,
                  IMAGE_BASE, IMAGE_BASE + TOTAL_IMAGE_BYTES - 1);

        repeat (10) @(posedge clk);
        rst_n = 1'b1;
        repeat (5) @(posedge clk);
        frontend_phase = 1'b1;
        wait (frontend_complete);
        repeat (5) @(posedge clk);
        $display("INTEGRATED_FAST_COMPLETE cycles=%0d", frontend_cycles);

        for (frame = 0; frame < FRAME_COUNT; frame = frame + 1) begin
            hls_axil_write(7'h10, IMAGE_BASE + frame * FRAME_PIXELS);
            hls_axil_write(7'h18, CANDIDATE_BASE + frame * CANDIDATE_STRIDE);
            hls_axil_write(7'h20, OUTPUT_BASE + frame * OUTPUT_STRIDE);
            hls_axil_write(7'h28, HEIGHT);
            hls_axil_write(7'h30, WIDTH);
            hls_axil_write(7'h38, candidate_counts[frame]);
            hls_axil_write(7'h40, 512);
            before_cycles = global_cycles;
            hls_axil_write(7'h00, 1);
            status = 0;
            elapsed = 0;
            while (!status[1] && elapsed < 3_000_000) begin
                repeat (1000) @(posedge clk);
                elapsed = elapsed + 1000;
                hls_axil_read(7'h00, status);
            end
            if (!status[1])
                $fatal(1, "descriptor frame %0d timed out status=%x", frame + 1, status);
            hls_total_cycles = hls_total_cycles + global_cycles - before_cycles;
            descriptor_counts[frame] =
                ddr_i.mem[OUTPUT_BASE + frame*OUTPUT_STRIDE] |
                (ddr_i.mem[OUTPUT_BASE + frame*OUTPUT_STRIDE + 1] << 8) |
                (ddr_i.mem[OUTPUT_BASE + frame*OUTPUT_STRIDE + 2] << 16) |
                (ddr_i.mem[OUTPUT_BASE + frame*OUTPUT_STRIDE + 3] << 24);
            if (descriptor_counts[frame] > 512)
                $fatal(1, "descriptor count out of range on frame %0d", frame + 1);
            $display("INTEGRATED_HLS frame=%0d candidates=%0d descriptors=%0d cycles=%0d",
                     frame + 1, candidate_counts[frame], descriptor_counts[frame],
                     global_cycles - before_cycles);
        end

        pair_index = 0;
        for (left = 0; left < FRAME_COUNT; left = left + 1) begin
            for (right = left + 1; right < FRAME_COUNT; right = right + 1) begin
                run_hamming(left, right, pair_index);
                pair_index = pair_index + 1;
                run_hamming(right, left, pair_index);
                pair_index = pair_index + 1;
            end
        end
        if (pair_index != PAIR_COUNT)
            $fatal(1, "pair count mismatch");

        for (init_index = 0; init_index < FRAME_COUNT*CANDIDATE_STRIDE;
             init_index = init_index + 1)
            candidate_dump[init_index] = ddr_i.mem[CANDIDATE_BASE + init_index];
        for (init_index = 0; init_index < FRAME_COUNT*OUTPUT_STRIDE;
             init_index = init_index + 1)
            descriptor_dump[init_index] = ddr_i.mem[OUTPUT_BASE + init_index];
        for (result_index = 0; result_index < PAIR_COUNT*512;
             result_index = result_index + 1) begin
            result_dump[result_index] = {
                ddr_i.mem[RESULT_BASE + result_index*8 + 7],
                ddr_i.mem[RESULT_BASE + result_index*8 + 6],
                ddr_i.mem[RESULT_BASE + result_index*8 + 5],
                ddr_i.mem[RESULT_BASE + result_index*8 + 4],
                ddr_i.mem[RESULT_BASE + result_index*8 + 3],
                ddr_i.mem[RESULT_BASE + result_index*8 + 2],
                ddr_i.mem[RESULT_BASE + result_index*8 + 1],
                ddr_i.mem[RESULT_BASE + result_index*8]
            };
        end
        stats_dump[0] = stat_direct_write_bytes;
        stats_dump[1] = stat_g0_read_bytes;
        stats_dump[2] = stat_g0_read_bursts;
        stats_dump[3] = stat_g1_write_bytes;
        stats_dump[4] = stat_g1_write_bursts;
        stats_dump[5] = stat_h_read_bytes;
        stats_dump[6] = stat_h_read_bursts;
        stats_dump[7] = stat_h_write_bytes;
        stats_dump[8] = stat_h_write_bursts;
        stats_dump[9] = stat_stall_cycles;
        stats_dump[10] = frontend_cycles;
        stats_dump[11] = hls_total_cycles;
        stats_dump[12] = hamming_total_cycles;
        stats_dump[13] = max_fifo_water;
        stats_dump[14] = global_cycles;
        stats_dump[15] = 64'h4f52_425f_5041_5353;
        $writememh("panorama/build/native_multi_ip/candidate_counts.hex", candidate_counts);
        $writememh("panorama/build/native_multi_ip/candidates.hex", candidate_dump);
        $writememh("panorama/build/native_multi_ip/descriptor_counts.hex", descriptor_counts);
        $writememh("panorama/build/native_multi_ip/descriptors.hex", descriptor_dump);
        $writememh("panorama/build/native_multi_ip/results.hex", result_dump);
        $writememh("panorama/build/native_multi_ip/stats.hex", stats_dump);
        $display("INTEGRATED_MULTI_IP_COMPLETE total_cycles=%0d hls_cycles=%0d hamming_cycles=%0d",
                 global_cycles, hls_total_cycles, hamming_total_cycles);
        $finish;
    end

endmodule
