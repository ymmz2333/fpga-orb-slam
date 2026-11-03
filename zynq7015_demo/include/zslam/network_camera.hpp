#pragma once
#include "ports.hpp"
#include "bridge_wire.hpp"

namespace zslam {
// One bounded, explicitly selected GRAY8 input. Mode0=actual camera;
// mode1=recorded diagnostic. Neither silently substitutes for the other.
std::unique_ptr<CameraSource> networkCamera(unsigned port,const std::string& calibration,
                                          unsigned mode,unsigned frames,const std::string& journal,bool manual=false);
// The real first frame is used for hardware preflight and then processed once
// by SLAM. Copy into the caller's lease; do not replace a pool-owned vector.
std::unique_ptr<CameraSource> replayPreflightCamera(std::unique_ptr<CameraSource>,GrayFrame);
}
