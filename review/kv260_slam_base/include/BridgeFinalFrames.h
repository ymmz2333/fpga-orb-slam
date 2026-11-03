#pragma once
#include "Tracking.h"
#include <fstream>
#include <iomanip>
#include <set>
namespace ORB_SLAM3 {
inline void ExportBridgeFinalFrames(Tracking *tracker,Map *map,const std::string &path){
    const size_t n=tracker->mlRelativeFramePoses.size();
    if(tracker->mlpReferences.size()!=n||tracker->mlFrameTimes.size()!=n||tracker->mlbLost.size()!=n)throw std::runtime_error("Final frame pose list lengths differ");
    std::ofstream out(path);out<<std::setprecision(17)<<"slam_timestamp_ns,map_id";
    for(int r=0;r<4;r++)for(int c=0;c<4;c++)out<<",twc_"<<r<<c;out<<'\n';
    auto ref=tracker->mlpReferences.begin();auto stamp=tracker->mlFrameTimes.begin();auto lost=tracker->mlbLost.begin();
    for(auto pose=tracker->mlRelativeFramePoses.begin();pose!=tracker->mlRelativeFramePoses.end();++pose,++ref,++stamp,++lost){
        if(*lost||!*ref)continue;KeyFrame *key=*ref;Sophus::SE3f chain;std::set<KeyFrame*>seen;
        while(key&&key->isBad()){
            if(!seen.insert(key).second||seen.size()>10000)throw std::runtime_error("Culled keyframe parent cycle");
            chain=chain*key->mTcp;key=key->GetParent();}
        if(!key||key->GetMap()!=map)continue;
        auto twc=((*pose)*chain*key->GetPose()).inverse().matrix();if(!twc.allFinite())continue;
        out<<std::llround(*stamp*1e9)<<','<<map->GetId();
        for(int r=0;r<4;r++)for(int c=0;c<4;c++)out<<','<<twc(r,c);out<<'\n';
    }
    out.close();if(!out)throw std::runtime_error("Cannot save final optimized frame poses");
}
}
