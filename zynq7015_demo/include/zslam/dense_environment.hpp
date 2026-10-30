#pragma once
#include "bridge_wire.hpp"
#include <cmath>
namespace zslam {
struct DensePoint {float x=0,y=0,z=0;uint8_t r=0,g=0,b=0;};
inline std::vector<DensePoint> readDenseEnvironment(const std::string &path,const std::string &points_hash,const std::string &camera_hash){
    auto data=demo::readFile(path,30000144);if(data.size()<144||std::memcmp(data.data(),"ORBDNS01",8))throw std::runtime_error("Invalid dense environment header");
    unsigned count=demo::get32(data.data()+8);
    if(!count||count>2000000||data.size()!=144+size_t(count)*15)throw std::runtime_error("Dense environment size/capacity mismatch");
    if(std::string(data.begin()+12,data.begin()+76)!=points_hash||std::string(data.begin()+76,data.begin()+140)!=camera_hash)throw std::runtime_error("Dense environment belongs to another sparse map/calibration");
    if(demo::get32(data.data()+140)!=demo::crc32(data.data()+144,data.size()-144))throw std::runtime_error("Dense environment CRC mismatch");
    std::vector<DensePoint> out;out.reserve(count);
    for(unsigned i=0;i<count;i++){const auto *p=data.data()+144+i*15;DensePoint v;std::memcpy(&v.x,p,4);std::memcpy(&v.y,p+4,4);std::memcpy(&v.z,p+8,4);v.r=p[12];v.g=p[13];v.b=p[14];
        if(!std::isfinite(v.x)||!std::isfinite(v.y)||!std::isfinite(v.z))throw std::runtime_error("Nonfinite dense coordinate");out.push_back(v);}
    return out;
}
}
