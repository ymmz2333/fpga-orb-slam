#pragma once
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <cstdlib>
#include <cmath>
#include <stdexcept>

namespace ORB_SLAM3 {
inline size_t DenseFilterFeatures(std::vector<cv::KeyPoint>& keys,cv::Mat& descriptors,const std::vector<float>& scales) {
    const char* path=std::getenv("ORB60_VALID_MASK");
    if(!path || !*path)return keys.size();
    static const cv::Mat integral=[&]() {
        cv::Mat mask=cv::imread(path,cv::IMREAD_GRAYSCALE),sum;
        if(mask.rows!=720 || mask.cols!=960)throw std::runtime_error("Invalid FPGA feature validity mask");
        cv::compare(mask,0,mask,cv::CMP_GT);
        cv::integral(mask,sum,CV_32S);
        return sum;
    }();
    size_t keep=0;
    for(size_t i=0;i<keys.size();++i) {
        const auto& key=keys[i];
        if(key.octave<0 || size_t(key.octave)>=scales.size())throw std::runtime_error("Invalid feature octave");
        const int r=int(std::ceil(31.f*scales[key.octave]));
        const int x=int(std::floor(key.pt.x)),y=int(std::floor(key.pt.y));
        const int x0=x-r,y0=y-r,x1=x+r+1,y1=y+r+1;
        if(x0<0 || y0<0 || x1>960 || y1>720)continue;
        const int sum=integral.at<int>(y1,x1)-integral.at<int>(y1,x0)-integral.at<int>(y0,x1)+integral.at<int>(y0,x0);
        if(sum!=255*(x1-x0)*(y1-y0))continue;
        if(keep!=i) {keys[keep]=key;descriptors.row(int(i)).copyTo(descriptors.row(int(keep)));}
        ++keep;
    }
    keys.resize(keep);
    if(keep)descriptors=descriptors.rowRange(0,int(keep)).clone();else descriptors.release();
    return keep;
}
} // namespace ORB_SLAM3
