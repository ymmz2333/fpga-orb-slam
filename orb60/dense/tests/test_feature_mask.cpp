#include <opencv2/opencv.hpp>
#include <vector>
#include <iostream>
#include <cstdlib>
#include "DenseFeatureMask.h"
void require(bool ok) {if(!ok)throw std::runtime_error("Feature mask regression failed");}
int main(int argc,char** argv) {
    if(argc!=2)return 2;
    std::vector<float> scales={1,1.2f,1.44f,1.728f,2.0736f,2.48832f,2.985984f,3.583181f};
    std::vector<cv::KeyPoint> keys;
    for(auto xy : std::vector<cv::Point2f>{{110,300},{400,300},{700,300},{200,300},{400,400}})
        keys.emplace_back(xy,31);
    keys[3].octave=7;keys[4].octave=7;
    cv::Mat descriptors(5,32,CV_8U);
    for(int i=0;i<5;++i)descriptors.row(i).setTo(i+10);
    unsetenv("ORB60_VALID_MASK");
    require(ORB_SLAM3::DenseFilterFeatures(keys,descriptors,scales)==5);
    cv::Mat mask=cv::Mat::zeros(720,960,CV_8U);
    mask(cv::Rect(100,100,760,520)).setTo(255);
    mask(cv::Rect(695,295,10,10)).setTo(0);
    std::string path=std::string(argv[1])+"/feature-mask.png";
    require(cv::imwrite(path,mask));setenv("ORB60_VALID_MASK",path.c_str(),1);
    require(ORB_SLAM3::DenseFilterFeatures(keys,descriptors,scales)==2);
    require(keys[0].pt==cv::Point2f(400,300)&&keys[1].pt==cv::Point2f(400,400));
    require(descriptors.rows==2&&descriptors.at<unsigned char>(0,0)==11&&descriptors.at<unsigned char>(1,0)==14);
    keys.clear();descriptors.release();
    require(ORB_SLAM3::DenseFilterFeatures(keys,descriptors,scales)==0&&descriptors.empty());
    std::cout<<"FEATURE_MASK_PASS default footprint octave order descriptors empty"<<std::endl;
}
