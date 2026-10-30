`timescale 1ns/1ps
module tb_tmds;
    reg clk=0,reset=1,de=0;
    reg [7:0] data=0;
    reg [1:0] control=0;
    wire [9:0] symbol;
    tmds_encoder dut(.*);
    always #5 clk=~clk;
    integer i,j,k,ones,dc,transitions;
    reg [7:0] q,decoded;
    reg [9:0] controls[0:3];
    task check_data(input [7:0] value);
        begin
            @(negedge clk);data=value;de=1;
            @(posedge clk);#1;
            q=symbol[9]?~symbol[7:0]:symbol[7:0];decoded[0]=q[0];
            for(j=1;j<8;j=j+1)decoded[j]=q[j]^q[j-1]^!symbol[8];
            if(decoded!==value)$fatal(1,"TMDS decode mismatch input=%h output=%h",value,symbol);
            ones=0;transitions=0;
            for(j=0;j<10;j=j+1)ones=ones+symbol[j];
            for(j=1;j<8;j=j+1)transitions=transitions+(q[j]!=q[j-1]);
            dc=dc+2*ones-10;
            if(dc < -8 || dc > 8)$fatal(1,"TMDS accumulated disparity %0d",dc);
            if(transitions>4)$fatal(1,"TMDS did not minimize transitions");
        end
    endtask
    initial begin
        controls[0]=10'b1101010100;controls[1]=10'b0010101011;
        controls[2]=10'b0101010100;controls[3]=10'b1010101011;
        repeat(4)@(posedge clk);@(negedge clk);reset=0;dc=0;
        for(k=0;k<4;k=k+1)begin
            @(negedge clk);de=0;control=k;
            @(posedge clk);#1;if(symbol!==controls[k])$fatal(1,"Control symbol mismatch");dc=0;
            for(i=0;i<256;i=i+1)check_data(i[7:0]);
            for(i=255;i>=0;i=i-1)check_data(i[7:0]);
        end
        $display("TEST_PASS TMDS exhaustive decode, control, transition and DC checks");$finish;
    end
    initial begin #100000;$fatal(1,"TMDS watchdog");end
endmodule
