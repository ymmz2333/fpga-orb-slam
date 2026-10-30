#ifndef ORB_SLAM3_FEATURE_IO_H
#define ORB_SLAM3_FEATURE_IO_H
#include <cstdint>
#include <string>
#include <vector>
#include <opencv2/core.hpp>
#include <opencv2/features2d.hpp>
namespace ORB_SLAM3 {
class ORBextractor;
struct FeatureIOStats {
    uint64_t timestamp_ns=0;
    int role=-1, count=0, extractor_calls=0;
    double read_ms=0, decode_ms=0, native_ms=0, dump_ms=0, auxiliary_ms=0;
};
class FeatureIO {
public:
    static void Configure(const std::string& mode,const std::string& directory);
    static bool Active();
    static void Begin(uint64_t timestamp_ns);
    static void SetExtractors(ORBextractor* normal,ORBextractor* initialization);
    static FeatureIOStats Stats();
    static int Process(ORBextractor* extractor,const cv::Mat& image,std::vector<cv::KeyPoint>& keys,
                       cv::Mat& descriptors,std::vector<int>& lapping);
    // Also used by a bounded codec fixture test; never changes feature values.
    static void SavePacket(const std::string& path,const std::string& memory_path,uint64_t timestamp_ns,
                           int role,int width,int height,ORBextractor* extractor,int mono_left,
                           const std::vector<cv::KeyPoint>& keys,const cv::Mat& descriptors);
    static int LoadPacket(const std::string& path,uint64_t timestamp_ns,int role,int width,int height,
                          ORBextractor* extractor,std::vector<cv::KeyPoint>& keys,cv::Mat& descriptors,
                          double& read_ms,double& decode_ms);
};
}
#endif
