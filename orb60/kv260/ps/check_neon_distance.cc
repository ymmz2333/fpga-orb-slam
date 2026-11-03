#include "Hamming256Neon.h"
#include <array>
#include <chrono>
#include <cstring>
#include <fstream>
#include <iostream>
#include <vector>
#include <algorithm>
unsigned reference(const uint8_t* a,const uint8_t* b) {
    unsigned dist=0;
    for(int i=0;i<8;++i) {
        uint32_t x,y;std::memcpy(&x,a+i*4,4);std::memcpy(&y,b+i*4,4);unsigned v=x^y;
        v=v-((v>>1)&0x55555555);v=(v&0x33333333)+((v>>2)&0x33333333);
        dist+=(((v+(v>>4))&0x0f0f0f0f)*0x01010101)>>24;
    }
    return dist;
}
volatile unsigned sink=0;
int main(int argc,char** argv) {
    if(argc!=2)return 2;
    std::ifstream f(argv[1],std::ios::binary);std::vector<std::array<uint8_t,68>> cases;std::array<uint8_t,68> row;
    while(f.read(reinterpret_cast<char*>(row.data()),row.size()))cases.push_back(row);
    if(!f.eof()||f.gcount()||cases.size()!=10000)return 3;
    for(const auto& item:cases) {
        uint32_t expected;std::memcpy(&expected,item.data()+64,4);
        if(expected>256||KvMatch::distance(item.data(),item.data()+32)!=expected||reference(item.data(),item.data()+32)!=expected)return 4;
    }
    auto bench=[&](bool neon){auto start=std::chrono::steady_clock::now();unsigned total=0;
        for(unsigned i=0;i<300000;++i) {
            const auto& item=cases[i%cases.size()];
            total+=neon?KvMatch::distance(item.data(),item.data()+32):reference(item.data(),item.data()+32);
        }
        sink+=total;return std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();};
    double old[3],fast[3];
    for(int i=0;i<3;++i){if(i%2){fast[i]=bench(true);old[i]=bench(false);}else{old[i]=bench(false);fast[i]=bench(true);}}
    std::sort(old,old+3);std::sort(fast,fast+3);
    std::cout<<"{\"status\":\"NEON_EXACT_DISTANCE_PASS\",\"cases\":"<<cases.size()
             <<",\"scope\":\"PS integer kernel only, not whole FPS\",\"reference_seconds\":"<<old[1]<<",\"neon_seconds\":"<<fast[1]<<"}\n";
}
