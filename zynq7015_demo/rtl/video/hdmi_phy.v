`timescale 1ns/1ps
`default_nettype none
module hdmi_phy(
    input wire pixel_clk,input wire serial_clk,input wire reset,
    input wire [23:0] rgb,input wire de,input wire hsync,input wire vsync,
    (* X_INTERFACE_INFO="xilinx.com:signal:clock:1.0 hdmi_clk_p CLK", X_INTERFACE_PARAMETER="FREQ_HZ 74250000" *)
    output wire hdmi_clk_p,
    (* X_INTERFACE_INFO="xilinx.com:signal:clock:1.0 hdmi_clk_n CLK", X_INTERFACE_PARAMETER="FREQ_HZ 74250000" *)
    output wire hdmi_clk_n,
    output wire [2:0] hdmi_dat_p,output wire [2:0] hdmi_dat_n
);
    wire [9:0] red,green,blue;
    tmds_encoder r(.clk(pixel_clk),.reset(reset),.data(rgb[23:16]),.de(de),.control(2'b00),.symbol(red));
    tmds_encoder g(.clk(pixel_clk),.reset(reset),.data(rgb[15:8]),.de(de),.control(2'b00),.symbol(green));
    tmds_encoder b(.clk(pixel_clk),.reset(reset),.data(rgb[7:0]),.de(de),.control({vsync,hsync}),.symbol(blue));
    tmds_serializer sr(.pixel_clk(pixel_clk),.serial_clk(serial_clk),.reset(reset),.symbol(red),.out_p(hdmi_dat_p[2]),.out_n(hdmi_dat_n[2]));
    tmds_serializer sg(.pixel_clk(pixel_clk),.serial_clk(serial_clk),.reset(reset),.symbol(green),.out_p(hdmi_dat_p[1]),.out_n(hdmi_dat_n[1]));
    tmds_serializer sb(.pixel_clk(pixel_clk),.serial_clk(serial_clk),.reset(reset),.symbol(blue),.out_p(hdmi_dat_p[0]),.out_n(hdmi_dat_n[0]));
    tmds_serializer sc(.pixel_clk(pixel_clk),.serial_clk(serial_clk),.reset(reset),.symbol(10'b1111100000),.out_p(hdmi_clk_p),.out_n(hdmi_clk_n));
endmodule
`default_nettype wire
