#pragma once
#include "FpgaORB.h"
#include <mutex>
#include <cmath>
namespace ORB_SLAM3 {
// A frame comes from the camera-owning Zynq, with an already completed PL result.
// This adapter only validates/decodes; it has no CPU extractor or network request.
class BridgeFeatures:private FpgaORB {
    struct Context {std::mutex mutex;uint64_t stamp=0;uint32_t crc=0,count=0;bool consumed=true;std::vector<uint8_t> payload;};
    static Context& context(){static Context c;return c;}
public:
    static void arm(uint64_t stamp,uint32_t crc,uint32_t count,std::vector<uint8_t> payload){auto &c=context();std::lock_guard<std::mutex>l(c.mutex);
        require(c.consumed,"previous frame not consumed");require(stamp>c.stamp,"non-monotonic input timestamp");c.stamp=stamp;c.crc=crc;c.count=count;c.payload=std::move(payload);c.consumed=false;}
    static int consume(uint64_t stamp,const cv::Mat&image,ORBextractor *extractor,std::vector<cv::KeyPoint>&keys,cv::Mat&descriptors,double&wait_ms,double&decode_ms){
        auto &c=context();std::lock_guard<std::mutex>l(c.mutex);require(!c.consumed,"missing/already consumed physical frame");
        require(stamp==c.stamp,"SLAM/source integer timestamp mismatch");
        require(image.type()==CV_8UC1&&image.rows==720&&image.cols==960&&image.isContinuous(),"unaltered working gray required");
        require(orb_crc32(image.data,image.total())==c.crc,"SLAM input pixels differ from PL input");
        wait_ms=0;decode(c.payload,c.count,extractor,keys,descriptors,decode_ms);c.consumed=true;return int(c.count);
    }
};
} // namespace ORB_SLAM3
