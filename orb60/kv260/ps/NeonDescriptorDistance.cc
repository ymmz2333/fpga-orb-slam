// PS software replacement of integer bit counting; matching decisions unchanged.
#include "ORBmatcher.h"
#include "Hamming256Neon.h"
namespace ORB_SLAM3 {
int ORBmatcher::DescriptorDistance(const cv::Mat& a,const cv::Mat& b) {
    return int(KvMatch::distance(a.ptr<uint8_t>(),b.ptr<uint8_t>()));
}
}
