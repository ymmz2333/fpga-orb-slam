// Transport-only synthetic gate. Uses real adapter and ORBextractor configuration.
#include "FpgaPipeline.h"
#include <chrono>
#include <thread>
int main(int argc,char **argv) {
    if(argc!=2)return 2;
    try {
        ORB_SLAM3::ORBextractor extractor(1000,1.2f,8,20,7);
        ORB_SLAM3::FpgaPipeline pipeline(argv[1]);
        std::thread producer([&]{
            try {
                for(unsigned i=1;i<=24;++i) {
                    cv::Mat image(720,960,CV_8UC1,cv::Scalar(i));pipeline.submit(1000+i,image);
                    image.setTo(cv::Scalar(99)); // queued pixels must be independently owned.
                }
            }catch(...) {} // Consumer observes the same transport exception.
        });
        try {
            for(unsigned i=1;i<=24;++i) {
                std::vector<cv::KeyPoint> keys;cv::Mat descriptors;double wait=0,decode=0;
                int n=pipeline.consume(1000+i,i%2,&extractor,keys,descriptors,wait,decode);
                if(n!=1||keys.size()!=1||keys[0].pt!=cv::Point2f(100,80)||keys[0].octave!=0
                   ||keys[0].angle!=float((i%32)*737280u)/65536.f)throw std::runtime_error("decoded keypoint mismatch");
                for(unsigned j=0;j<32;++j)if(descriptors.ptr(0)[j]!=uint8_t(i+j))throw std::runtime_error("descriptor mismatch");
                std::this_thread::sleep_for(std::chrono::milliseconds(3));
            }
            pipeline.finish();producer.join();std::cout<<"SYNTHETIC_CPP_PIPELINE_EXACT_PASS"<<std::endl;
        }catch(...) {pipeline.abort();producer.join();throw;}
        return 0;
    }catch(const std::exception& e){std::cerr<<"PIPELINE_REJECTED "<<e.what()<<std::endl;return 23;}
}
