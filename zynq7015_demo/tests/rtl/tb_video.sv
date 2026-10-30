`timescale 1ns/1ps
module tb_video #(parameter integer H=16,V=4);
    reg aclk=0,pixel_clk=0,aresetn=0,pixel_reset=1;
    always #3.333 aclk=~aclk;
    always #6.734 pixel_clk=~pixel_clk;
    reg [14:0] s_axi_awaddr=0,s_axi_araddr=0;
    reg [2:0] s_axi_awprot=0,s_axi_arprot=0;
    reg s_axi_awvalid=0,s_axi_wvalid=0,s_axi_bready=0,s_axi_arvalid=0,s_axi_rready=0;
    reg [31:0] s_axi_wdata=0;
    reg [3:0] s_axi_wstrb=15;
    wire s_axi_awready,s_axi_wready,s_axi_bvalid,s_axi_arready,s_axi_rvalid;
    wire [31:0] s_axi_rdata;
    wire [1:0] s_axi_bresp,s_axi_rresp;
    wire [31:0] m_axi_araddr;
    wire [7:0] m_axi_arlen;
    wire [2:0] m_axi_arsize,m_axi_arprot;
    wire [1:0] m_axi_arburst;
    wire m_axi_arlock,m_axi_arvalid,m_axi_rready;
    wire [3:0] m_axi_arcache,m_axi_arqos;
    reg m_axi_arready=0,m_axi_rvalid=0,m_axi_rlast=0;
    reg [63:0] m_axi_rdata=0;
    reg [1:0] m_axi_rresp=0;
    wire [23:0] rgb;
    wire de,hsync,vsync;
    video_scanout #(.H_ACTIVE(H),.H_FRONT(2),.H_SYNC(2),.H_BACK(4),
        .V_ACTIVE(V),.V_FRONT(1),.V_SYNC(1),.V_BACK(2)) dut(.*);
    reg [15:0] rng=16'hc391;
    reg reading=0,stall_reads=0,inject_error=0;
    reg [31:0] address=0;
    reg [8:0] remaining=0;
    reg ar_stalled=0;
    reg [39:0] ar_hold;
    integer bursts=0,pixels_checked=0,good_frames=0;
    reg check_pixels=0;
    reg [15:0] expected_pixel;
    reg [23:0] expected_rgb;
    reg [31:0] value,before_count;
    function automatic [15:0] memory_pixel(input [31:0] addr);
        begin
            if(addr>=32'h20d00000&&addr<32'h20d00000+H*V*2)memory_pixel=16'h4000+((addr-32'h20d00000)>>1);
            else if(addr>=32'h20b00000&&addr<32'h20b00000+H*V*2)memory_pixel=16'h0100+((addr-32'h20b00000)>>1);
            else begin $fatal(1,"DMA read outside bounded buffers: %h",addr);memory_pixel=0;end
        end
    endfunction
    function automatic [63:0] memory_word(input [31:0] addr);
        memory_word={memory_pixel(addr+6),memory_pixel(addr+4),memory_pixel(addr+2),memory_pixel(addr)};
    endfunction
    always @(posedge aclk)begin
        if(!aresetn)begin
            reading<=0;m_axi_arready<=0;m_axi_rvalid<=0;ar_stalled<=0;
        end else begin
            rng<={rng[14:0],rng[15]^rng[13]^rng[12]^rng[10]};
            m_axi_arready<=!reading&&!m_axi_rvalid&&rng[0];
            if(ar_stalled&&(!m_axi_arvalid||{m_axi_araddr,m_axi_arlen}!==ar_hold))$fatal(1,"AR changed under backpressure");
            ar_stalled<=m_axi_arvalid&&!m_axi_arready;ar_hold<={m_axi_araddr,m_axi_arlen};
            if(m_axi_arvalid&&m_axi_arready)begin
                if(reading)$fatal(1,"More than one outstanding burst");
                if(m_axi_arsize!=3||m_axi_arburst!=1||m_axi_araddr[2:0]!=0||m_axi_arlen>63)$fatal(1,"Bad AXI metadata");
                if({1'b0,m_axi_araddr[11:0]}+(({5'b0,m_axi_arlen}+13'd1)<<3)>4096)$fatal(1,"Burst crosses 4KiB");
                reading<=1;address<=m_axi_araddr;remaining<={1'b0,m_axi_arlen}+1;bursts<=bursts+1;
                m_axi_arready<=0;
            end
            if(!m_axi_rvalid&&reading&&!stall_reads&&rng[2:1]!=0)begin
                m_axi_rvalid<=1;m_axi_rdata<=memory_word(address);m_axi_rlast<=remaining==1;
                m_axi_rresp<=inject_error?2'b10:0;
            end
            if(m_axi_rvalid&&m_axi_rready)begin
                m_axi_rvalid<=0;address<=address+8;remaining<=remaining-1;
                if(m_axi_rlast)reading<=0;
            end
        end
    end
    always @(negedge pixel_clk)begin
        if(!pixel_reset)begin
            if(hsync!==((dut.x>=H+2)&&(dut.x<H+4)))$fatal(1,"Hsync timing");
            if(vsync!==((dut.y>=V+1)&&(dut.y<V+2)))$fatal(1,"Vsync timing");
            if(de!==((dut.x<H)&&(dut.y<V)))$fatal(1,"Active window timing");
            if(check_pixels&&de&&dut.use_dma&&(dut.have_word||!dut.fifo_empty))begin
                expected_pixel=memory_pixel(dut.active_base+2*(dut.y*H+dut.x));
                expected_rgb={expected_pixel[15:11],expected_pixel[15:13],expected_pixel[10:5],expected_pixel[10:9],expected_pixel[4:0],expected_pixel[4:2]};
                if(rgb!==expected_rgb)$fatal(1,"Pixel order x=%0d y=%0d got=%h expected=%h",dut.x,dut.y,rgb,expected_rgb);
                pixels_checked=pixels_checked+1;
                if(dut.x==H-1&&dut.y==V-1)good_frames=good_frames+1;
            end
            if(dut.bad_frame&&de&&!dut.frame_pattern&&rgb!==0)$fatal(1,"Underrun frame must remain black");
        end
    end
    task automatic write_reg(input [14:0] addr,input [31:0] data,input bit wfirst);
        begin
            if(wfirst)begin
                @(negedge aclk);s_axi_wdata=data;s_axi_wvalid=1;
                do @(posedge aclk);while(!s_axi_wready);
                @(negedge aclk);s_axi_wvalid=0;repeat(3)@(negedge aclk);
            end
            @(negedge aclk);s_axi_awaddr=addr;s_axi_awvalid=1;
            do @(posedge aclk);while(!s_axi_awready);
            @(negedge aclk);s_axi_awvalid=0;
            if(!wfirst)begin
                repeat(2)@(negedge aclk);s_axi_wdata=data;s_axi_wvalid=1;
                do @(posedge aclk);while(!s_axi_wready);
                @(negedge aclk);s_axi_wvalid=0;
            end
            wait(s_axi_bvalid);repeat(3)@(negedge aclk);
            if(!s_axi_bvalid||s_axi_bresp!=0)$fatal(1,"Write response not held");
            s_axi_bready=1;@(negedge aclk);s_axi_bready=0;
        end
    endtask
    task automatic read_reg(input [14:0] addr,output [31:0] data);
        reg [31:0] hold_data;
        begin
            @(negedge aclk);s_axi_araddr=addr;s_axi_arvalid=1;
            do @(posedge aclk);while(!s_axi_arready);
            @(negedge aclk);s_axi_arvalid=0;
            wait(s_axi_rvalid);hold_data=s_axi_rdata;
            repeat(3)begin @(negedge aclk);if(!s_axi_rvalid||s_axi_rdata!==hold_data)$fatal(1,"Read response not held");end
            data=hold_data;s_axi_rready=1;@(negedge aclk);s_axi_rready=0;
        end
    endtask
    initial begin
        repeat(12)@(negedge aclk);aresetn=1;
        repeat(6)@(negedge pixel_clk);pixel_reset=0;
        read_reg(40,value);if(value!=32'h5a564431)$fatal(1,"Video ABI ID");
        write_reg(4,32'h20b00000,1);write_reg(8,1,0);
        // Switch away from the startup pattern in the middle of an active
        // line, with DDR deliberately unavailable until the next blanking.
        wait(dut.x==H/2&&dut.y==V/2);stall_reads=1;write_reg(0,1,1);
        wait(dut.x==0&&dut.y==V);stall_reads=0;
        check_pixels=1;
        wait(good_frames>=3);
        read_reg(28,value);if(value!=0)$fatal(1,"Unexpected underrun in unstalled test");
        write_reg(4,32'h20d00000,0);write_reg(8,2,1);
        wait(dut.active_ticket==2);wait(good_frames>=6);
        write_reg(4,32'h20000000,1);read_reg(4,value);
        if(value!=32'h20d00000)$fatal(1,"Unsafe base accepted");
        stall_reads=1;
        repeat(H*V*3+700)@(negedge pixel_clk);stall_reads=0;
        wait(!dut.bad_frame&&dut.x==0&&dut.y==0&&dut.frame_ready);check_pixels=1;
        before_count=good_frames;wait(good_frames>=before_count+3);
        read_reg(28,value);if(value==0)$fatal(1,"Underrun was not recorded");
        read_reg(32,value);if(value!=0)$fatal(1,"Unexpected AXI error");
        inject_error=1;repeat((H+8)*(V+4)*2)@(negedge pixel_clk);inject_error=0;
        read_reg(32,value);if(value==0)$fatal(1,"AXI error was not recorded");
        if(pixels_checked<500||bursts<12)$fatal(1,"Insufficient checks");
        $display("TEST_PASS video AXI split AW/W, response stalls, bounded reads, double buffer, timing, pixels, underrun recovery and error reporting pixels=%0d bursts=%0d",pixels_checked,bursts);
        $finish;
    end
    initial begin #20000000;$fatal(1,"Video watchdog");end
endmodule

module tb_video_full;
    tb_video #(.H(128),.V(64)) test();
endmodule
