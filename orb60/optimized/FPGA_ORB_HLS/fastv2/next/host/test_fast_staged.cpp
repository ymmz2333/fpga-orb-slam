#include <algorithm>
#include <cstdint>
#include <iostream>
uint8_t next_test_fast_score(uint8_t,const uint8_t[16]);
static uint8_t reference(uint8_t center,const uint8_t ring[16]) {
    int best=0;
    for(int start=0;start<16;++start) {
        int low=256,high=-256;
        for(int t=0;t<9;++t) {const int d=int(ring[(start+t)&15])-center;low=std::min(low,d);high=std::max(high,d);}
        best=std::max(best,std::max(low,-high));
    }
    return uint8_t(best>0?best-1:0);
}
int main() {
    uint8_t ring[16];uint32_t state=0x604410;
    auto check=[&](uint8_t center) {return next_test_fast_score(center,ring)==reference(center,ring);};
    for(int center=0;center<256;++center) for(int mode=0;mode<4;++mode) {
        for(int i=0;i<16;++i) ring[i]=mode==0?0:mode==1?255:mode==2?((i&1)?0:255):uint8_t(center);
        if(!check(uint8_t(center))) return 1;
        for(int start=0;start<16;++start) {
            for(int i=0;i<16;++i) ring[i]=uint8_t(center);
            for(int i=0;i<9;++i) ring[(start+i)&15]=mode&1?255:0;
            if(!check(uint8_t(center))) return 1;
        }
    }
    for(unsigned n=0;n<10000000;++n) {
        auto random=[&](){state^=state<<13;state^=state>>17;state^=state<<5;return uint8_t(state);};
        const uint8_t center=random();for(auto& p:ring)p=random();if(!check(center)) return 1;
    }
    std::cout<<"FAST_STAGED_EXACT_PASS random=10000000 directed=17408\n";return 0;
}
