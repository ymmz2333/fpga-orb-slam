`timescale 1ns/1ps
module tb_serializer;
    reg pixel_clk=0,serial_clk=0,reset=1;
    reg [9:0] symbol=10'h2a5;
    wire out_p,out_n,clk_p,clk_n;
    always #10 pixel_clk=~pixel_clk;
    always #2 serial_clk=~serial_clk;
    tmds_serializer data_lane(.*);
    tmds_serializer clock_lane(.pixel_clk(pixel_clk),.serial_clk(serial_clk),.reset(reset),
        .symbol(10'b1111100000),.out_p(clk_p),.out_n(clk_n));
    integer phase,checked=0;
    reg previous_clock,aligned;
    task automatic check_word(input [9:0] value);
        integer n;
        begin
            @(negedge pixel_clk);symbol=value;
            repeat(5)@(posedge pixel_clk);
            previous_clock=clk_p;aligned=0;phase=0;
            for(n=0;n<160;n=n+1)begin
                @(serial_clk);#0.01;
                if(!clk_p&&previous_clock)begin aligned=1;phase=0;end
                if(aligned)begin
                    if(out_p!==value[phase])$fatal(1,"OSERDES bit order value=%h phase=%0d got=%b",value,phase,out_p);
                    if(out_n!==!out_p||clk_n!==!clk_p)$fatal(1,"Differential complement");
                    if(clk_p!==(phase>=5))$fatal(1,"Forwarded clock ratio/phase");
                    phase=(phase+1)%10;checked=checked+1;
                end
                previous_clock=clk_p;
            end
        end
    endtask
    initial begin
        // UNISIM glbl asserts its startup GSR for the first 100ns.
        #250;@(negedge pixel_clk);reset=0;
        repeat(8)@(posedge pixel_clk);
        check_word(10'h2a5);check_word(10'h172);check_word(10'h001);check_word(10'h200);
        if(checked<500)$fatal(1,"Insufficient serialization checks");
        $display("TEST_PASS UNISIM OSERDESE2 master/slave 10:1 LSB order, 5x DDR clock and differential lanes bits=%0d",checked);$finish;
    end
    initial begin #10000;$fatal(1,"Serializer watchdog");end
endmodule
