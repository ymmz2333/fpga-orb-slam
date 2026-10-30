#include "descriptor.hpp"
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

template<typename T> static std::vector<T> binary(const std::string& path,size_t count) {
    std::ifstream f(path,std::ios::binary);std::vector<T> result(count);
    if(!f.read(reinterpret_cast<char*>(result.data()),count*sizeof(T)) || f.peek()!=EOF) throw std::runtime_error("bad vector "+path);
    return result;
}
int main(int argc,char** argv) {
    try {
        if(argc!=2) throw std::runtime_error("expected descriptor vectors");
        const std::string directory=argv[1];std::ifstream meta(directory+"/cases.bin",std::ios::binary);
        uint32_t header[4]={};
        if(!meta.read(reinterpret_cast<char*>(header),16) || header[0]!=0x60d20001 || header[1]!=1 || header[3]!=1000)
            throw std::runtime_error("bad descriptor case header");
        std::vector<uint64_t> features(8000,UINT64_C(0xc3c3c3c3c3c3c3c3));
        for(unsigned i=0;i<header[2];++i) {
            int32_t control[12]={};if(!meta.read(reinterpret_cast<char*>(control),48)) throw std::runtime_error("missing controls");
            std::string index=std::to_string(i);if(i<10)index="0"+index;
            const auto prefix=directory+"/d"+index;
            auto raw=binary<uint64_t>(prefix+"_raw.bin",86400),blur=binary<uint64_t>(prefix+"_blur.bin",86400);
            const auto points=binary<uint64_t>(prefix+"_points.bin",512),expected=binary<uint64_t>(prefix+"_features.bin",8000);
            if(control[10]) std::fill(features.begin(),features.end(),UINT64_C(0xc3c3c3c3c3c3c3c3));
            const auto raw_before=raw,blur_before=blur,points_before=points;uint64_t stats[8]={};
            const int status=fastv2_descriptor_hls(raw.data(),blur.data(),points.data(),features.data(),stats,
                control[0],control[1],control[2],control[3],control[4],control[5]);
            orb60::DescriptorStats s;std::memcpy(&s,stats,64);
            if(status!=control[6] || features!=expected || raw!=raw_before || blur!=blur_before || points!=points_before ||
                s.version!=orb60::kDescriptorVersion || s.status!=uint32_t(status) || s.level!=uint32_t(control[3]) ||
                s.requested!=uint32_t(control[2]) || s.completed!=uint32_t(control[7]) || s.frame_offset!=uint32_t(control[4]) ||
                s.raw_read_bytes!=uint32_t(control[8]) || s.blur_read_bytes!=uint32_t(control[9]) ||
                s.point_read_bytes!=uint32_t(status==-1 ? 0 : control[2]*16) || s.feature_write_bytes!=s.completed*64 ||
                s.flags!=uint32_t(status==-1 ? 0 : 3) || (status==-1 ? s.dataflow_cycles!=0 : s.dataflow_cycles<1) ||
                s.reserved[0] || s.reserved[1] || s.reserved[2] || s.reserved[3]) {
                std::cerr<<"DESCRIPTOR_CASE_FAIL case="<<i<<" status="<<status<<" expected_status="<<control[6]
                    <<" records_exact="<<(features==expected)<<" raw_bytes="<<s.raw_read_bytes<<" blur_bytes="<<s.blur_read_bytes<<'\n';
                return 1;
            }
            std::cout<<"DESCRIPTOR_CASE_PASS case="<<i<<" level="<<control[3]<<" count="<<control[2]<<" completed="<<s.completed
                <<" status="<<status<<" cycles="<<s.dataflow_cycles<<'\n';
        }
        if(meta.peek()!=EOF)throw std::runtime_error("trailing controls");
        std::cout<<"DESCRIPTOR_STREAM_PASS cases="<<header[2]<<'\n';return 0;
    } catch(const std::exception& e) {std::cerr<<"DESCRIPTOR_STREAM_FAIL "<<e.what()<<'\n';return 1;}
}
