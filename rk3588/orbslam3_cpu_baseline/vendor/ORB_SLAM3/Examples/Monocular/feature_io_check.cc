#include "FeatureIO.h"
#include "ORBextractor.h"
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <sys/stat.h>
using namespace ORB_SLAM3;
int main(int argc,char** argv) {
    if(argc!=2) return 1;
    const std::string dir=argv[1]; ::mkdir(dir.c_str(),0755);
    ORBextractor extractor(1000,1.2f,8,20,7);
    const uint64_t ns=1403636579763555584ULL;
    std::vector<cv::KeyPoint> expected;
    expected.emplace_back(12.25f,23.5f,31.f,359.125f,42.f,0,-1);
    expected.emplace_back(100.5f,200.25f,37.2f,0.f,11.f,1,7);
    cv::Mat desc(2,32,CV_8UC1);
    for(int i=0;i<64;++i) desc.data[i]=uint8_t(i*7);
    FeatureIO::SavePacket(dir+"/fixture.orb",dir+"/fixture.bin",ns,0,752,480,&extractor,0,expected,desc);
    std::vector<cv::KeyPoint> actual; cv::Mat loaded; double read,decode;
    int mono=FeatureIO::LoadPacket(dir+"/fixture.orb",ns,0,752,480,&extractor,actual,loaded,read,decode);
    if(mono!=0 || actual.size()!=expected.size() || std::memcmp(desc.data,loaded.data,64)) return 2;
    for(size_t i=0;i<actual.size();++i) {
        const auto& a=actual[i]; const auto& b=expected[i];
        if(std::memcmp(&a.pt.x,&b.pt.x,4) || std::memcmp(&a.pt.y,&b.pt.y,4) || a.octave!=b.octave ||
           std::memcmp(&a.angle,&b.angle,4) || std::memcmp(&a.size,&b.size,4) ||
           std::memcmp(&a.response,&b.response,4) || a.class_id!=b.class_id) return 3;
    }
    int rejected=0;
    for(int change=0;change<4;++change) {
        try { FeatureIO::LoadPacket(dir+"/fixture.orb",ns+(change==0),change==1,752-(change==2),480,
                                    &extractor,actual,loaded,read,decode);
            if(change==3) {
                ORBextractor mismatch(500,1.2f,8,20,7);
                FeatureIO::LoadPacket(dir+"/fixture.orb",ns,0,752,480,&mismatch,actual,loaded,read,decode);
            }
        } catch(const std::runtime_error&) { ++rejected; }
    }
    // Empty frames have valid headers and a released descriptor matrix.
    FeatureIO::SavePacket(dir+"/empty.orb",dir+"/empty.bin",ns,0,752,480,&extractor,0,{},cv::Mat());
    FeatureIO::LoadPacket(dir+"/empty.orb",ns,0,752,480,&extractor,actual,loaded,read,decode);
    if(rejected!=4 || !actual.empty() || !loaded.empty()) return 4;
    std::cout << "FEATURE_IO_CHECK PASS exact_float_descriptor_roundtrip=1 rejected_metadata=4 empty_frame=1\n";
    return 0;
}
