// Include once, in the isolated Tracking.cc; no public Tracking/System ABI changes.
#pragma once
#include "BridgeTrackingDiagnostics.h"
#include <cmath>
#include <iomanip>

namespace ORB_SLAM3 { namespace BridgeDiag {
namespace {
struct Event {const char* stage=nullptr;unsigned count=0;std::array<Field,24> fields;};
struct Store {
    bool enabled=false;uint64_t frame=0,stamp=0;unsigned count=0,used=0,dropped=0;
    std::array<unsigned,8> levels{};std::array<unsigned,32> angles{};
    std::array<Event,128> events;
};
thread_local Store trace;
uint32_t read32(const uint8_t*p){return uint32_t(p[0])|(uint32_t(p[1])<<8)|(uint32_t(p[2])<<16)|(uint32_t(p[3])<<24);}
}
bool active(){return trace.enabled;}
void begin(uint64_t frame,uint64_t stamp,unsigned count,const uint8_t*records){
    if(!stamp||count>1000||(!records&&count))throw std::runtime_error("Invalid diagnostic frame");
    trace.enabled=true;trace.frame=frame;trace.stamp=stamp;trace.count=count;trace.used=trace.dropped=0;
    trace.levels.fill(0);trace.angles.fill(0);
    for(unsigned i=0;i<count;++i){auto level=read32(records+64*i+12),bin=read32(records+64*i+16);
        if(level>=8||bin>=32)throw std::runtime_error("Invalid diagnostic PL level/angle");
        ++trace.levels[level];++trace.angles[bin];}
}
void event(const char*stage,std::initializer_list<Field> fields){
    if(!trace.enabled)return;
    if(trace.used==trace.events.size()||fields.size()>24){++trace.dropped;return;}
    auto&e=trace.events[trace.used++];e.stage=stage;e.count=unsigned(fields.size());
    unsigned n=0;for(const auto&field:fields)e.fields[n++]=field;
}
bool decision(const char*stage,bool accepted,int matches,int inliers){
    event(stage,{{"accepted",accepted?1.:0.},{"matches",matches},{"inliers",inliers}});return accepted;
}
void writeFrame(std::ostream&out,int state,const double*pose){
    if(!trace.enabled)throw std::runtime_error("Missing diagnostic frame begin");
    out<<std::setprecision(17)<<"{\"schema\":1,\"source_frame_id\":"<<trace.frame<<",\"timestamp_ns\":"<<trace.stamp
       <<",\"features\":"<<trace.count<<",\"tracking_state\":"<<state<<",\"levels\":[";
    for(unsigned i=0;i<8;++i){if(i)out<<',';out<<trace.levels[i];}out<<"],\"angle_bins\":[";
    for(unsigned i=0;i<32;++i){if(i)out<<',';out<<trace.angles[i];}out<<"],\"tcw\":";
    if(pose){out<<'[';for(unsigned i=0;i<12;++i){if(i)out<<',';if(std::isfinite(pose[i]))out<<pose[i];else out<<"null";}out<<']';}
    else out<<"null";
    out<<",\"events_dropped\":"<<trace.dropped<<",\"events\":[";
    for(unsigned i=0;i<trace.used;++i){if(i)out<<',';auto&e=trace.events[i];out<<"{\"stage\":\""<<e.stage<<'"';
        for(unsigned k=0;k<e.count;++k){const auto&f=e.fields[k];out<<",\""<<f.first<<"\":";if(std::isfinite(f.second))out<<f.second;else out<<"null";}out<<'}';}
    out<<"]}\n";trace.enabled=false;
}
} }
