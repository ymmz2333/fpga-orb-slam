/* GPL-3.0-or-later: independent circular-image oracle for fused reception. */
#include "../src/descriptor_hls.cpp"
#include "constants.hpp"
#include <iostream>
#include <vector>
#include <stdexcept>
#include <limits>

static uint32_t random_state=0x6013a32u;
static uint32_t random_value() {random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;return random_state;}
static uint8_t pixel_at(const std::vector<uint64_t>& image,int width,int y,int x) {
    const size_t address=size_t(y)*width+x;return uint8_t(image[address/8]>>(8*(address%8)));
}
static PointToken point_at(int x,int y) {return {uint64_t(uint32_t(x))|(uint64_t(uint32_t(y))<<32),UINT64_C(0xfedcba9876543210)};}

static void check_image(int width,int height,int pattern,uint64_t& tested,uint64_t& beats) {
    std::vector<uint64_t> image(86400,UINT64_C(0xb7b7b7b7b7b7b7b7));
    for(int y=0;y<height;++y) for(int x=0;x<width;++x) {
        uint8_t p=0;
        switch(pattern) {
        case 0:p=0;break;case 1:p=255;break;case 2:p=uint8_t(x);break;
        case 3:p=uint8_t(y);break;case 4:p=x>=width/2?255:0;break;
        case 5:p=y>=height/2?255:0;break;case 6:p=(x+y)&1?255:0;break;
        default:p=uint8_t(random_value());break;
        }
        const size_t address=size_t(y)*width+x;
        image[address/8]=(image[address/8]&~(UINT64_C(255)<<(8*(address%8))))|(uint64_t(p)<<(8*(address%8)));
    }
    std::vector<PointToken> points={point_at(0,0),point_at(width-33,height-33)};
    for(int i=0;i<32;++i) points.push_back(point_at(int(random_value()%uint32_t(width-32)),int(random_value()%uint32_t(height-32))));
    points.push_back(point_at(-1,0));points.push_back(point_at(width-32,0));
    points.push_back(point_at(0,height-32));points.push_back(point_at(std::numeric_limits<int>::max(),std::numeric_limits<int>::min()));
    points.push_back(point_at(0,0)); // Valid input after errors must still drain.
    DescriptorReadPort port(image.data());hls::stream<PointToken> incoming,metadata;
    hls::stream<MomentPacket> output;hls::stream<uint32_t> done;
    for(const auto& p:points) incoming.write(p);
    issue_raw_requests(port,incoming,metadata,int(points.size()),width,height);
    receive_raw_moments(port,metadata,output,int(points.size()),width,height,done);
    uint32_t bytes=0;
    for(const auto& p:points) {
        const auto actual=output.read();const int x=signed32(uint32_t(p.xy)),y=signed32(uint32_t(p.xy>>32));
        const bool valid=x>=0 && y>=0 && x+32<width && y+32<height;
        int64_t m10=0,m01=0;
        if(valid) {
            const int cx=x+16,cy=y+16;
            // Original independent table and scalar image accesses. No packed
            // beat, alignment, partial-word sum or DUT helper in the oracle.
            for(int v=-15;v<=15;++v) {
                const int extent=orb_golden::umax[v<0?-v:v];
                for(int u=-extent;u<=extent;++u) {
                    const int pixel=pixel_at(image,width,cy+v,cx+u);
                    m10+=int64_t(u)*pixel;m01+=int64_t(v)*pixel;
                }
                const int start=(cy+v)*width+cx-15;
                bytes+=uint32_t(((start%8+31+7)/8)*8);
            }
        }
        if(actual.point.xy!=p.xy || actual.point.score_tile!=p.score_tile || actual.status!=(valid?0:-2) ||
           actual.m10!=m10 || actual.m01!=m01 || m10 < -624240 || m10 > 624240 || m01 < -624240 || m01 > 624240)
            throw std::runtime_error("fused receiver differs from original circular-image oracle");
        ++tested;
    }
    if(done.read()!=bytes || !incoming.empty() || !metadata.empty() || !output.empty() || !done.empty())
        throw std::runtime_error("fused receiver ownership or payload byte count failed");
    beats+=bytes/8;
}
int main() {
    try {
        uint64_t tested=0,beats=0;
        for(int width: {33,34,35,36,37,38,39,40,63,64,65,959,960})
            for(int pattern=0;pattern<8;++pattern) check_image(width,65,pattern,tested,beats);
        for(int i=0;i<128;++i) check_image(33+int(random_value()%928),33+int(random_value()%96),7,tested,beats);
        // Full external record/error-prefix/A32 coverage comes from the frozen
        // independent 38-transaction descriptor stream test, run separately.
        std::cout<<"RAW_MOMENT_FUSION_PASS points="<<tested<<" beats="<<beats<<" seed=0x6013a32\n";
        return 0;
    } catch(const std::exception& e) {std::cerr<<"RAW_MOMENT_FUSION_FAIL "<<e.what()<<'\n';return 1;}
}
