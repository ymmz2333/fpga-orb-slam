#pragma once
#include "MapPoint.h"
#include <set>
// Selected live tracking frames are exact color/pose anchors, not fabricated KFs.
inline void bridgeFrame(ORB_SLAM3::System &slam,const Sophus::SE3f&tcw,const demo::Packet&p,const std::string&folder){
    if(folder.empty()||!(p.flags&demo::color_expected)||slam.GetTrackingState()!=2)return;
    auto points=slam.GetTrackedMapPoints();auto keys=slam.GetTrackedKeyPointsUn();
    ORB_SLAM3::OrbTelemetryData snapshot;slam.GetVisualizationSnapshot(snapshot,false);
    std::ostringstream observations;observations<<std::setprecision(17);std::set<unsigned long>seen;unsigned count=0;
    for(size_t i=0;i<points.size()&&i<keys.size();i++){
        auto *point=points[i];if(!point||point->isBad()||point->Observations()<3||!seen.insert(point->mnId).second)continue;
        auto xyz=point->GetWorldPos();auto q=tcw*xyz;if(!xyz.allFinite()||q.z()<=1e-6f)continue;
        if(count++)observations<<',';observations<<'['<<keys[i].pt.x<<','<<keys[i].pt.y<<','<<xyz.x()<<','<<xyz.y()<<','<<xyz.z()<<','<<point->mnId<<']';
    }
    if(count<20)return;auto twc=tcw.inverse().matrix();if(!twc.allFinite())return;
    std::ostringstream out;out<<std::setprecision(17)<<"{\"map_id\":"<<snapshot.map_id<<",\"keyframe_id\":"<<(-int64_t(p.frame)-1)
        <<",\"source_frame_id\":"<<p.frame<<",\"timestamp_ns\":"<<p.stamp<<",\"session\":"<<p.session<<",\"gray_crc\":"<<p.aux
        <<",\"anchor_kind\":\"sampled_tracking_frame\",\"twc\":[";
    for(int r=0;r<4;r++){if(r)out<<',';out<<'[';for(int c=0;c<4;c++){if(c)out<<',';out<<twc(r,c);}out<<']';}
    out<<"],\"observations\":["<<observations.str()<<"]}\n";
    const auto name=folder+"/f"+std::to_string(p.frame)+".json";
    std::ofstream file(name+".part");file<<out.str();file.close();if(!file||std::rename((name+".part").c_str(),name.c_str()))throw std::runtime_error("Live color pose export failed");
}
