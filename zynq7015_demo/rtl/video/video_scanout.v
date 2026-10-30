`timescale 1ns/1ps
`default_nettype none
// One AXI reader, fixed bounded double-buffer aperture, frame-synchronous flush.
module video_scanout #(
    parameter integer H_ACTIVE=1280,H_FRONT=110,H_SYNC=40,H_BACK=220,
    parameter integer V_ACTIVE=720,V_FRONT=5,V_SYNC=5,V_BACK=20
)(
    (* X_INTERFACE_INFO="xilinx.com:signal:clock:1.0 aclk CLK", X_INTERFACE_PARAMETER="ASSOCIATED_BUSIF M_AXI:S_AXI, ASSOCIATED_RESET aresetn, FREQ_HZ 150000000" *)
    input wire aclk,
    (* X_INTERFACE_INFO="xilinx.com:signal:reset:1.0 aresetn RST", X_INTERFACE_PARAMETER="POLARITY ACTIVE_LOW" *)
    input wire aresetn,
    input wire pixel_clk,input wire pixel_reset,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWADDR", X_INTERFACE_PARAMETER="PROTOCOL AXI4LITE, DATA_WIDTH 32, ADDR_WIDTH 15" *)
    input wire [14:0] s_axi_awaddr,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWPROT" *) input wire [2:0] s_axi_awprot,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWVALID" *) input wire s_axi_awvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWREADY" *) output wire s_axi_awready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WDATA" *) input wire [31:0] s_axi_wdata,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WSTRB" *) input wire [3:0] s_axi_wstrb,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WVALID" *) input wire s_axi_wvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WREADY" *) output wire s_axi_wready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BRESP" *) output wire [1:0] s_axi_bresp,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BVALID" *) output reg s_axi_bvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BREADY" *) input wire s_axi_bready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARADDR" *) input wire [14:0] s_axi_araddr,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARPROT" *) input wire [2:0] s_axi_arprot,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARVALID" *) input wire s_axi_arvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARREADY" *) output wire s_axi_arready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RDATA" *) output reg [31:0] s_axi_rdata,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RRESP" *) output wire [1:0] s_axi_rresp,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RVALID" *) output reg s_axi_rvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RREADY" *) input wire s_axi_rready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARADDR", X_INTERFACE_PARAMETER="PROTOCOL AXI4, DATA_WIDTH 64, ADDR_WIDTH 32, READ_WRITE_MODE READ_ONLY, NUM_READ_OUTSTANDING 1, MAX_BURST_LENGTH 64" *)
    output reg [31:0] m_axi_araddr,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARLEN" *) output reg [7:0] m_axi_arlen,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARSIZE" *) output wire [2:0] m_axi_arsize,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARBURST" *) output wire [1:0] m_axi_arburst,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARLOCK" *) output wire m_axi_arlock,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARCACHE" *) output wire [3:0] m_axi_arcache,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARPROT" *) output wire [2:0] m_axi_arprot,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARQOS" *) output wire [3:0] m_axi_arqos,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARVALID" *) output reg m_axi_arvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI ARREADY" *) input wire m_axi_arready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI RDATA" *) input wire [63:0] m_axi_rdata,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI RRESP" *) input wire [1:0] m_axi_rresp,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI RLAST" *) input wire m_axi_rlast,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI RVALID" *) input wire m_axi_rvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 M_AXI RREADY" *) output wire m_axi_rready,
    output wire [23:0] rgb,output wire de,output wire hsync,output wire vsync
);
    localparam integer H_TOTAL=H_ACTIVE+H_FRONT+H_SYNC+H_BACK;
    localparam integer V_TOTAL=V_ACTIVE+V_FRONT+V_SYNC+V_BACK;
    localparam integer FRAME_WORDS=H_ACTIVE*V_ACTIVE/4;
    reg [11:0] x,y;
    reg request_toggle,underflow_toggle;
    reg [1:0] control;
    reg [31:0] pending_base,pending_ticket,active_base,active_ticket;
    reg [31:0] frame_count,underflow_count,error_count;
    reg aw_pending,w_pending;
    reg [14:0] write_addr;
    reg [31:0] write_data;
    reg [3:0] write_strobe;
    assign s_axi_awready=!aw_pending&&!s_axi_bvalid;
    assign s_axi_wready=!w_pending&&!s_axi_bvalid;
    assign s_axi_bresp=2'b00;
    assign s_axi_arready=!s_axi_rvalid;
    assign s_axi_rresp=2'b00;
    assign m_axi_arsize=3'd3;
    assign m_axi_arburst=2'b01;
    assign m_axi_arlock=1'b0;
    assign m_axi_arcache=4'b0011;
    assign m_axi_arprot=3'b000;
    assign m_axi_arqos=4'b0000;

    (* ASYNC_REG="TRUE" *) reg [1:0] req_sync,uf_sync;
    (* ASYNC_REG="TRUE" *) reg [1:0] en_sync,pattern_sync,ack_sync;
    reg req_seen,uf_seen,ack_toggle;
    reg [3:0] flush_count;
    reg [2:0] state;
    localparam WAIT_FRAME=0,DRAIN=1,FLUSH=2,WAIT_FIFO=3,STREAM=4;
    reg burst_active;
    reg [7:0] beats_left;
    reg [19:0] words_left;
    reg [31:0] next_address;
    wire frame_pending=req_sync[1]!=req_seen;
    wire discard=(state!=STREAM)||frame_pending;
    wire fifo_full,fifo_empty,wr_busy,rd_busy;
    wire [63:0] fifo_data;
    wire fifo_reset=!aresetn||(state==FLUSH);
    wire push=m_axi_rvalid&&m_axi_rready&&!discard;
    wire pop;
    assign m_axi_rready=burst_active&&(discard||(!fifo_full&&!wr_busy));
    xpm_fifo_async #(.FIFO_MEMORY_TYPE("block"),.FIFO_WRITE_DEPTH(1024),
        .WRITE_DATA_WIDTH(64),.READ_DATA_WIDTH(64),.READ_MODE("fwft"),.FIFO_READ_LATENCY(0),
        .WR_DATA_COUNT_WIDTH(11),.RD_DATA_COUNT_WIDTH(11),.CDC_SYNC_STAGES(2),
        .USE_ADV_FEATURES("0000")) pixels(
        .rst(fifo_reset),.wr_clk(aclk),.wr_en(push),.din(m_axi_rdata),.full(fifo_full),
        .wr_rst_busy(wr_busy),.rd_clk(pixel_clk),.rd_en(pop),.dout(fifo_data),
        .empty(fifo_empty),.rd_rst_busy(rd_busy),.sleep(1'b0),
        .injectsbiterr(1'b0),.injectdbiterr(1'b0),
        .prog_full(),.wr_data_count(),.overflow(),.almost_full(),.wr_ack(),
        .prog_empty(),.rd_data_count(),.underflow(),.almost_empty(),.data_valid(),.sbiterr(),.dbiterr());

    always @(posedge aclk)begin
        if(!aresetn)begin
            req_sync<=0;uf_sync<=0;req_seen<=0;uf_seen<=0;ack_toggle<=0;
            control<=2;pending_base<=32'h20b00000;pending_ticket<=0;
            active_base<=32'h20b00000;active_ticket<=0;
            frame_count<=0;underflow_count<=0;error_count<=0;
            aw_pending<=0;w_pending<=0;s_axi_bvalid<=0;s_axi_rvalid<=0;s_axi_rdata<=0;
            write_addr<=0;write_data<=0;write_strobe<=0;
            state<=WAIT_FRAME;flush_count<=0;burst_active<=0;beats_left<=0;
            words_left<=0;next_address<=0;m_axi_araddr<=0;m_axi_arlen<=0;m_axi_arvalid<=0;
        end else begin
            req_sync<={req_sync[0],request_toggle};uf_sync<={uf_sync[0],underflow_toggle};
            if(uf_sync[1]!=uf_seen)begin uf_seen<=uf_sync[1];underflow_count<=underflow_count+1;end
            if(s_axi_awvalid&&s_axi_awready)begin write_addr<=s_axi_awaddr;aw_pending<=1;end
            if(s_axi_wvalid&&s_axi_wready)begin write_data<=s_axi_wdata;write_strobe<=s_axi_wstrb;w_pending<=1;end
            if(s_axi_bvalid&&s_axi_bready)s_axi_bvalid<=0;
            if(aw_pending&&w_pending&&!s_axi_bvalid)begin
                aw_pending<=0;w_pending<=0;s_axi_bvalid<=1;
                case(write_addr[14:2])
                    0:if(write_strobe[0])control<=write_data[1:0];
                    1:if(write_strobe==4'hf&&((write_data==32'h20b00000)||(write_data==32'h20d00000)))pending_base<=write_data;
                    2:if(write_strobe==4'hf)pending_ticket<=write_data;
                    default:begin end
                endcase
            end
            if(s_axi_rvalid&&s_axi_rready)s_axi_rvalid<=0;
            if(s_axi_arvalid&&s_axi_arready)begin
                s_axi_rvalid<=1;
                case(s_axi_araddr[14:2])
                    0:s_axi_rdata<={30'b0,control};
                    1:s_axi_rdata<=pending_base;
                    2:s_axi_rdata<=pending_ticket;
                    4:s_axi_rdata<=active_base;
                    5:s_axi_rdata<=active_ticket;
                    6:s_axi_rdata<=frame_count;
                    7:s_axi_rdata<=underflow_count;
                    8:s_axi_rdata<=error_count;
                    9:s_axi_rdata<={27'b0,wr_busy,fifo_full,state};
                    10:s_axi_rdata<=32'h5a564431;
                    11:s_axi_rdata<={16'd1280,16'd720};
                    default:s_axi_rdata<=0;
                endcase
            end
            if(m_axi_arvalid&&m_axi_arready)begin
                m_axi_arvalid<=0;burst_active<=1;beats_left<=m_axi_arlen;
            end
            if(m_axi_rvalid&&m_axi_rready)begin
                if(m_axi_rresp!=0||m_axi_rlast!=(beats_left==0))error_count<=error_count+1;
                if(m_axi_rlast)burst_active<=0;
                else beats_left<=beats_left-1;
            end
            case(state)
                WAIT_FRAME:if(frame_pending)state<=DRAIN;
                STREAM:begin
                    if(frame_pending)state<=DRAIN;
                    else if(control[0]&&!control[1]&&words_left!=0&&!burst_active&&!m_axi_arvalid&&!wr_busy&&!fifo_full)begin
                        m_axi_araddr<=next_address;m_axi_arvalid<=1;
                        if(words_left>=64)begin
                            m_axi_arlen<=63;next_address<=next_address+512;words_left<=words_left-64;
                        end else begin
                            m_axi_arlen<=words_left[7:0]-1;next_address<=next_address+{9'b0,words_left,3'b000};words_left<=0;
                        end
                    end
                end
                DRAIN:if(!burst_active&&!m_axi_arvalid)begin
                    req_seen<=req_sync[1];active_base<=pending_base;active_ticket<=pending_ticket;
                    next_address<=pending_base;words_left<=FRAME_WORDS;
                    frame_count<=frame_count+1;flush_count<=15;state<=FLUSH;
                end
                FLUSH:if(flush_count==0)state<=WAIT_FIFO;else flush_count<=flush_count-1;
                WAIT_FIFO:if(!wr_busy)begin ack_toggle<=req_seen;state<=STREAM;end
                default:state<=WAIT_FRAME;
            endcase
        end
    end

    reg [63:0] held;
    reg [1:0] lane;
    reg have_word,bad_frame,frame_enabled,frame_pattern,frame_armed;
    wire visible=(x<H_ACTIVE)&&(y<V_ACTIVE);
    wire frame_ready=ack_sync[1]==request_toggle;
    wire use_dma=visible&&frame_enabled&&!frame_pattern&&frame_armed&&frame_ready&&!bad_frame&&!rd_busy;
    assign pop=use_dma&&!have_word&&!fifo_empty;
    wire [15:0] pixel=have_word?held[15:0]:(!fifo_empty?fifo_data[15:0]:16'b0);
    wire [23:0] expanded={pixel[15:11],pixel[15:13],pixel[10:5],pixel[10:9],pixel[4:0],pixel[4:2]};
    wire [2:0] bar=x/(H_ACTIVE/8);
    wire [23:0] pattern={{8{bar[2]}},{8{bar[1]}},{8{bar[0]}}};
    assign rgb=frame_pattern?pattern:(use_dma&&(have_word||!fifo_empty)?expanded:24'b0);
    assign de=visible;
    assign hsync=(x>=H_ACTIVE+H_FRONT)&&(x<H_ACTIVE+H_FRONT+H_SYNC);
    assign vsync=(y>=V_ACTIVE+V_FRONT)&&(y<V_ACTIVE+V_FRONT+V_SYNC);
    always @(posedge pixel_clk)begin
        if(pixel_reset)begin
            x<=0;y<=V_ACTIVE;request_toggle<=0;underflow_toggle<=0;
            en_sync<=0;pattern_sync<=3;ack_sync<=0;held<=0;lane<=0;have_word<=0;bad_frame<=0;
            frame_enabled<=0;frame_pattern<=1;frame_armed<=0;
        end else begin
            en_sync<={en_sync[0],control[0]};pattern_sync<={pattern_sync[0],control[1]};ack_sync<={ack_sync[0],ack_toggle};
            if(x==H_TOTAL-1)begin x<=0;if(y==V_TOTAL-1)y<=0;else y<=y+1;end else x<=x+1;
            if(x==0&&y==V_ACTIVE)begin
                frame_enabled<=en_sync[1];frame_pattern<=pattern_sync[1];
                have_word<=0;lane<=0;bad_frame<=0;
                // One outstanding frame request. A late ACK cannot alias a
                // newer frame after an even number of missed vertical blanks.
                if(frame_ready)begin request_toggle<=!request_toggle;frame_armed<=1;end
                else frame_armed<=0;
            end
            if(x==0&&y==0&&frame_enabled&&!frame_pattern&&(!frame_armed||!frame_ready||rd_busy))begin
                bad_frame<=1;underflow_toggle<=!underflow_toggle;
            end
            if(use_dma)begin
                if(have_word)begin held<=held>>16;if(lane==3)begin have_word<=0;lane<=0;end else lane<=lane+1;end
                else if(!fifo_empty)begin held<=fifo_data>>16;have_word<=1;lane<=1;end
                else begin bad_frame<=1;underflow_toggle<=!underflow_toggle;end
            end
        end
    end
endmodule
`default_nettype wire
