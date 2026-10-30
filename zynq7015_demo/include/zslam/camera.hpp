#pragma once
#include "ui.hpp"
#include <memory>

namespace zslam {
enum class CameraEncoding { Grey, Yuyv, Mjpeg };
struct CameraCaptureConfig {
    unsigned width=1280,height=720;
    CameraEncoding encoding=CameraEncoding::Mjpeg;
    bool jpeg_region_decode=true;
    uint64_t color_interval_ns=0; // zero keeps the retained gray-only capture path
};
struct CameraCrop {unsigned width,height,x,y;};
CameraCrop cameraCrop(unsigned width,unsigned height);
Camera croppedCamera(const Camera &source,unsigned width,unsigned height);
void unpackCameraGray(const uint8_t*,std::size_t,unsigned stride,unsigned width,unsigned height,CameraEncoding,GrayFrame&);
struct CameraCaptureProfile {
    unsigned width=0,height=0,crop_x=0,crop_y=0,rate_numerator=0,rate_denominator=0;
    unsigned capture_buffers=0;std::size_t capture_mmap_bytes=0,decoder_scratch_bytes=0;
    CameraEncoding encoding=CameraEncoding::Grey;
    bool jpeg_region_decode=false;
    uint64_t frames=0,sequence_gaps=0,host_timestamps=0,compressed_bytes=0;
    uint64_t first_timestamp_ns=0,last_timestamp_ns=0;
    double decode_cpu_ms=0;
};
const char *cameraEncodingName(CameraEncoding);
void writeCameraReport(const CameraCaptureProfile&,const std::string&);
void writeGrayPgm(const GrayFrame&,const std::string&);
// Centre320x240 Laplacian variance: focus aid only, never a calibration gate.
double cameraFocusScore(const GrayFrame&);
// Optional calibration capture only. At most60 source-identified images;
// production FPS runs leave this disabled to exclude SD image-write overhead.
class CalibrationRecorder {
    struct Impl;std::unique_ptr<Impl> impl_;
public:
    CalibrationRecorder(const std::string &new_folder,unsigned shots,unsigned interval_frames);
    ~CalibrationRecorder();
    bool consider(const GrayFrame&);
    unsigned saved()const;
    void finish();
};
class CameraSequence {
    bool started_=false;uint32_t previous_=0;uint64_t sequence_=0,stamp_=0,gaps_=0;
public:
    uint64_t accept(uint32_t sequence,uint64_t stamp);
    uint64_t gaps()const{return gaps_;}
};
// One owner per capture stream. Reuses a bounded source-sized GRAY8 scratch buffer.
class MjpegGrayDecoder {
    struct Impl;std::unique_ptr<Impl> impl_;
public:
    static constexpr std::size_t max_compressed_bytes=4*1024*1024;
    MjpegGrayDecoder(unsigned width,unsigned height,bool region_decode=true);
    ~MjpegGrayDecoder();
    std::size_t scratchBytes()const;
    void decode(const uint8_t*,std::size_t,GrayFrame&);
};
}
