// GPL-3.0-or-later. Bounded original-video decode -> real 7015 ORB pipeline.
#pragma once
#include "FeatureIO.h"
#include "Orb60Protocol.h"
#include "PackedYuvSource.h"
#include <opencv2/videoio.hpp>
#include <opencv2/imgproc.hpp>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <exception>
#include <fstream>
#include <mutex>
#include <memory>
#include <sstream>
#include <thread>
#include <sys/stat.h>
#include <unistd.h>

namespace KvNetwork {
struct Identity {uint64_t index,stamp;uint32_t crc;};
inline std::vector<Identity> identities(const std::string& file,size_t limit=0) {
    std::ifstream in(file);std::string line;std::getline(in,line);
    if(line!="source_frame_id,timestamp_ns,gray_crc")throw std::runtime_error("Video identity header mismatch");
    std::vector<Identity> result;
    while(std::getline(in,line)) {
        std::istringstream s(line);Identity row;char a,b;
        if(!(s>>row.index>>a>>row.stamp>>b>>row.crc)||a!=','||b!=','||row.index!=result.size()||
           !row.stamp||(!result.empty()&&row.stamp<=result.back().stamp))throw std::runtime_error("Video integer identity order/shape mismatch");
        s>>std::ws;if(!s.eof())throw std::runtime_error("Extra video identity fields");
        result.push_back(row);if(limit&&result.size()==limit)break;
    }
    if(result.empty()||(limit&&result.size()!=limit))throw std::runtime_error("Incomplete video identities");
    return result;
}
struct VideoFrame {Identity id;cv::Mat bgr,gray;double decode_ms=0;};
class VideoSource {
    cv::VideoCapture video;std::ifstream pipe;bool piped=false,paired=false;std::unique_ptr<PackedYuvSource> packed;
public:
    explicit VideoSource(const std::string& path) {
        if(path.compare(0,5,"yuyv:")==0||path.compare(0,5,"uyvy:")==0){packed.reset(new PackedYuvSource(path.substr(5),path.compare(0,5,"uyvy:")==0));return;}
        paired=path.compare(0,7,"paired:")==0;piped=paired||path.compare(0,5,"pipe:")==0;
        if(piped){const auto name=path.substr(paired?7:5);struct stat info{};
            if(lstat(name.c_str(),&info)||!S_ISFIFO(info.st_mode))throw std::runtime_error("Explicit raw-video input must be an existing FIFO");
            if(paired&&info.st_uid!=getuid())throw std::runtime_error("Paired FIFO must belong to current user");
            pipe.open(name,std::ios::binary);if(!pipe)throw std::runtime_error("Cannot open owned video FIFO");
        }else if(!video.open(path,cv::CAP_FFMPEG))throw std::runtime_error("Cannot open original video decoder");
    }
    bool read(cv::Mat& bgr,cv::Mat* gray=nullptr,const Identity* expected=nullptr) {
        if(packed){cv::Mat unused;return packed->read(bgr,gray?*gray:unused,expected!=nullptr,expected?expected->index:0,expected?expected->stamp:0,expected?expected->crc:0);}
        if(!piped)return video.read(bgr);
        uint8_t header[32]={};
        if(paired) {
            pipe.read(reinterpret_cast<char*>(header),32);const auto received=pipe.gcount();
            if(received==0&&pipe.eof())return false;
            if(received!=32||std::memcmp(header,"ORBPAIR1",8))throw std::runtime_error("Invalid/truncated paired-video header");
            if(!gray||!expected||orb_get64(header+8)!=expected->index||orb_get64(header+16)!=expected->stamp||orb_get32(header+28)!=expected->crc)
                throw std::runtime_error("Paired source frame/timestamp/gray identity mismatch");
        }
        bgr.create(720,960,CV_8UC3);const auto size=bgr.total()*bgr.elemSize();
        pipe.read(reinterpret_cast<char*>(bgr.data),size);const auto received=pipe.gcount();
        if(received==0&&pipe.eof())return false;
        if(received!=std::streamsize(size))throw std::runtime_error("Truncated original RGB frame from decoder FIFO");
        if(paired) {
            if(orb_crc32(bgr.data,size)!=orb_get32(header+24))throw std::runtime_error("Paired RGB CRC mismatch");
            gray->create(720,960,CV_8UC1);pipe.read(reinterpret_cast<char*>(gray->data),gray->total());
            if(pipe.gcount()!=std::streamsize(gray->total()))throw std::runtime_error("Truncated paired original gray frame");
        }
        return true;
    }
};
inline VideoFrame decode(VideoSource& capture,Identity id) {
    const auto start=std::chrono::steady_clock::now();VideoFrame f;f.id=id;
    if(!capture.read(f.bgr,&f.gray,&id)||f.bgr.type()!=CV_8UC3||f.bgr.rows!=720||f.bgr.cols!=960)
        throw std::runtime_error("Original video must decode exactly to 960x720 BGR8; no implicit resize");
    if(f.gray.empty())cv::cvtColor(f.bgr,f.gray,cv::COLOR_BGR2GRAY);
    if(orb_crc32(f.gray.data,f.gray.total())!=id.crc)
        throw std::runtime_error("Native decoder gray differs from frozen source frame "+std::to_string(id.index));
    f.decode_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();return f;
}
class VideoPipeline {
    std::mutex mutex;std::condition_variable changed;std::deque<VideoFrame> ready;
    std::thread producer;bool stopped=false,done=false;std::exception_ptr failure;
public:
    VideoPipeline(const std::string& video,const std::vector<Identity>& ids,bool entire) {
        ORB_SLAM3::FeatureIO::StartPipeline();
        producer=std::thread([this,video,ids,entire]{try {
            VideoSource capture(video);
            for(const auto& id:ids) {
                {std::unique_lock<std::mutex> l(mutex);changed.wait(l,[&]{return stopped||ready.size()<3;});if(stopped)return;}
                auto f=decode(capture,id);ORB_SLAM3::FeatureIO::QueueFrame(id.stamp,f.gray);
                {std::lock_guard<std::mutex> l(mutex);if(stopped)return;ready.push_back(std::move(f));changed.notify_all();}
            }
            cv::Mat extra;if(entire&&capture.read(extra))throw std::runtime_error("Video has more frames than frozen identities");
        }catch(...){std::lock_guard<std::mutex> l(mutex);failure=std::current_exception();}
        std::lock_guard<std::mutex> l(mutex);done=true;changed.notify_all();});
    }
    VideoFrame get(size_t index) {
        std::unique_lock<std::mutex> l(mutex);changed.wait(l,[&]{return failure||done||!ready.empty();});
        if(failure)std::rethrow_exception(failure);
        if(ready.empty()||ready.front().id.index!=index)throw std::runtime_error("Video/FPGA source frame sequence mismatch");
        auto f=std::move(ready.front());ready.pop_front();changed.notify_all();return f;
    }
    void finish(){if(producer.joinable())producer.join();if(failure)std::rethrow_exception(failure);ORB_SLAM3::FeatureIO::FinishPipeline();}
    ~VideoPipeline(){ {std::lock_guard<std::mutex> l(mutex);stopped=true;changed.notify_all();}
        ORB_SLAM3::FeatureIO::AbortPipeline();if(producer.joinable())producer.join();}
};
}
