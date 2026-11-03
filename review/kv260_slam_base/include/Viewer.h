// GPL-3.0-or-later. Requesting a GUI in a headless executable is an explicit error.
#pragma once
#include <stdexcept>
#include <string>
namespace ORB_SLAM3 {
class System;class FrameDrawer;class MapDrawer;class Tracking;class Settings;
class Viewer {
public:
    bool both=false;
    Viewer(System*,FrameDrawer*,MapDrawer*,Tracking*,const std::string&,Settings*) {
        throw std::runtime_error("KV260 executable is headless; pass bUseViewer=false");
    }
    void Run(){throw std::runtime_error("KV260 GUI is not compiled");}
    void RequestFinish(){}
    void RequestStop(){}
    bool isFinished(){return true;}
    bool isStopped(){return true;}
    bool isStepByStep(){return false;}
    void Release(){}
};
}
