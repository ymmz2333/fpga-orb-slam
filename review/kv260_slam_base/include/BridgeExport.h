#pragma once
#include "Atlas.h"
#include "KeyFrame.h"
#include "MapPoint.h"
#include <algorithm>
#include <fstream>
#include <iomanip>
#include <map>
#include <stdexcept>
#include <sys/stat.h>

namespace ORB_SLAM3 {
inline void ExportBridgeAtlas(Atlas *atlas,const std::string&directory,bool enforce_capacity=true){
    Map *map=atlas->GetCurrentMap();if(!map)throw std::runtime_error("No active SLAM map");
    if(mkdir(directory.c_str(),0755))throw std::runtime_error("New export directory required");
    struct Observation {KeyFrame*key;size_t feature;MapPoint*point;Eigen::Vector3f xyz;double error;};
    std::vector<Observation>obs;std::map<unsigned long,std::vector<size_t>>groups;
    auto keys=map->GetAllKeyFrames();std::sort(keys.begin(),keys.end(),[](KeyFrame*a,KeyFrame*b){return a->mnId<b->mnId;});
    std::vector<KeyFrame*>accepted;
    for(auto *key:keys){if(!key||key->isBad())continue;auto twc=key->GetPoseInverse().matrix();if(!twc.allFinite())continue;accepted.push_back(key);
        const auto matches=key->GetMapPointMatches();
        for(size_t i=0;i<matches.size()&&i<key->mvKeysUn.size();i++){MapPoint*point=matches[i];if(!point||point->isBad()||point->GetMap()!=map||point->Observations()<3)continue;
            auto xyz=point->GetWorldPos();Eigen::Vector3f q=key->GetPose()*xyz;if(!xyz.allFinite()||q.z()<=1e-6f)continue;const auto &uv=key->mvKeysUn[i].pt;
            double error=std::hypot(key->fx*q.x()/q.z()+key->cx-uv.x,key->fy*q.y()/q.z()+key->cy-uv.y);if(!std::isfinite(error)||error>3)continue;
            if(i>=size_t(key->mDescriptors.rows)||key->mDescriptors.cols!=32||key->mDescriptors.type()!=CV_8UC1)throw std::runtime_error("Missing actual keyframe descriptor association");
            groups[point->mnId].push_back(obs.size());obs.push_back({key,i,point,xyz,error});}}
    if(groups.empty()||accepted.empty())throw std::runtime_error("Map has no valid keyframes or reliable observations");
    if(enforce_capacity&&(groups.size()>30000||accepted.size()>1024))throw std::runtime_error("Map has "+std::to_string(groups.size())+" reliable points / "+std::to_string(accepted.size())+" keyframes; Zynq limits are 30000 / 1024; complete raw backup preserved; no automatic truncation");
    std::ofstream kf(directory+"/keyframes.csv"),points(directory+"/points.csv"),observations(directory+"/observations.csv"),reps(directory+"/representative_descriptors.bin",std::ios::binary),descs(directory+"/observation_descriptors.bin",std::ios::binary),identity(directory+"/map_id.txt");
    kf<<std::setprecision(17)<<"map_id,keyframe_id,slam_frame_id,timestamp_ns,fx,fy,cx,cy,d0,d1,d2,d3,d4";for(int r=0;r<4;r++)for(int c=0;c<4;c++)kf<<",twc_"<<r<<c;kf<<'\n';
    for(auto *key:accepted){auto pose=key->GetPoseInverse().matrix();cv::Mat d;key->mDistCoef.reshape(1,1).convertTo(d,CV_64F);
        kf<<map->GetId()<<','<<key->mnId<<','<<key->mnFrameId<<','<<std::llround(key->mTimeStamp*1e9)<<','<<key->fx<<','<<key->fy<<','<<key->cx<<','<<key->cy;
        for(int i=0;i<5;i++)kf<<','<<(i<d.cols?d.at<double>(0,i):0);for(int r=0;r<4;r++)for(int c=0;c<4;c++)kf<<','<<pose(r,c);kf<<'\n';}
    observations<<std::setprecision(17)<<"keyframe_id,point_id,u,v,raw_u,raw_v,x,y,z,observations,octave,error_px,descriptor_row,feature_index\n";
    for(size_t i=0;i<obs.size();i++){const auto&o=obs[i];const auto &key=o.key->mvKeysUn[o.feature];const auto raw=o.key->mvKeys[o.feature].pt;
        observations<<o.key->mnId<<','<<o.point->mnId<<','<<key.pt.x<<','<<key.pt.y<<','<<raw.x<<','<<raw.y<<','<<o.xyz.x()<<','<<o.xyz.y()<<','<<o.xyz.z()<<','<<o.point->Observations()<<','<<key.octave<<','<<o.error<<','<<i<<','<<o.feature<<'\n';
        descs.write(reinterpret_cast<const char*>(o.key->mDescriptors.ptr(int(o.feature))),32);}
    points<<std::setprecision(17)<<"point_id,x,y,z,representative_observation_row,observations\n";
    for(const auto &group:groups){size_t selected=group.second.front();unsigned best=~0u;for(size_t i:group.second){std::vector<unsigned>dist;const auto&a=obs[i];const uint8_t*p=a.key->mDescriptors.ptr(int(a.feature));
            for(size_t j:group.second){const auto&b=obs[j];const uint8_t*q=b.key->mDescriptors.ptr(int(b.feature));unsigned n=0;for(unsigned k=0;k<32;k++)n+=unsigned(__builtin_popcount(unsigned(p[k]^q[k])));dist.push_back(n);}
            std::sort(dist.begin(),dist.end());unsigned score=dist[dist.size()/2]+dist[(dist.size()-1)/2];if(score<best){best=score;selected=i;}}
        const auto&o=obs[selected];points<<group.first<<','<<o.xyz.x()<<','<<o.xyz.y()<<','<<o.xyz.z()<<','<<selected<<','<<o.point->Observations()<<'\n';reps.write(reinterpret_cast<const char*>(o.key->mDescriptors.ptr(int(o.feature))),32);}
    identity<<map->GetId()<<'\n';
    for(auto*f:{&kf,&points,&observations,&reps,&descs,&identity}){f->close();if(!*f)throw std::runtime_error("Localization map export write failed");}
    std::ofstream complete(directory+"/EXPORT_COMPLETE");complete<<"points="<<groups.size()<<" keyframes="<<accepted.size()<<" observations="<<obs.size()<<"\n";complete.close();if(!complete)throw std::runtime_error("Cannot commit map export marker");
}
} // namespace ORB_SLAM3
