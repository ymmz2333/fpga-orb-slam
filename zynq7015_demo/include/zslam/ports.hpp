#pragma once
#include "ui.hpp"
#include "video_port.h"
#include "camera.hpp"
#include <memory>

namespace zslam {
class CameraSource {public:virtual ~CameraSource()=default;virtual bool next(GrayFrame&)=0;virtual CameraCaptureProfile profile()const{return {};}};
class DisplaySink {public:virtual ~DisplaySink()=default;virtual void present(const Dashboard&,uint64_t)=0;virtual void report(const std::string&){};};
std::unique_ptr<CameraSource> rawCamera(const std::string&,unsigned fps=30,const std::string &index_path="");
std::unique_ptr<CameraSource> v4l2Camera(const std::string&,unsigned requested_fps=30,CameraCaptureConfig={});
std::unique_ptr<CameraSource> externalCamera(zslam_camera_port);
std::unique_ptr<DisplaySink> framebufferDisplay(const std::string&);
std::unique_ptr<DisplaySink> externalDisplay(zslam_display_port);
int readControlKey();
struct OrbCpuProfile {uint64_t frames=0,cache_hits=0,cache_misses=0;std::size_t cache_bytes=0;double engine_ms=0,verify_ms=0,decode_ms=0;};
class LiveOrb {
    struct Impl;std::shared_ptr<Impl> impl_;
public:
    explicit LiveOrb(const std::string&,unsigned poll_pause_us=50,bool decode_cache=true);
    ~LiveOrb();
    Frame extract(const GrayFrame&,const Camera&);
    // Extraction-owner only. Exact meta + 64-byte records + statistics from
    // the immediately completed PL transaction, never reconstructed features.
    std::vector<uint8_t> resultPayload()const;
    // Producer lease remains held through this call. The offset must be one
    // of the paired engine's three receive slots, never an arbitrary DDR range.
    Frame extractDdr(unsigned input_offset,uint64_t sequence,uint64_t timestamp_ns,const Camera&);
    // Same exclusively owned UIO and WC DDR mapping as ORB; no second alias.
    std::unique_ptr<DisplaySink> hdmiDisplay();
    void verifyGolden(const std::string&);
    // Read only after the extraction owner has stopped/joined.
    OrbCpuProfile profile()const;
};
} // namespace zslam
