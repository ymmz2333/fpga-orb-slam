#include "Thirdparty/DBoW2/DBoW2/FORB.h"
#include "BowDistanceNeon.h"
#include <array>
#include <algorithm>
#include <chrono>
#include <cstring>
#include <dlfcn.h>
#include <fstream>
#include <iostream>
#include <vector>
volatile unsigned kv_bow_sink=0;
int main(int argc,char** argv){try {
    if(argc!=3)return 2;
    std::ifstream input(argv[1],std::ios::binary);std::vector<std::array<uint8_t,68>> cases;std::array<uint8_t,68> item;
    while(input.read(reinterpret_cast<char*>(item.data()),item.size()))cases.push_back(item);
    if(!input.eof()||input.gcount()||cases.size()!=10000)return 3;
    for(const auto& c:cases) {
        uint32_t expected;std::memcpy(&expected,c.data()+64,4);
        for(int alignment=0;alignment<16;++alignment) {
            std::array<uint8_t,64> a{},b{};std::memcpy(a.data()+alignment,c.data(),32);std::memcpy(b.data()+alignment,c.data()+32,32);
            cv::Mat am(1,32,CV_8U,a.data()+alignment),bm(1,32,CV_8U,b.data()+alignment);
            if(expected>256||KvBow::distance(am,bm)!=int(expected)||DBoW2::FORB::distance(am,bm)!=int(expected))return 4;
        }
    }
    bool rejected=false;try{KvBow::distance(cv::Mat(1,31,CV_8U),cv::Mat(1,32,CV_8U));}catch(const std::invalid_argument&){rejected=true;}
    if(!rejected)return 5;
    Dl_info info{};if(!dladdr(reinterpret_cast<void*>(&DBoW2::FORB::distance),&info)||!info.dli_fname)return 6;
    if(std::string(info.dli_fname)!=argv[2])return 7;
    auto bench=[&](bool neon){const auto begin=std::chrono::steady_clock::now();unsigned sum=0;
        for(unsigned i=0;i<300000;++i){auto& c=cases[i%cases.size()];cv::Mat a(1,32,CV_8U,c.data()),b(1,32,CV_8U,c.data()+32);sum+=neon?KvBow::distance(a,b):DBoW2::FORB::distance(a,b);}
        kv_bow_sink+=sum;return std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count();};
    double ref[3],fast[3];for(int i=0;i<3;++i){ref[i]=bench(false);fast[i]=bench(true);}std::sort(ref,ref+3);std::sort(fast,fast+3);
    std::cout<<"{\"status\":\"EXACT_BOW_NEON_PASS\",\"cases\":10000,\"alignments\":16,\"reference_seconds\":"<<ref[1]<<",\"neon_seconds\":"<<fast[1]<<",\"bound_library\":\""<<info.dli_fname<<"\",\"scope\":\"Integer kernel and actual symbol binding only, no full SLAM acceptance\"}\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
