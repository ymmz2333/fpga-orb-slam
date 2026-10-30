// Compile a byte-preserved pre-B2 source snapshot in a distinct namespace.
// No design-candidate implementation is used by this reference.
#include "reference.h"
#include ORB_REFERENCE_CC
#ifndef ORB_CANDIDATE_LAPPING_UPPER
#define ORB_CANDIDATE_LAPPING_UPPER 1000
#endif
namespace ORB_SLAM3_REFERENCE {
class Access : public ORBextractor {
public:
    Access(): ORBextractor(1000,1.2f,8,20,7) {}
    using ORBextractor::pattern;
    using ORBextractor::umax;
};
}
int originalExtract(const cv::Mat& image,int n,float scale,int levels,int fast,int low,
                    std::vector<cv::KeyPoint>& keys,cv::Mat& descriptors) {
    ORB_SLAM3_REFERENCE::ORBextractor extractor(n,scale,levels,fast,low);
    // Use the actual MONOCULAR Frame ABI, not the stereo/no-overlap call.
    std::vector<int> overlap{0,ORB_CANDIDATE_LAPPING_UPPER};
    return extractor(image,cv::Mat(),keys,descriptors,overlap);
}
void originalDescribeAt(const cv::Mat& layer,std::vector<cv::KeyPoint> keys,cv::Mat& descriptors) {
    ORB_SLAM3_REFERENCE::Access original;
    for(auto& key:keys)
        key.angle=ORB_SLAM3_REFERENCE::IC_Angle(layer,key.pt,original.umax);
    cv::Mat working=layer.clone();
    cv::GaussianBlur(working,working,cv::Size(7,7),2,2,cv::BORDER_REFLECT_101);
    ORB_SLAM3_REFERENCE::computeDescriptors(working,keys,descriptors,original.pattern);
}
