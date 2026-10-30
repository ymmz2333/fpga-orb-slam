`timescale 1ns/1ps

// AXI memory controller around the retained 256-bit Hamming matcher.
//
// QUERY_BASE and TRAIN_BASE point at the first 40-byte descriptor record:
//   word 0: metadata, words 1..4: 256-bit descriptor, little-word first.
// One 64-bit best/second result is written for each query.
module orb_hamming_axi_controller #(
    parameter integer ADDR_WIDTH = 32,
    parameter integer DATA_WIDTH = 64,
    parameter integer MAX_QUERIES = 512,
    parameter integer MAX_TRAINS = 512,
    parameter integer FIFO_DEPTH = 16
) (
    input  wire                         clk,
    input  wire                         rst,

    input  wire [6:0]                   s_axi_control_awaddr,
    input  wire                         s_axi_control_awvalid,
    output wire                         s_axi_control_awready,
    input  wire [31:0]                  s_axi_control_wdata,
    input  wire [3:0]                   s_axi_control_wstrb,
    input  wire                         s_axi_control_wvalid,
    output wire                         s_axi_control_wready,
    output reg  [1:0]                   s_axi_control_bresp,
    output reg                          s_axi_control_bvalid,
    input  wire                         s_axi_control_bready,
    input  wire [6:0]                   s_axi_control_araddr,
    input  wire                         s_axi_control_arvalid,
    output wire                         s_axi_control_arready,
    output reg  [31:0]                  s_axi_control_rdata,
    output reg  [1:0]                   s_axi_control_rresp,
    output reg                          s_axi_control_rvalid,
    input  wire                         s_axi_control_rready,

    output reg  [ADDR_WIDTH-1:0]        m_axi_awaddr,
    output reg  [7:0]                   m_axi_awlen,
    output wire [2:0]                   m_axi_awsize,
    output wire [1:0]                   m_axi_awburst,
    output reg                          m_axi_awvalid,
    input  wire                         m_axi_awready,
    output reg  [DATA_WIDTH-1:0]        m_axi_wdata,
    output wire [DATA_WIDTH/8-1:0]      m_axi_wstrb,
    output wire                         m_axi_wlast,
    output reg                          m_axi_wvalid,
    input  wire                         m_axi_wready,
    input  wire [1:0]                   m_axi_bresp,
    input  wire                         m_axi_bvalid,
    output reg                          m_axi_bready,
    output reg  [ADDR_WIDTH-1:0]        m_axi_araddr,
    output reg  [7:0]                   m_axi_arlen,
    output wire [2:0]                   m_axi_arsize,
    output wire [1:0]                   m_axi_arburst,
    output reg                          m_axi_arvalid,
    input  wire                         m_axi_arready,
    input  wire [DATA_WIDTH-1:0]        m_axi_rdata,
    input  wire [1:0]                   m_axi_rresp,
    input  wire                         m_axi_rlast,
    input  wire                         m_axi_rvalid,
    output wire                         m_axi_rready,

    output wire                         interrupt
);

    localparam integer FIFO_PTR_WIDTH = $clog2(FIFO_DEPTH);
    localparam [4:0] IDLE = 5'd0;
    localparam [4:0] QUERY_PREP = 5'd1;
    localparam [4:0] QUERY_AR = 5'd2;
    localparam [4:0] QUERY_R = 5'd3;
    localparam [4:0] MATCH_START = 5'd4;
    localparam [4:0] TRAIN_PREP = 5'd5;
    localparam [4:0] TRAIN_AR = 5'd6;
    localparam [4:0] TRAIN_R = 5'd7;
    localparam [4:0] WAIT_MATCH = 5'd8;
    localparam [4:0] WRITE_START = 5'd9;
    localparam [4:0] WRITE_DATA = 5'd10;
    localparam [4:0] WRITE_RESP = 5'd11;

    reg [4:0] state;
    reg [31:0] query_base_reg;
    reg [31:0] train_base_reg;
    reg [31:0] result_base_reg;
    reg [31:0] query_count_reg;
    reg [31:0] train_count_reg;
    reg start_pulse;
    reg soft_reset_pulse;

    reg busy;
    reg done;
    reg axi_error;
    reg parameter_error;
    assign interrupt = done;
    wire [31:0] status_value = {
        28'd0, parameter_error, axi_error, done, busy
    };

    // A compact AXI-Lite slave.  AW and W may arrive on different cycles;
    // each VALID is held by a conforming master until both READYs assert.
    wire control_write = s_axi_control_awvalid && s_axi_control_wvalid &&
        !s_axi_control_bvalid;
    assign s_axi_control_awready = control_write;
    assign s_axi_control_wready = control_write;
    assign s_axi_control_arready = !s_axi_control_rvalid;

    integer byte_lane;
    reg [31:0] merged_write;
    always @* begin
        case (s_axi_control_awaddr[6:2])
            5'h02: merged_write = query_base_reg;
            5'h03: merged_write = train_base_reg;
            5'h04: merged_write = result_base_reg;
            5'h05: merged_write = query_count_reg;
            5'h06: merged_write = train_count_reg;
            default: merged_write = 0;
        endcase
        for (byte_lane = 0; byte_lane < 4; byte_lane = byte_lane + 1)
            if (s_axi_control_wstrb[byte_lane])
                merged_write[byte_lane*8 +: 8] =
                    s_axi_control_wdata[byte_lane*8 +: 8];
    end

    always @(posedge clk) begin
        if (rst) begin
            query_base_reg <= 0;
            train_base_reg <= 0;
            result_base_reg <= 0;
            query_count_reg <= 0;
            train_count_reg <= 0;
            start_pulse <= 1'b0;
            soft_reset_pulse <= 1'b0;
            s_axi_control_bresp <= 2'b00;
            s_axi_control_bvalid <= 1'b0;
            s_axi_control_rdata <= 0;
            s_axi_control_rresp <= 2'b00;
            s_axi_control_rvalid <= 1'b0;
        end else begin
            start_pulse <= 1'b0;
            soft_reset_pulse <= 1'b0;

            if (s_axi_control_bvalid && s_axi_control_bready)
                s_axi_control_bvalid <= 1'b0;
            if (control_write) begin
                s_axi_control_bresp <= 2'b00;
                s_axi_control_bvalid <= 1'b1;
                case (s_axi_control_awaddr[6:2])
                    5'h00: begin
                        start_pulse <= s_axi_control_wdata[0];
                        soft_reset_pulse <= s_axi_control_wdata[1];
                    end
                    5'h02: query_base_reg <= merged_write;
                    5'h03: train_base_reg <= merged_write;
                    5'h04: result_base_reg <= merged_write;
                    5'h05: query_count_reg <= merged_write;
                    5'h06: train_count_reg <= merged_write;
                    default: begin end
                endcase
            end

            if (s_axi_control_rvalid && s_axi_control_rready)
                s_axi_control_rvalid <= 1'b0;
            if (s_axi_control_arvalid && s_axi_control_arready) begin
                s_axi_control_rresp <= 2'b00;
                s_axi_control_rvalid <= 1'b1;
                case (s_axi_control_araddr[6:2])
                    5'h00: s_axi_control_rdata <= 0;
                    5'h01: s_axi_control_rdata <= status_value;
                    5'h02: s_axi_control_rdata <= query_base_reg;
                    5'h03: s_axi_control_rdata <= train_base_reg;
                    5'h04: s_axi_control_rdata <= result_base_reg;
                    5'h05: s_axi_control_rdata <= query_count_reg;
                    5'h06: s_axi_control_rdata <= train_count_reg;
                    default: s_axi_control_rdata <= 0;
                endcase
            end
        end
    end

    assign m_axi_awsize = 3'd3;
    assign m_axi_awburst = 2'b01;
    assign m_axi_wstrb = {DATA_WIDTH/8{1'b1}};
    assign m_axi_wlast = 1'b1;
    assign m_axi_arsize = 3'd3;
    assign m_axi_arburst = 2'b01;

    reg [31:0] query_index;
    reg [2:0] query_word;
    reg [255:0] query_descriptor;
    reg [31:0] train_words_left;
    reg [ADDR_WIDTH-1:0] train_address;
    reg [7:0] burst_beats_left;
    reg [2:0] record_phase;
    reg [255:0] descriptor_partial;
    reg [15:0] train_index;
    reg [63:0] result_word;

    reg [255:0] fifo_descriptor [0:FIFO_DEPTH-1];
    reg [15:0] fifo_index [0:FIFO_DEPTH-1];
    reg fifo_last [0:FIFO_DEPTH-1];
    reg [FIFO_PTR_WIDTH-1:0] fifo_write_ptr;
    reg [FIFO_PTR_WIDTH-1:0] fifo_read_ptr;
    reg [FIFO_PTR_WIDTH:0] fifo_count;

    wire h_q_ready;
    wire h_s_ready;
    wire h_match_valid;
    wire [15:0] h_best_index;
    wire [8:0] h_best_distance;
    wire [15:0] h_second_index;
    wire [8:0] h_second_distance;
    wire h_query_fire = (state == MATCH_START) && h_q_ready;
    wire h_stream_valid = (fifo_count != 0);
    wire h_stream_fire = h_stream_valid && h_s_ready;
    wire h_match_ready = (state == WAIT_MATCH);

    wire fifo_can_write = (fifo_count < FIFO_DEPTH) || h_stream_fire;
    assign m_axi_rready = (state == QUERY_R) ||
        ((state == TRAIN_R) && ((record_phase != 3'd4) || fifo_can_write));
    wire read_fire = m_axi_rvalid && m_axi_rready;
    wire fifo_write = (state == TRAIN_R) && read_fire &&
        (record_phase == 3'd4);

    orb_hamming_matcher matcher_i (
        .clk(clk),
        .rst(rst || soft_reset_pulse),
        .q_desc(query_descriptor),
        .q_valid(state == MATCH_START),
        .q_ready(h_q_ready),
        .s_desc(fifo_descriptor[fifo_read_ptr]),
        .s_index(fifo_index[fifo_read_ptr]),
        .s_last(fifo_last[fifo_read_ptr]),
        .s_valid(h_stream_valid),
        .s_ready(h_s_ready),
        .m_best_index(h_best_index),
        .m_best_distance(h_best_distance),
        .m_second_index(h_second_index),
        .m_second_distance(h_second_distance),
        .m_match_valid(h_match_valid),
        .m_match_ready(h_match_ready)
    );

    integer boundary_beats;
    integer selected_beats;
    always @(posedge clk) begin
        if (rst || soft_reset_pulse) begin
            state <= IDLE;
            busy <= 1'b0;
            done <= 1'b0;
            axi_error <= 1'b0;
            parameter_error <= 1'b0;
            m_axi_awaddr <= 0;
            m_axi_awlen <= 0;
            m_axi_awvalid <= 1'b0;
            m_axi_wdata <= 0;
            m_axi_wvalid <= 1'b0;
            m_axi_bready <= 1'b0;
            m_axi_araddr <= 0;
            m_axi_arlen <= 0;
            m_axi_arvalid <= 1'b0;
            query_index <= 0;
            query_word <= 0;
            query_descriptor <= 0;
            train_words_left <= 0;
            train_address <= 0;
            burst_beats_left <= 0;
            record_phase <= 0;
            descriptor_partial <= 0;
            train_index <= 0;
            result_word <= 0;
            fifo_write_ptr <= 0;
            fifo_read_ptr <= 0;
            fifo_count <= 0;
        end else begin
            if (h_stream_fire)
                fifo_read_ptr <= fifo_read_ptr + 1'b1;
            if (fifo_write) begin
                fifo_descriptor[fifo_write_ptr] <= {
                    m_axi_rdata, descriptor_partial[191:0]
                };
                fifo_index[fifo_write_ptr] <= train_index;
                fifo_last[fifo_write_ptr] <=
                    (train_index == train_count_reg - 1'b1);
                fifo_write_ptr <= fifo_write_ptr + 1'b1;
            end
            case ({fifo_write, h_stream_fire})
                2'b10: fifo_count <= fifo_count + 1'b1;
                2'b01: fifo_count <= fifo_count - 1'b1;
                default: begin end
            endcase

            if (start_pulse) begin
                if (busy) begin
                    parameter_error <= 1'b1;
                end else begin
                    done <= 1'b0;
                    axi_error <= 1'b0;
                    parameter_error <= 1'b0;
                    if ((query_count_reg > MAX_QUERIES) ||
                        (train_count_reg > MAX_TRAINS) ||
                        (|query_base_reg[2:0]) || (|train_base_reg[2:0]) ||
                        (|result_base_reg[2:0])) begin
                        done <= 1'b1;
                        parameter_error <= 1'b1;
                    end else if (query_count_reg == 0) begin
                        done <= 1'b1;
                    end else begin
                        busy <= 1'b1;
                        query_index <= 0;
                        query_word <= 0;
                        state <= QUERY_PREP;
                    end
                end
            end else begin
                case (state)
                    IDLE: begin
                        m_axi_arvalid <= 1'b0;
                        m_axi_awvalid <= 1'b0;
                        m_axi_wvalid <= 1'b0;
                        m_axi_bready <= 1'b0;
                    end

                    QUERY_PREP: begin
                        m_axi_araddr <= query_base_reg +
                            query_index * 32'd40 + 32'd8 +
                            query_word * 32'd8;
                        m_axi_arlen <= 0;
                        m_axi_arvalid <= 1'b1;
                        state <= QUERY_AR;
                    end

                    QUERY_AR: begin
                        if (m_axi_arvalid && m_axi_arready) begin
                            m_axi_arvalid <= 1'b0;
                            state <= QUERY_R;
                        end
                    end

                    QUERY_R: begin
                        if (read_fire) begin
                            if (m_axi_rresp != 2'b00 || !m_axi_rlast)
                                axi_error <= 1'b1;
                            query_descriptor[query_word*64 +: 64] <=
                                m_axi_rdata;
                            if (query_word == 3) begin
                                query_word <= 0;
                                state <= MATCH_START;
                            end else begin
                                query_word <= query_word + 1'b1;
                                state <= QUERY_PREP;
                            end
                        end
                    end

                    MATCH_START: begin
                        if (h_query_fire) begin
                            fifo_write_ptr <= 0;
                            fifo_read_ptr <= 0;
                            fifo_count <= 0;
                            record_phase <= 0;
                            descriptor_partial <= 0;
                            train_index <= 0;
                            if (train_count_reg == 0) begin
                                result_word <= {
                                    13'd0, 1'b0, 9'h1ff, 16'd0,
                                    9'h1ff, 16'd0
                                };
                                state <= WRITE_START;
                            end else begin
                                train_words_left <= train_count_reg * 32'd5;
                                train_address <= train_base_reg;
                                state <= TRAIN_PREP;
                            end
                        end
                    end

                    TRAIN_PREP: begin
                        boundary_beats = (4096 - train_address[11:0]) >> 3;
                        if (boundary_beats == 0)
                            boundary_beats = 512;
                        selected_beats = 16;
                        if (train_words_left < selected_beats)
                            selected_beats = train_words_left;
                        if (boundary_beats < selected_beats)
                            selected_beats = boundary_beats;
                        m_axi_araddr <= train_address;
                        m_axi_arlen <= selected_beats - 1;
                        burst_beats_left <= selected_beats;
                        m_axi_arvalid <= 1'b1;
                        state <= TRAIN_AR;
                    end

                    TRAIN_AR: begin
                        if (m_axi_arvalid && m_axi_arready) begin
                            m_axi_arvalid <= 1'b0;
                            state <= TRAIN_R;
                        end
                    end

                    TRAIN_R: begin
                        if (read_fire) begin
                            if (m_axi_rresp != 2'b00 ||
                                (m_axi_rlast != (burst_beats_left == 1)))
                                axi_error <= 1'b1;

                            case (record_phase)
                                3'd1: descriptor_partial[63:0] <= m_axi_rdata;
                                3'd2: descriptor_partial[127:64] <= m_axi_rdata;
                                3'd3: descriptor_partial[191:128] <= m_axi_rdata;
                                default: begin end
                            endcase
                            if (record_phase == 4) begin
                                record_phase <= 0;
                                train_index <= train_index + 1'b1;
                            end else begin
                                record_phase <= record_phase + 1'b1;
                            end

                            train_address <= train_address + 32'd8;
                            train_words_left <= train_words_left - 1'b1;
                            burst_beats_left <= burst_beats_left - 1'b1;
                            if (burst_beats_left == 1) begin
                                if (train_words_left == 1)
                                    state <= WAIT_MATCH;
                                else
                                    state <= TRAIN_PREP;
                            end
                        end
                    end

                    WAIT_MATCH: begin
                        if (h_match_valid) begin
                            result_word <= {
                                13'd0, 1'b1,
                                h_second_distance, h_second_index,
                                h_best_distance, h_best_index
                            };
                            state <= WRITE_START;
                        end
                    end

                    WRITE_START: begin
                        m_axi_awaddr <= result_base_reg + query_index * 32'd8;
                        m_axi_awlen <= 0;
                        m_axi_awvalid <= 1'b1;
                        m_axi_wdata <= result_word;
                        m_axi_wvalid <= 1'b1;
                        state <= WRITE_DATA;
                    end

                    WRITE_DATA: begin
                        if (m_axi_awvalid && m_axi_awready)
                            m_axi_awvalid <= 1'b0;
                        if (m_axi_wvalid && m_axi_wready)
                            m_axi_wvalid <= 1'b0;
                        if ((!m_axi_awvalid || m_axi_awready) &&
                            (!m_axi_wvalid || m_axi_wready)) begin
                            m_axi_bready <= 1'b1;
                            state <= WRITE_RESP;
                        end
                    end

                    WRITE_RESP: begin
                        if (m_axi_bvalid && m_axi_bready) begin
                            m_axi_bready <= 1'b0;
                            if (m_axi_bresp != 2'b00)
                                axi_error <= 1'b1;
                            if (query_index + 1 >= query_count_reg) begin
                                busy <= 1'b0;
                                done <= 1'b1;
                                state <= IDLE;
                            end else begin
                                query_index <= query_index + 1'b1;
                                query_word <= 0;
                                state <= QUERY_PREP;
                            end
                        end
                    end

                    default: state <= IDLE;
                endcase
            end
        end
    end

endmodule
