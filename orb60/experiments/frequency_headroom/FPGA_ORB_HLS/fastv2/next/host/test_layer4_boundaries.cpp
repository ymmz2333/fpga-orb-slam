#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>
extern "C" int next_test_layer4_merge(const uint64_t*,const uint8_t*,int,uint64_t*);
extern "C" void next_test_layer4_gaussian(const uint64_t*,uint64_t*,int,int);
static int reflect(int x,int n) {return x<0?-x:x>=n?2*n-x-2:x;}
int main() {
    try {
        constexpr int n=4096;std::vector<uint64_t> values(4*n),out(4*n);std::vector<uint8_t> masks(n);
        for(int mode=0;mode<=16;++mode) {
            std::vector<uint64_t> wanted;
            for(int i=0;i<n;++i) {
                masks[i]=mode<16?mode:((i*13+i/7)&15);
                for(int lane=0;lane<4;++lane) {values[4*i+lane]=4*i+lane+1;if(masks[i]&(1<<lane)) wanted.push_back(values[4*i+lane]);}
            }
            int size=next_test_layer4_merge(values.data(),masks.data(),n,out.data());
            if(size!=int(wanted.size()) || !std::equal(wanted.begin(),wanted.end(),out.begin())) throw std::runtime_error("quad merge order/count");
        }
        const unsigned coefficients[7]={18,34,48,56,48,34,18};
        for(int w: {33,34,35,63,64,65}) for(int h: {9,17,37}) {
            std::vector<uint8_t> pixels(w*h);std::vector<unsigned> horizontal(w*h);uint32_t random=0x604411;
            for(auto& p:pixels) {random^=random<<13;random^=random>>17;random^=random<<5;p=uint8_t(random);}
            for(int y=0;y<h;++y) for(int x=0;x<w;++x) for(int t=0;t<7;++t) horizontal[y*w+x]+=pixels[y*w+reflect(x+t-3,w)]*coefficients[t];
            std::vector<uint64_t> raw((w*h+7)/8),expected(raw.size()+8,UINT64_C(0xa5a5a5a5a5a5a5a5)),actual=expected;
            for(size_t i=0;i<raw.size();++i) expected[i]=0;
            for(int y=0;y<h;++y) for(int x=0;x<w;++x) {
                const int i=y*w+x;raw[i/8]|=uint64_t(pixels[i])<<(8*(i&7));unsigned value=0;
                for(int t=0;t<7;++t) value+=horizontal[reflect(y+t-3,h)*w+x]*coefficients[t];
                expected[i/8]|=uint64_t(uint8_t((value+32768)>>16))<<(8*(i&7));
            }
            next_test_layer4_gaussian(raw.data(),actual.data(),w,h);
            if(actual!=expected) throw std::runtime_error("quad Gaussian/tail/guard");
        }
        std::cout<<"LAYER4_BOUNDARY_PASS masks=0..15,mixed gaussian_shapes=18 tails=1,2,3,0\n";return 0;
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
