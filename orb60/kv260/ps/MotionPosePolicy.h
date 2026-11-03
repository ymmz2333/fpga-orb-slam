// Private PS candidate: defer the preliminary solve only for strong mono matches.
// The unchanged final local-map solve must acknowledge every deferral.
#pragma once
#include <cstdlib>
#include <cstdio>
#include <fstream>
#include <string>
#include <stdexcept>
namespace KvMotionPose {
inline bool enabled(){static const bool value=std::getenv("ORB60_MOTION_POSE_POLICY")&&std::string(std::getenv("ORB60_MOTION_POSE_POLICY"))=="defer-strong";return value;}
inline bool eligible(bool mono,bool only_tracking,bool tracking_ok,int previous_inliers,int matches){return mono&&!only_tracking&&tracking_ok&&previous_inliers>=80&&matches>=100;}
struct Counters {
    unsigned long calls=0,deferred=0,finalized=0,local_solves=0,pending_frame=0;bool pending=false;
    ~Counters(){
        if(!enabled())return;const char* path=std::getenv("ORB60_MOTION_POSE_REPORT");if(!path||!*path)return;
        std::string temp=std::string(path)+".part";std::ofstream f(temp);
        f<<"{\"status\":\"MOTION_POSE_COUNTERS_RECORDED\",\"policy\":\"defer-strong\",\"motion_calls\":"<<calls<<",\"deferred\":"<<deferred<<",\"finalized\":"<<finalized<<",\"local_solves\":"<<local_solves<<",\"pending\":"<<(pending?"true":"false")<<",\"minimum_projected_matches\":100,\"minimum_previous_inliers\":80}\n";
        f.close();if(f)std::rename(temp.c_str(),path);
    }
};
inline Counters& counters(){static thread_local Counters value;return value;}
inline bool defer(bool mono,bool only_tracking,bool tracking_ok,int previous_inliers,int matches,unsigned long frame){
    if(!enabled())return false;auto& c=counters();if(c.pending)throw std::runtime_error("Previous deferred frame lacked final pose solve");++c.calls;
    const bool take=eligible(mono,only_tracking,tracking_ok,previous_inliers,matches);
    if(take){++c.deferred;c.pending=true;c.pending_frame=frame;}return take;
}
inline void final_pose(unsigned long frame){
    if(!enabled())return;auto& c=counters();++c.local_solves;
    if(c.pending){if(c.pending_frame!=frame)throw std::runtime_error("Deferred/final pose frame mismatch");++c.finalized;c.pending=false;}
}
}
