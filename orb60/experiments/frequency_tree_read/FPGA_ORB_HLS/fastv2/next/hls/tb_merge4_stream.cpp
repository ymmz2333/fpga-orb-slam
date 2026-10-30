#include "merge4.hpp"
#include <iostream>
#include <vector>
int main() {
    for(int mode=0;mode<=16;++mode) {
        hls::stream<CandidateQuad> input;hls::stream<uint64_t> output;std::vector<uint64_t> expected;
        for(int i=0;i<256;++i) {
            CandidateQuad packet={};packet.mask=uint8_t(mode<16?mode:((i*13+i/7)&15));
            for(int lane=0;lane<4;++lane) {packet.words[lane]=4*i+lane+1;if(packet.mask&(1<<lane)) expected.push_back(packet.words[lane]);}
            input.write(packet);
        }
        CandidateQuad end={};end.words[0]=(UINT64_C(1)<<63)|expected.size();input.write(end);expected.push_back(end.words[0]);
        fastv2_merge4_hls(input,output);
        for(auto value:expected) if(output.read()!=value) {std::cerr<<"MERGE4_FAIL mode="<<mode<<'\n';return 1;}
        if(!input.empty() || !output.empty()) return 1;
    }
    std::cout<<"MERGE4_STREAM_PASS cases=17 legal_masks=0..15,mixed\n";return 0;
}
