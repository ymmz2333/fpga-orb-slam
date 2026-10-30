#include "descriptor.hpp"
#include "next_backend.h"
#include "golden.hpp"
#include "backend_tables.h"
#include "descriptor_rom.hpp"
#include <array>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>

static void require(bool value,const char* message) {if(!value) throw std::runtime_error(message);}
int main() {
    try {
        unsigned quantized=0,rotations=0;
        for(int k=0;k<=32;++k) {
            const int64_t boundary=int64_t(k)*737280-368640;
            for(int delta=-3;delta<=3;++delta) {
                const int64_t angle=boundary+delta;
                if(angle<0 || angle>=23592960) continue;
                require(orb60_descriptor_quantize(uint32_t(angle))==orb_golden::quantize(uint32_t(angle),32),"A32 boundary");
                ++quantized;
            }
        }
        for(uint32_t angle=0;angle<23592960;angle+=997) {
            require(orb60_descriptor_quantize(angle)==orb_golden::quantize(angle,32),"A32 scan");++quantized;
        }
        for(int bin=0;bin<32;++bin) for(int bit=0;bit<256;++bit) {
            const uint32_t packed=orb60_descriptor_rom::kBriefPairs[(bin&7)*256+bit];
            for(int sample=0;sample<2;++sample) {
                int x=int((packed>>(12*sample))&63),y=int((packed>>(12*sample+6))&63);
                if(x>=32)x-=64;if(y>=32)y-=64;
                for(int q=0;q<(bin>>3);++q) {const int old=x;x=-y;y=old;}
                require(x==kNextBriefOffsets[bin][bit*2+sample][0] && y==kNextBriefOffsets[bin][bit*2+sample][1],"Compressed quarter rotation");
                ++rotations;
            }
        }
        // Append all eight maximum lists to a guarded capacity-1000 frame.
        const int widths[]={960,800,667,556,463,386,322,268},heights[]={720,600,500,417,347,289,241,201};
        const int counts[]={204,165,140,117,105,87,70,54};
        std::vector<uint64_t> raw(86400,0),blur=raw,output(8002,UINT64_C(0xc3c3c3c3c3c3c3c3)),expected=output;
        std::array<NextPoint,256> points={};std::vector<uint64_t> packed(512,0);uint64_t stats[8]={};
        int offset=0;
        for(int level=0;level<8;++level) {
            std::vector<NextFeature> ref(counts[level]);
            for(int i=0;i<counts[level];++i) points[i]={i%(widths[level]-32),(i*13)%(heights[level]-32),i-127,i%204};
            require(next_describe(reinterpret_cast<const uint8_t*>(raw.data()),reinterpret_cast<const uint8_t*>(blur.data()),
                widths[level],heights[level],points.data(),counts[level],level,ref.data(),counts[level])==0,"Frozen append reference");
            std::memcpy(packed.data(),points.data(),counts[level]*16);
            require(fastv2_descriptor_hls(raw.data(),blur.data(),packed.data(),output.data()+1,stats,widths[level],heights[level],
                counts[level],level,offset,1000)==0,"Frame append");
            std::memcpy(expected.data()+1+offset*8,ref.data(),counts[level]*64);
            require(output==expected,"Append/order/guard/tail");offset+=counts[level];
        }
        require(offset==942,"Frame maximum");
        // Invalid middle point preserves the completed prefix, drains subsequent blocks.
        std::fill(output.begin(),output.end(),UINT64_C(0xc3c3c3c3c3c3c3c3));expected=output;
        points[0]={0,0,99,0};points[1]={-1,0,88,0};points[2]={1,1,77,0};
        std::memcpy(packed.data(),points.data(),48);
        NextFeature one={};
        require(next_describe(reinterpret_cast<const uint8_t*>(raw.data()),reinterpret_cast<const uint8_t*>(blur.data()),
            960,720,points.data(),1,0,&one,1)==0,"Prefix reference");
        require(fastv2_descriptor_hls(raw.data(),blur.data(),packed.data(),output.data()+1,stats,960,720,3,0,7,1000)==-2,"Middle point rejection");
        std::memcpy(expected.data()+1+7*8,&one,64);require(output==expected,"Completed prefix semantics");
        orb60::DescriptorStats c;std::memcpy(&c,stats,64);require(c.completed==1 && c.status==uint32_t(-2),"Failure stats");
        require(fastv2_descriptor_hls(raw.data(),blur.data(),packed.data(),output.data()+1,stats,960,720,1,0,1000,1000)==-1 &&
            output==expected,"Capacity at append end");
        std::cout<<"ORB60_DESCRIPTOR_CONTRACT_PASS rotations="<<rotations<<" quantized="<<quantized<<" frame_features="<<offset<<" partial_error=1\n";
        return 0;
    } catch(const std::exception& e) {std::cerr<<"ORB60_DESCRIPTOR_CONTRACT_FAIL "<<e.what()<<'\n';return 1;}
}
