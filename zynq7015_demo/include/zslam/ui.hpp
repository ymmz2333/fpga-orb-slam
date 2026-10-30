#pragma once
#include "slam.hpp"
#include "dense_environment.hpp"
#include <string>

namespace zslam {
struct Timings {double capture_ms=0,orb_ms=0,slam_ms=0,render_ms=0,present_ms=0,total_ms=0,fps=0,target_fps=30;uint64_t deadline_misses=0;bool physical=false,recorded=false,preview=false;double focus_score=0;};
struct GrayFrame {uint64_t id=0,timestamp_ns=0;unsigned width=960,height=720;std::vector<uint8_t> pixels;
    // Optional source MJPEG lease, selected before V4L2 QBUF; never re-encoded.
    std::vector<uint8_t> color_jpeg;};
struct SceneSnapshot {
    std::vector<PointView> points;
    std::vector<TrackSample> trajectory;
    std::size_t reserved_bytes=0;
    explicit SceneSnapshot(const Slam &slam):points(slam.points()),trajectory(slam.trajectory()),reserved_bytes(slam.reservedBytes()){}
    SceneSnapshot()=default;
};
struct DrawProfile {double image_cpu_ms=0,geometry_cpu_ms=0,labels_cpu_ms=0;uint64_t trajectory_hits=0,trajectory_misses=0;};
class Dashboard {
public:
    unsigned width=1280,height=720;std::vector<uint16_t> pixels;
    explicit Dashboard(bool trajectory_cache=false);
    void setDenseEnvironment(std::vector<DensePoint> points){dense_environment_=std::move(points);cloud_valid_=false;}
    std::size_t denseEnvironmentPoints()const{return dense_environment_.size();}
    void draw(const GrayFrame*,const Frame&,const Slam&,const Status&,const Timings&);
    void draw(const GrayFrame*,const Frame&,const SceneSnapshot&,const Status&,const Timings&);
    void savePpm(const std::string&)const;
    void demoBanner(const std::string &label){rect(0,696,1280,24,0x0861);text(12,700,label,0xffff,1);
        if(label.rfind("ERROR",0)==0||label.rfind("STOPPED",0)==0){rect(990,0,280,70,0x0861);text(1018,20,label.rfind("ERROR",0)==0?"ERROR":"STOPPED",0xf9a7,2);}}
    const DrawProfile &lastProfile()const{return profile_;}
    std::size_t trajectoryCacheBytes()const{return trajectory_pixels_.capacity()*sizeof(TrajectoryPixel);}
private:
    DrawProfile profile_;
    bool initialized_=false,preview_mode_=false;
    struct CloudPixel {int x,y;uint16_t color;};
    std::vector<PointView> cloud_cache_;
    std::vector<CloudPixel> cloud_pixels_;
    std::vector<DensePoint> dense_environment_;
    V3 eye_,forward_,right_,up_;double radius_=3;
    bool cloud_valid_=false;
    static constexpr unsigned trajectory_slots_=4096;
    struct TrajectoryPixel {uint64_t generation=0,frame=0,stamp=0;V3 center;int x=0,y=0;bool valid=false,visible=false;};
    std::vector<TrajectoryPixel> trajectory_pixels_;uint64_t projection_generation_=0;
    void pixel(int,int,uint16_t);
    void rect(int,int,int,int,uint16_t);
    void line(int,int,int,int,uint16_t);
    void text(int,int,const std::string&,uint16_t,int scale=1);
};
} // namespace zslam
