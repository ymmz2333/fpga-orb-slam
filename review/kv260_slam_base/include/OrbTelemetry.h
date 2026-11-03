// GPL-3.0-or-later. Optional read-only display telemetry, never an ORB producer.
#ifndef ORB_SLAM3_ORB_TELEMETRY_H
#define ORB_SLAM3_ORB_TELEMETRY_H
#include "System.h"
#include "FeatureIO.h"
#include "Orb60Protocol.h"
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <memory>
#include <mutex>
#include <sstream>
#include <sys/stat.h>
#include <thread>
namespace ORB_SLAM3 {
struct OrbVizFeature {float x,y;int octave;bool mapped;};
struct OrbVizPoint {uint64_t id;Eigen::Vector3f xyz;};
struct OrbVizCamera {EIGEN_MAKE_ALIGNED_OPERATOR_NEW uint64_t id;Eigen::Matrix4f twc;};
struct OrbTelemetryData {
    unsigned long map_id=0;int state=0;bool map_full=false;
    std::vector<OrbVizFeature> features;
    std::vector<OrbVizPoint> points;
    std::vector<OrbVizCamera,Eigen::aligned_allocator<OrbVizCamera>> keyframes;
};
class OrbTelemetry {
    using Clock=std::chrono::steady_clock;
    struct Frame {
        EIGEN_MAKE_ALIGNED_OPERATOR_NEW
        OrbTelemetryData data;cv::Mat image;Eigen::Matrix4f twc;
        uint64_t index=0,timestamp=0;FeatureIOStats stats;
        double track_ms=0,fps=0;
    };
    std::string directory;bool recording=false,stopping=false;
    std::mutex mutex;std::condition_variable changed;std::thread worker;
    std::unique_ptr<Frame> pending;
    Clock::time_point previous,previous_map,next_capture;uint64_t previous_index=0;
    std::chrono::nanoseconds capture_period{33333333};
    uint64_t written=0;std::atomic<uint64_t> replaced{0};
    static void check(bool ok,const std::string& why){if(!ok)throw std::runtime_error("OrbTelemetry: "+why);}
    void status(const char *state) {
        std::ofstream f(directory+"/status.json.tmp");
        f<<"{\"state\":\""<<state<<"\",\"written\":"<<written<<",\"replaced\":"<<replaced.load()<<"}\n";
        f.close();std::rename((directory+"/status.json.tmp").c_str(),(directory+"/status.json").c_str());
    }
    static void append32(std::vector<uint8_t>& out,uint32_t v){size_t n=out.size();out.resize(n+4);orb_put32(out.data()+n,v);}
    static void append64(std::vector<uint8_t>& out,uint64_t v){size_t n=out.size();out.resize(n+8);orb_put64(out.data()+n,v);}
    static void real(std::vector<uint8_t>& out,float v){uint32_t bits;std::memcpy(&bits,&v,4);append32(out,bits);}
    void write(Frame& f) {
        std::vector<uint8_t> jpeg;check(cv::imencode(".jpg",f.image,jpeg,{cv::IMWRITE_JPEG_QUALITY,80}),"JPEG encode");
        cv::Mat gray;if(f.image.channels()==1)gray=f.image;else cv::cvtColor(f.image,gray,cv::COLOR_BGR2GRAY);
        if(!gray.isContinuous())gray=gray.clone();
        std::ostringstream s;s<<std::setprecision(9);
        s<<"{\"schema\":1,\"frame_index\":"<<f.index<<",\"timestamp_ns\":"<<f.timestamp
         <<",\"map_id\":"<<f.data.map_id<<",\"state\":"<<f.data.state
         <<",\"width\":"<<f.image.cols<<",\"height\":"<<f.image.rows
         <<",\"source_gray\":"<<(f.image.channels()==1?"true":"false")
         <<",\"source\":\""<<(FeatureIO::FPGAActive()?"fpga":"cpu")<<"\",\"map_full\":"<<(f.data.map_full?"true":"false")
         <<",\"raw_gray_crc\":"<<orb_crc32(gray.data,gray.total())
         <<",\"pose_valid\":"<<(f.data.state==2&&f.twc.allFinite()?"true":"false")
         <<",\"processing_fps\":"<<f.fps<<",\"track_ms\":"<<f.track_ms
         <<",\"feature_wait_ms\":"<<f.stats.read_ms<<",\"decode_ms\":"<<f.stats.decode_ms
         <<",\"feature_count\":"<<f.stats.count<<",\"cpu_orb_calls\":"<<f.stats.extractor_calls
         <<",\"display_replaced\":"<<replaced.load()<<",\"pose_twc\":[";
        for(int r=0;r<4;++r)for(int c=0;c<4;++c){if(r||c)s<<',';s<<f.twc(r,c);}
        s<<"],\"features\":[";
        for(size_t i=0;i<f.data.features.size();++i){const auto& k=f.data.features[i];if(i)s<<',';
            s<<'['<<k.x<<','<<k.y<<','<<k.octave<<','<<(k.mapped?1:0)<<']';}
        s<<"]}";const std::string json=s.str();
        std::vector<uint8_t> body(json.begin(),json.end());body.insert(body.end(),jpeg.begin(),jpeg.end());
        for(const auto& p:f.data.points){append64(body,p.id);for(int i=0;i<3;++i)real(body,p.xyz[i]);}
        for(const auto& k:f.data.keyframes){append64(body,k.id);for(int r=0;r<4;++r)for(int c=0;c<4;++c)real(body,k.twc(r,c));}
        uint8_t header[32]={};std::memcpy(header,"ORBVIZ01",8);orb_put32(header+8,1);
        orb_put32(header+12,unsigned(json.size()));orb_put32(header+16,unsigned(jpeg.size()));
        orb_put32(header+20,unsigned(f.data.points.size()));orb_put32(header+24,unsigned(f.data.keyframes.size()));
        orb_put32(header+28,orb_crc32(body.data(),body.size()));
        auto save=[&](const std::string& path){
            std::ofstream out(path,std::ios::binary|std::ios::trunc);out.write(reinterpret_cast<char*>(header),32);
            out.write(reinterpret_cast<const char*>(body.data()),std::streamsize(body.size()));out.close();check(bool(out),"snapshot write");
        };
        save(directory+"/latest.orbv.tmp");
        check(std::rename((directory+"/latest.orbv.tmp").c_str(),(directory+"/latest.orbv").c_str())==0,"atomic snapshot rename");
        if(recording){std::ostringstream name;name<<directory<<"/frames/"<<std::setw(8)<<std::setfill('0')<<f.index<<".orbv";save(name.str());}
        ++written;
    }
    void loop() {
        try {
            for(;;) {
                std::unique_ptr<Frame> f;
                {std::unique_lock<std::mutex> lock(mutex);changed.wait(lock,[&]{return stopping||bool(pending);});
                 if(!pending)break;f=std::move(pending);}
                write(*f);
            }
            status("COMPLETED");
        }catch(const std::exception& e){std::cerr<<e.what()<<std::endl;status("ERROR");}
    }
public:
    OrbTelemetry(const std::string& path,bool record):directory(path),recording(record) {
        double fps=30;
        if(const char* value=std::getenv("ORB60_VIEWER_FPS")) {
            char* end=nullptr;fps=std::strtod(value,&end);
            check(end!=value&&*end=='\0'&&std::isfinite(fps)&&fps>=1&&fps<=60,"display FPS must be1..60");
        }
        capture_period=std::chrono::nanoseconds(static_cast<int64_t>(1e9/fps));
        check(mkdir(directory.c_str(),0755)==0||errno==EEXIST,"output directory");
        if(recording)check(mkdir((directory+"/frames").c_str(),0755)==0||errno==EEXIST,"record directory");
        (void)orb_crc32(nullptr,0);previous=Clock::now()-std::chrono::seconds(1);previous_map=previous;next_capture=Clock::now();
        status("RUNNING");worker=std::thread(&OrbTelemetry::loop,this);
    }
    ~OrbTelemetry(){finish();}
    void capture(System& slam,const cv::Mat& image,const Sophus::SE3f& tcw,uint64_t index,
                 uint64_t timestamp,const FeatureIOStats& stats,double track_ms,bool force=false) {
        auto now=Clock::now();double elapsed=std::chrono::duration<double>(now-previous).count();
        if(!force&&now<next_capture)return;
        do {next_capture+=capture_period;} while(next_capture<=now);
        auto f=std::unique_ptr<Frame>(new Frame);bool include_map=force||std::chrono::duration<double>(now-previous_map).count()>=.5;
        slam.GetVisualizationSnapshot(f->data,include_map);
        f->image=image.clone();f->twc=tcw.inverse().matrix();
        if(!f->twc.allFinite()){f->twc.setIdentity();f->data.state=0;}
        f->index=index;f->timestamp=timestamp;f->stats=stats;f->track_ms=track_ms;
        f->fps=index>previous_index?double(index-previous_index)/elapsed:0;
        if(f->data.map_full)previous_map=now;previous=now;previous_index=index;
        {std::lock_guard<std::mutex> lock(mutex);
         // Do not overwrite the only pending complete map with an image-only update.
         if(pending&&pending->data.map_id==f->data.map_id&&pending->data.map_full&&!f->data.map_full) {
             f->data.points=std::move(pending->data.points);f->data.keyframes=std::move(pending->data.keyframes);f->data.map_full=true;
         }
         if(pending)++replaced;pending=std::move(f);changed.notify_one();}
    }
    void finish(){if(!worker.joinable())return;{std::lock_guard<std::mutex> lock(mutex);stopping=true;changed.notify_all();}worker.join();}
};
}
#endif
