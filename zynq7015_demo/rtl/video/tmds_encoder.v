`timescale 1ns/1ps
`default_nettype none
module tmds_encoder(
    input wire clk, input wire reset,
    input wire [7:0] data, input wire de,
    input wire [1:0] control,
    output reg [9:0] symbol
);
    reg [8:0] q;
    reg [3:0] ones_in, ones_q;
    reg use_xnor;
    reg signed [5:0] balance;
    reg signed [5:0] disparity;
    integer i;
    always @* begin
        ones_in=0;ones_q=0;
        for(i=0;i<8;i=i+1)ones_in=ones_in+{3'b0,data[i]};
        use_xnor=(ones_in>4)||((ones_in==4)&&!data[0]);
        q[0]=data[0];
        for(i=1;i<8;i=i+1)q[i]=q[i-1]^data[i]^use_xnor;
        q[8]=!use_xnor;
        for(i=0;i<8;i=i+1)ones_q=ones_q+{3'b0,q[i]};
        balance=$signed({1'b0,ones_q,1'b0})-6'sd8;
    end
    always @(posedge clk) begin
        if(reset)begin disparity<=0;symbol<=10'b1101010100;end
        else if(!de)begin
            disparity<=0;
            case(control)
                2'b00:symbol<=10'b1101010100;
                2'b01:symbol<=10'b0010101011;
                2'b10:symbol<=10'b0101010100;
                2'b11:symbol<=10'b1010101011;
            endcase
        end else if((disparity==0)||(balance==0))begin
            symbol<={~q[8],q[8],q[8]?q[7:0]:~q[7:0]};
            disparity<=disparity+(q[8]?balance:-balance);
        end else if(((disparity>0)&&(balance>0))||((disparity<0)&&(balance<0)))begin
            symbol<={1'b1,q[8],~q[7:0]};
            disparity<=disparity+(q[8]?6'sd2:6'sd0)-balance;
        end else begin
            symbol<={1'b0,q[8],q[7:0]};
            disparity<=disparity+balance-(q[8]?6'sd0:6'sd2);
        end
    end
endmodule
`default_nettype wire
