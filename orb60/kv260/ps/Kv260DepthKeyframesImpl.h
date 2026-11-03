#pragma once
#include "Kv260DepthKeyframes.h"
#include "KeyFrame.h"
#include "MapPoint.h"
#include "Map.h"
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <set>
#include <sstream>
#include <stdexcept>

namespace KvDepth {
namespace {
struct Context {
    uint64_t frame=0, stamp=0, last_selected_stamp=0, last_map=~uint64_t(0);
    uint32_t crc=0;
    bool armed=false, selected=false;
};
thread_local Context current;
}
bool enabled() {const char* p=std::getenv("ORB60_KV260_KEYFRAME_DEPTH");return p&&std::string(p)=="1";}
void begin(uint64_t frame,uint64_t stamp,uint32_t crc) {
    current.frame=frame;current.stamp=stamp;current.crc=crc;current.armed=true;current.selected=false;
}
void publish(ORB_SLAM3::KeyFrame* key) {
    if(!enabled()||!current.armed||!key||key->isBad())return;
    if(std::abs(key->mTimeStamp*1e9-double(current.stamp))>1.)
        throw std::runtime_error("Depth keyframe timestamp differs from current PL input");
    const char* folder=std::getenv("ORB60_BRIDGE_COLOR_POSES");
    if(!folder)throw std::runtime_error("Keyframe depth output directory is absent");
    const uint64_t mid=key->GetMap()->GetId();
    uint64_t interval=1000000000;
    if(const char* value=std::getenv("ORB60_KV260_DEPTH_INTERVAL_NS")) {
        std::string text(value);size_t used=0;interval=std::stoull(text,&used);
        if(used!=text.size()||interval<100000000||interval>60000000000ULL)
            throw std::runtime_error("Invalid depth source sampling interval");
    }
    if(mid==current.last_map&&current.last_selected_stamp&&current.stamp-current.last_selected_stamp<interval)return;
    const auto tcw=key->GetPose();const auto twc=tcw.inverse().matrix();
    if(!twc.allFinite())return;
    const auto points=key->GetMapPointMatches();
    std::set<unsigned long>seen;std::ostringstream observations;observations<<std::setprecision(17);unsigned count=0;
    for(size_t i=0;i<points.size()&&i<key->mvKeysUn.size();++i) {
        auto* point=points[i];
        if(!point||point->isBad()||point->Observations()<3||!seen.insert(point->mnId).second)continue;
        auto xyz=point->GetWorldPos();auto q=tcw*xyz;
        if(!xyz.allFinite()||q.z()<=1e-6f)continue;
        if(count++)observations<<',';
        observations<<'['<<key->mvKeysUn[i].pt.x<<','<<key->mvKeysUn[i].pt.y<<','<<xyz.x()<<','<<xyz.y()<<','<<xyz.z()<<','<<point->mnId<<']';
    }
    if(count<20)return;
    std::ostringstream out;out<<std::setprecision(17)<<"{\"map_id\":"<<mid<<",\"keyframe_id\":"<<key->mnId
        <<",\"source_frame_id\":"<<current.frame<<",\"timestamp_ns\":"<<current.stamp
        <<",\"gray_crc\":"<<current.crc<<",\"anchor_kind\":\"slam_keyframe\",\"twc\":[";
    for(int r=0;r<4;++r){if(r)out<<',';out<<'[';for(int c=0;c<4;++c){if(c)out<<',';out<<twc(r,c);}out<<']';}
    out<<"],\"observations\":["<<observations.str()<<"]}\n";
    const std::string path=std::string(folder)+"/f"+std::to_string(current.frame)+".json";
    std::ofstream file(path+".part");file<<out.str();file.close();
    if(!file||std::rename((path+".part").c_str(),path.c_str()))throw std::runtime_error("Cannot persist depth keyframe");
    current.selected=true;current.last_selected_stamp=current.stamp;current.last_map=mid;
}
std::string ack() {return enabled()?std::string("{\"depth_keyframe_selected\":")+(current.selected?"true}":"false}"):"";}
}
