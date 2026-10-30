#pragma once
// Read-only live keyframe observations. The existing ORBVIZ01 packet is unchanged.
#include "Atlas.h"
#include "KeyFrame.h"
#include "MapPoint.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <map>
#include <mutex>
#include <sstream>
#include <stdexcept>

namespace ORB_SLAM3 {
inline void DenseLiveExportAtlas(Atlas* atlas,const std::string& directory) {
    using Clock=std::chrono::steady_clock;
    static auto previous=Clock::now()-std::chrono::seconds(1);
    static std::map<unsigned long,double> last;
    const auto now=Clock::now();
    if(now-previous<std::chrono::milliseconds(100))return;
    previous=now;
    Map* map=atlas->GetCurrentMap();if(!map)return;
    std::unique_lock<std::mutex> lock(map->mMutexMapUpdate,std::try_to_lock);
    if(!lock.owns_lock())return; // Preview never waits for mapping/BA.
    const auto mid=map->GetId();
    auto keys=map->GetAllKeyFrames();
    std::sort(keys.begin(),keys.end(),[](KeyFrame* a,KeyFrame* b){return a->mTimeStamp<b->mTimeStamp;});
    for(KeyFrame* key:keys) {
        if(!key||key->isBad()||(last.count(mid)&&key->mTimeStamp<last[mid]+.5-1e-8))continue;
        const auto pose=key->GetPoseInverse().matrix();if(!pose.allFinite())continue;
        std::ostringstream obs;obs<<std::setprecision(17);size_t count=0;
        auto points=key->GetMapPointMatches();
        for(size_t i=0;i<points.size()&&i<key->mvKeysUn.size();++i) {
            MapPoint* point=points[i];
            if(!point||point->isBad()||point->GetMap()!=map||point->Observations()<3)continue;
            const Eigen::Vector3f world=point->GetWorldPos(),camera=key->GetPose()*world;
            if(!world.allFinite()||camera.z()<=1e-6f)continue;
            const auto uv=key->mvKeysUn[i].pt;
            const double error=std::hypot(key->fx*camera.x()/camera.z()+key->cx-uv.x,
                                          key->fy*camera.y()/camera.z()+key->cy-uv.y);
            if(!std::isfinite(error)||error>3.)continue;
            if(count++)obs<<',';
            obs<<'['<<uv.x<<','<<uv.y<<','<<world.x()<<','<<world.y()<<','<<world.z()<<','<<point->mnId<<']';
        }
        if(count<20)continue;
        cv::Mat dist;key->mDistCoef.reshape(1,1).convertTo(dist,CV_64F);
        std::ostringstream s;s<<std::setprecision(17);
        s<<"{\"map_id\":"<<mid<<",\"keyframe_id\":"<<key->mnId<<",\"slam_frame_id\":"<<key->mnFrameId
         <<",\"timestamp_ns\":"<<std::llround(key->mTimeStamp*1e9)
         <<",\"k\":[["<<key->fx<<",0,"<<key->cx<<"],[0,"<<key->fy<<','<<key->cy<<"],[0,0,1]],\"distortion\":[";
        for(int i=0;i<5;++i){if(i)s<<',';s<<(i<dist.cols?dist.at<double>(0,i):0.);}
        s<<"],\"twc\":[";
        for(int r=0;r<4;++r){if(r)s<<',';s<<'[';for(int c=0;c<4;++c){if(c)s<<',';s<<pose(r,c);}s<<']';}
        s<<"],\"observations\":["<<obs.str()<<"],\"semantics\":\"live provisional SLAM keyframe, not final BA\"}\n";
        const auto stamp=key->mTimeStamp;
        const auto name=directory+"/m"+std::to_string(mid)+"_k"+std::to_string(key->mnId)+".json";
        lock.unlock();
        std::ofstream out(name+".part");out<<s.str();out.close();
        if(!out||std::rename((name+".part").c_str(),name.c_str())!=0)throw std::runtime_error("Live dense keyframe write failed");
        last[mid]=stamp;return;
    }
}
}
