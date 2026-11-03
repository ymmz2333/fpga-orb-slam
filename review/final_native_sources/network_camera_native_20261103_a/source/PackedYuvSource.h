#include "PackedByteStream.h"
// Packed camera-format file replay. Byte order follows Linux V4L2 YUYV/UYVY.
#pragma once
#include "Orb60Protocol.h"
#include <opencv2/imgproc.hpp>
#include <array>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <vector>
namespace KvNetwork {
class PackedYuvSource {
    struct Color {uint64_t index,stamp;uint32_t crc;};
    PackedByteStream input;std::array<uint8_t,256> lut{};bool uyvy=false;uint64_t counter=0;std::vector<Color> colors;
public:
    PackedYuvSource(const std::string& path,bool use_uyvy):input(path,std::ios::binary),uyvy(use_uyvy) {
        if(!input)throw std::runtime_error("Cannot open explicit uncompressed packed source");
        const char* name=std::getenv("ORB60_PACKED_GRAY_LUT");
        if(!name||!*name)throw std::runtime_error("Explicit packed luminance LUT required");
        std::ifstream file(name,std::ios::binary);file.read(reinterpret_cast<char*>(lut.data()),256);
        if(file.gcount()!=256||file.peek()!=std::char_traits<char>::eof())throw std::runtime_error("Packed luminance LUT shape mismatch");
        const char* verify=std::getenv("ORB60_PACKED_VERIFY_COLOR_CSV");
        if(verify&&*verify) {
            std::ifstream manifest(verify);std::string line;std::getline(manifest,line);
            if(line!="source_frame_id,timestamp_ns,bgr_crc")throw std::runtime_error("Packed RGB verification header mismatch");
            while(std::getline(manifest,line)) {
                std::istringstream s(line);Color row{};char a,b;
                if(!(s>>row.index>>a>>row.stamp>>b>>row.crc)||a!=','||b!=','||row.index!=colors.size()||!row.stamp||(!colors.empty()&&row.stamp<=colors.back().stamp))throw std::runtime_error("Packed RGB verification identity mismatch");
                s>>std::ws;if(!s.eof())throw std::runtime_error("Extra packed RGB fields");colors.push_back(row);
            }
            if(colors.empty())throw std::runtime_error("Empty packed RGB verification manifest");
        }
    }
    bool read(cv::Mat& bgr,cv::Mat& gray,bool indexed,uint64_t index,uint64_t stamp,uint32_t gray_crc) {
        uint8_t header[32];input.read(reinterpret_cast<char*>(header),32);const auto n=input.gcount();
        if(n==0&&input.eof()) {
            if(!colors.empty()&&counter!=colors.size())throw std::runtime_error("Incomplete packed RGB verification coverage");
            return false;
        }
        if(n!=32||std::memcmp(header,uyvy?"ORBUYVY1":"ORBYUYV1",8))throw std::runtime_error("Packed source format/header mismatch");
        if(!indexed||index!=counter||orb_get64(header+8)!=index||orb_get64(header+16)!=stamp||orb_get32(header+28)!=gray_crc)throw std::runtime_error("Packed source frame/time/gray identity mismatch");
        cv::Mat packed(720,960,CV_8UC2);const size_t bytes=packed.total()*packed.elemSize();
        input.read(reinterpret_cast<char*>(packed.data),bytes);
        if(input.gcount()!=std::streamsize(bytes)||orb_crc32(packed.data,bytes)!=orb_get32(header+24))throw std::runtime_error("Packed frame length/CRC mismatch");
        gray.create(720,960,CV_8UC1);const size_t channel=uyvy?1:0;
        const size_t pixels=gray.total();for(size_t i=0;i<pixels;++i)gray.data[i]=lut[packed.data[i*2+channel]];
        cv::cvtColor(packed,bgr,uyvy?cv::COLOR_YUV2BGR_UYVY:cv::COLOR_YUV2BGR_YUY2);
        if(!colors.empty()) {
            if(counter>=colors.size())throw std::runtime_error("Extra packed RGB frame");const auto& row=colors[counter];
            if(row.index!=index||row.stamp!=stamp||orb_crc32(bgr.data,bgr.total()*bgr.elemSize())!=row.crc)throw std::runtime_error("Native packed RGB pixels differ from independent reference");
        }
        ++counter;return true;
    }
};
}
