// GPL-3.0-or-later. Headless KV260 adapter for the optional ORB-SLAM3 viewer.
#pragma once
#include "Atlas.h"
#include "Settings.h"
#include <mutex>
namespace ORB_SLAM3 {
class MapDrawer {
public:
    EIGEN_MAKE_ALIGNED_OPERATOR_NEW
    Atlas* mpAtlas;
    MapDrawer(Atlas* atlas,const std::string&,Settings*):mpAtlas(atlas){}
    void SetCurrentCameraPose(const Sophus::SE3f& pose) {
        std::lock_guard<std::mutex> lock(mutex_);pose_=pose;
    }
private:
    Sophus::SE3f pose_;
    std::mutex mutex_;
};
}
