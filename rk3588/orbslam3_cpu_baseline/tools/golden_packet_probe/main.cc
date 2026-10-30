// PS/software acceptance tool: actual B1 decoder and encoder, without extraction/SLAM.
#include "FeatureIO.h"
#include "ORBextractor.h"
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <map>
#include <sstream>
#include <cstdio>
std::vector<char> bytes(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("cannot read " + path);
    return {std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>()};
}
int main(int argc, char** argv) {
    try {
        if (argc != 3) throw std::runtime_error("manifest.tsv scratch-file required");
        std::ifstream manifest(argv[1]);
        if (!manifest) throw std::runtime_error("manifest missing");
        std::map<std::pair<int,int>, std::unique_ptr<ORB_SLAM3::ORBextractor>> extractors;
        std::string line; unsigned checked=0;
        while (std::getline(manifest,line)) {
            std::istringstream fields(line); std::string path; uint64_t ns; int role,w,h,levels,budget;
            if (!(fields>>path>>ns>>role>>w>>h>>levels>>budget)) throw std::runtime_error("malformed manifest");
            auto key=std::make_pair(levels,budget);
            if (!extractors.count(key)) extractors[key].reset(new ORB_SLAM3::ORBextractor(budget,1.2f,levels,20,7));
            auto* extractor=extractors[key].get();
            std::vector<cv::KeyPoint> keys; cv::Mat descriptors; double read=0,decode=0;
            int mono=ORB_SLAM3::FeatureIO::LoadPacket(path,ns,role,w,h,extractor,keys,descriptors,read,decode);
            ORB_SLAM3::FeatureIO::SavePacket(argv[2],"",ns,role,w,h,extractor,mono,keys,descriptors);
            bool equal=bytes(path)==bytes(argv[2]); std::remove(argv[2]);
            if (!equal) throw std::runtime_error("non-exact roundtrip " + path);
            ++checked;
        }
        std::cout<<"B1_ACTUAL_CODEC_BYTE_EXACT packets="<<checked<<std::endl;
        return 0;
    } catch (const std::exception& e) { std::cerr<<e.what()<<std::endl; return 1; }
}
