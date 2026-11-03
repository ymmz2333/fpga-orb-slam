// KV260 PS native camera input; existing FeatureIO still owns actual7015 PL.
#pragma once
#include "Kv260VideoPipeline.h"
#include "v4l2_capture.h"
#include <linux/videodev2.h>
#include <limits>
#include <cmath>

namespace KvNetwork {
struct CameraFrame:VideoFrame {struct orb_camera_frame sensor{};};
inline void validateCameraCalibration(const std::string& source,const std::string& yaml) {
    std::ifstream in(source);std::string header,line,extra;
    if(!std::getline(in,header)||header!="width,height,fx,fy,cx,cy,d0,d1,d2,d3,d4"||!std::getline(in,line))
        throw std::runtime_error("Exact source-camera CSV required");
    if(std::getline(in,extra))throw std::runtime_error("One source calibration row required");
    std::istringstream values(line);double v[11];
    for(unsigned i=0;i<11;i++){char comma=0;if(!(values>>v[i])||!std::isfinite(v[i]))throw std::runtime_error("Invalid camera scalar");
        if(i<10&&(!(values>>comma)||comma!=','))throw std::runtime_error("Invalid camera CSV delimiter");}
    values>>std::ws;if(!values.eof()||v[0]!=1280||v[1]!=720||v[2]<=0||v[3]<=0)throw std::runtime_error("Exact1280x720 source calibration required");
    cv::FileStorage y(yaml,cv::FileStorage::READ);
    if(!y.isOpened()||std::string(y["Camera.type"])!="PinHole")throw std::runtime_error("Pinhole YAML required");
    const char* names[]={"width","height","fx","fy","cx","cy","k1","k2","p1","p2","k3"};
    v[0]=960;v[4]-=160;
    for(unsigned i=0;i<11;i++){
        auto n=y[std::string("Camera.")+names[i]];
        if(n.empty()||std::abs(double(n)-v[i])>1e-10)throw std::runtime_error("Source camera / working YAML geometry mismatch");}
    if(double(y["Camera.fps"])!=60)throw std::runtime_error("This camera entry requires explicit60FPS negotiated profile");
}
class CameraPipeline {
    std::mutex mutex;std::condition_variable changed;std::deque<CameraFrame> ready;
    std::thread producer;bool stopped=false,done=false;std::exception_ptr failure;
public:
    CameraPipeline(const std::string& device,size_t frames,const std::string& report) {
        if(device.compare(0,10,"/dev/video")||!frames)throw std::runtime_error("Finite actual V4L2 device input required");
        ORB_SLAM3::FeatureIO::StartPipeline();
        producer=std::thread([this,device,frames,report]{void* camera=nullptr;try {
            char error[2048]={};camera=orb_camera_open(device.c_str(),V4L2_PIX_FMT_YUYV,60,error,sizeof(error));
            if(!camera)throw std::runtime_error(error);
            struct orb_camera_info p{};
            if(orb_camera_info(camera,&p)||p.colorspace!=V4L2_COLORSPACE_SRGB||
               (p.ycbcr_encoding!=0&&p.ycbcr_encoding!=V4L2_YCBCR_ENC_601)||
               (p.quantization!=0&&p.quantization!=V4L2_QUANTIZATION_LIM_RANGE))throw std::runtime_error("Unsupported packed camera colorimetry");
            for(size_t i=0;i<frames;i++) {
                {std::unique_lock<std::mutex> l(mutex);changed.wait(l,[&]{return stopped||ready.size()<1;});if(stopped)break;}
                const auto began=std::chrono::steady_clock::now();CameraFrame f;cv::Mat packed(720,960,CV_8UC2);f.gray.create(720,960,CV_8UC1);
                if(orb_camera_read(camera,packed.data,packed.total()*2,f.gray.data,f.gray.total(),&f.sensor,3000,error,sizeof(error)))throw std::runtime_error(error);
                f.id={i,f.sensor.timestamp_ns,orb_crc32(f.gray.data,f.gray.total())};
                cv::cvtColor(packed,f.bgr,cv::COLOR_YUV2BGR_YUY2);
                f.decode_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-began).count();
                ORB_SLAM3::FeatureIO::QueueFrame(f.id.stamp,f.gray);
                {std::lock_guard<std::mutex> l(mutex);if(stopped)break;ready.push_back(std::move(f));changed.notify_all();}
            }
            char json[2048];if(orb_camera_profile(camera,json,sizeof(json)))throw std::runtime_error("Camera profile failed");
            std::ofstream out(report);out<<json<<'\n';out.close();if(!out)throw std::runtime_error("Camera profile write failed");
            void* owned=camera;camera=nullptr;if(orb_camera_close(owned))throw std::runtime_error("Camera STREAMOFF failed");
        }catch(...){if(camera)orb_camera_close(camera);std::lock_guard<std::mutex> l(mutex);failure=std::current_exception();}
        std::lock_guard<std::mutex> l(mutex);done=true;changed.notify_all();});
    }
    CameraFrame get(size_t index) {
        std::unique_lock<std::mutex> l(mutex);changed.wait(l,[&]{return failure||done||!ready.empty();});
        if(failure)std::rethrow_exception(failure);
        if(ready.empty()||ready.front().id.index!=index)throw std::runtime_error("Camera/FPGA sampled-frame sequence mismatch");
        auto f=std::move(ready.front());ready.pop_front();changed.notify_all();return f;
    }
    void finish(){if(producer.joinable())producer.join();if(failure)std::rethrow_exception(failure);ORB_SLAM3::FeatureIO::FinishPipeline();}
    ~CameraPipeline(){ {std::lock_guard<std::mutex> l(mutex);stopped=true;changed.notify_all();}
        ORB_SLAM3::FeatureIO::AbortPipeline();if(producer.joinable())producer.join();}
};
}
