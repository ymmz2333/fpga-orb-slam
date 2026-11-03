#include "Orb60Protocol.h"
#include <algorithm>
#include <chrono>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>
int main(int argc,char** argv) {
    try {
        if(argc!=3)throw std::runtime_error("fixture binary and CRC CSV required");
        if(!(getauxval(AT_HWCAP)&HWCAP_CRC32))throw std::runtime_error("Native ARM CRC instruction unavailable");
        std::ifstream f(argv[1],std::ios::binary);
        std::vector<uint8_t> data((std::istreambuf_iterator<char>(f)),{});
        if(data.empty())throw std::runtime_error("Empty CRC fixture");
        std::ifstream rows(argv[2]);std::string line;std::getline(rows,line);
        if(line!="offset,length,crc32")throw std::runtime_error("CRC fixture header mismatch");
        size_t count=0;unsigned long long offset,length,expected;char a,b;
        while(rows>>offset>>a>>length>>b>>expected) {
            if(a!=','||b!=','||offset>data.size()||length>data.size()-offset||expected>0xffffffffULL)throw std::runtime_error("CRC fixture bounds");
            const auto* p=data.data()+offset;
            if(orb_crc32(p,length)!=expected||orb_crc32_software(p,length)!=expected||orb_crc32_arm(p,length)!=expected)throw std::runtime_error("CRC differs from independent zlib fixture");
            ++count;
        }
        if(!rows.eof()||count<1024)throw std::runtime_error("Incomplete CRC fixture");
        const char check[]="123456789";
        if(orb_crc32(check,9)!=0xcbf43926u||orb_crc32(check,0)!=0)throw std::runtime_error("Standard IEEE CRC vector mismatch");
        volatile uint32_t sink=0;
        auto bench=[&](bool hardware) {
            std::vector<double> ms;
            for(int repeat=0;repeat<21;++repeat) {
                auto start=std::chrono::steady_clock::now();
                for(int n=0;n<20;++n)sink^=hardware?orb_crc32_arm(data.data(),691200):orb_crc32_software(data.data(),691200);
                ms.push_back(std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count()/20);
            }
            std::sort(ms.begin(),ms.end());return ms[ms.size()/2];
        };
        const double software=bench(false),hardware=bench(true);
        std::cout<<"{\"status\":\"EXACT_ARM_IEEE_CRC_PASS\",\"cases\":"<<count
                 <<",\"hardware_available\":true,\"gray_software_ms_median\":"<<software
                 <<",\"gray_hardware_ms_median\":"<<hardware<<",\"sink\":"<<sink<<"}\n";
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}
}
