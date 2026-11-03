// PS-only exact 256-bit word-tree distance; no vocabulary or score changes.
#pragma once
#include "Hamming256Neon.h"
#include <opencv2/core.hpp>
#include <stdexcept>
namespace KvBow {
inline int distance(const cv::Mat& a,const cv::Mat& b) {
    if(a.type()!=CV_8UC1||b.type()!=CV_8UC1||a.rows!=1||b.rows!=1||a.cols!=32||b.cols!=32)
        throw std::invalid_argument("Fixed 1x32 byte ORB descriptors required");
    return int(KvMatch::distance(a.ptr<uint8_t>(),b.ptr<uint8_t>()));
}
}
