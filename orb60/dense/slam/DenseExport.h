#pragma once
// Read-only export after SLAM worker threads and global BA have finished.
#include "Atlas.h"
#include "KeyFrame.h"
#include "MapPoint.h"
#include <algorithm>
#include <cerrno>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <stdexcept>
#include <sys/stat.h>

namespace ORB_SLAM3 {
inline void DenseDirectory(const std::string& directory) {
    if (mkdir(directory.c_str(), 0755) != 0 && errno != EEXIST)
        throw std::runtime_error("Cannot create dense export directory: " + directory);
}
inline void DenseExportAtlas(Atlas* atlas, const std::string& directory) {
    DenseDirectory(directory);
    std::ofstream maps(directory + "/maps.csv");
    maps << "map_id,keyframes,observations\n";
    for (Map* map : atlas->GetAllMaps()) {
        const auto id = map->GetId();
        const std::string folder = directory + "/map_" + std::to_string(id);
        DenseDirectory(folder);
        std::ofstream keys(folder + "/keyframes.csv"), observations(folder + "/observations.csv");
        keys << "map_id,keyframe_id,slam_frame_id,timestamp_ns,fx,fy,cx,cy";
        for (int i=0;i<5;++i) keys << ",d" << i;
        for (int r=0;r<4;++r) for (int c=0;c<4;++c) keys << ",twc_" << r << c;
        keys << '\n' << std::setprecision(17);
        observations << "keyframe_id,point_id,u,v,raw_u,raw_v,x,y,z,observations,octave,error_px\n" << std::setprecision(17);
        auto frames = map->GetAllKeyFrames();
        std::sort(frames.begin(), frames.end(), [](KeyFrame* a, KeyFrame* b) { return a->mnId < b->mnId; });
        size_t nk = 0, no = 0;
        for (KeyFrame* key : frames) {
            if (!key || key->isBad()) continue;
            const Eigen::Matrix4f twc = key->GetPoseInverse().matrix();
            if (!twc.allFinite()) continue;
            keys << id << ',' << key->mnId << ',' << key->mnFrameId << ','
                 << std::llround(key->mTimeStamp * 1e9) << ',' << key->fx << ',' << key->fy
                 << ',' << key->cx << ',' << key->cy;
            cv::Mat distortion;
            key->mDistCoef.reshape(1,1).convertTo(distortion, CV_64F);
            for (int i=0;i<5;++i) keys << ',' << (i < distortion.cols ? distortion.at<double>(0,i) : 0.);
            for (int r=0;r<4;++r) for (int c=0;c<4;++c) keys << ',' << twc(r,c);
            keys << '\n'; ++nk;
            const auto points = key->GetMapPointMatches();
            for (size_t i=0;i<points.size() && i<key->mvKeysUn.size();++i) {
                MapPoint* point = points[i];
                if (!point || point->isBad() || point->GetMap() != map || point->Observations() < 3) continue;
                const Eigen::Vector3f world = point->GetWorldPos();
                const Eigen::Vector3f camera = key->GetPose() * world;
                if (!world.allFinite() || camera.z() <= 1e-6f) continue;
                const auto& pixel = key->mvKeysUn[i];
                const double u = key->fx*camera.x()/camera.z()+key->cx;
                const double v = key->fy*camera.y()/camera.z()+key->cy;
                const double error = std::hypot(u-pixel.pt.x,v-pixel.pt.y);
                if (!std::isfinite(error) || error > 3.) continue;
                const auto raw = i < key->mvKeys.size() ? key->mvKeys[i].pt : pixel.pt;
                observations << key->mnId << ',' << point->mnId << ',' << pixel.pt.x << ',' << pixel.pt.y
                             << ',' << raw.x << ',' << raw.y << ',' << world.x() << ',' << world.y()
                             << ',' << world.z() << ',' << point->Observations() << ',' << pixel.octave << ',' << error << '\n';
                ++no;
            }
        }
        if (!keys.good() || !observations.good()) throw std::runtime_error("Dense export write failed");
        maps << id << ',' << nk << ',' << no << '\n';
    }
    if (!maps.good()) throw std::runtime_error("Dense map manifest write failed");
}
} // namespace ORB_SLAM3
