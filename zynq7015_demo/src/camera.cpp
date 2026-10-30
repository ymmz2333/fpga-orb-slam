#include "zslam/camera.hpp"
#include <turbojpeg.h>
#include <cstring>
#include <stdexcept>
#include <limits>
#include <fstream>
#include <iomanip>
#include "zslam/filesystem.hpp"

namespace zslam {
static_assert(TURBOJPEG_VERSION_NUMBER==3002000,"Camera decoder requires pinned libjpeg-turbo3.2.0 headers");
CameraCrop cameraCrop(unsigned width,unsigned height){
    if(!((width==960&&height==720)||(width==1280&&(height==720||height==800))||(width==1024&&height==768)))
        throw std::runtime_error("Camera requires 960x720, 1024x768, 1280x720 or 1280x800; no implicit resize");
    return {width,height,(width-960)/2,(height-720)/2};
}
Camera croppedCamera(const Camera &source,unsigned width,unsigned height){
    auto crop=cameraCrop(width,height);
    if(source.width!=width||source.height!=height)throw std::runtime_error("Calibration must describe the negotiated source size before cropping");
    Camera result=source;result.width=960;result.height=720;result.cx-=crop.x;result.cy-=crop.y;return result;
}
const char *cameraEncodingName(CameraEncoding encoding){
    switch(encoding){case CameraEncoding::Grey:return "GREY";case CameraEncoding::Yuyv:return "YUYV";case CameraEncoding::Mjpeg:return "MJPEG";}
    throw std::runtime_error("Unknown camera encoding");
}
void writeCameraReport(const CameraCaptureProfile &p,const std::string &path){
    std::ofstream out(path);double seconds=p.last_timestamp_ns>p.first_timestamp_ns?double(p.last_timestamp_ns-p.first_timestamp_ns)*1e-9:0;
    out<<std::setprecision(15)<<"{\n  \"format\": \""<<cameraEncodingName(p.encoding)<<"\",\n  \"source_width\": "<<p.width<<",\n  \"source_height\": "<<p.height
       <<",\n  \"crop_x\": "<<p.crop_x<<",\n  \"crop_y\": "<<p.crop_y<<",\n  \"output_width\": 960,\n  \"output_height\": 720,\n  \"resized\": false"
       <<",\n  \"interval_numerator\": "<<p.rate_numerator<<",\n  \"interval_denominator\": "<<p.rate_denominator<<",\n  \"frames\": "<<p.frames
       <<",\n  \"capture_buffers\": "<<p.capture_buffers<<",\n  \"capture_mmap_bytes\": "<<p.capture_mmap_bytes<<",\n  \"decoder_scratch_bytes\": "<<p.decoder_scratch_bytes
       <<",\n  \"jpeg_region_decode\": "<<(p.jpeg_region_decode?"true":"false")
       <<",\n  \"sequence_gaps\": "<<p.sequence_gaps<<",\n  \"host_timestamp_frames\": "<<p.host_timestamps<<",\n  \"first_timestamp_ns\": "<<p.first_timestamp_ns
       <<",\n  \"last_timestamp_ns\": "<<p.last_timestamp_ns<<",\n  \"capture_timestamp_fps\": "<<(seconds>0&&p.frames>1?(p.frames-1)/seconds:0)
       <<",\n  \"compressed_bytes\": "<<p.compressed_bytes<<",\n  \"decode_cpu_ms\": "<<p.decode_cpu_ms<<",\n  \"mean_decode_cpu_ms\": "<<(p.frames?p.decode_cpu_ms/p.frames:0)
       <<",\n  \"claim\": \"Camera capture/decode metadata; not complete SLAM or pose acceptance. Host fallback timestamps are dequeue times.\"\n}\n";
    if(!out)throw std::runtime_error("Camera report write failed");
}
void writeGrayPgm(const GrayFrame &frame,const std::string &path){
    if(frame.width!=960||frame.height!=720||frame.pixels.size()!=960*720)throw std::runtime_error("PGM needs tight960x720 GRAY8");
    if(fs::exists(path))throw std::runtime_error("Refuse to overwrite camera image");
    std::ofstream out(path,std::ios::binary);out<<"P5\n960 720\n255\n";
    out.write(reinterpret_cast<const char*>(frame.pixels.data()),frame.pixels.size());out.flush();
    if(!out)throw std::runtime_error("Camera PGM write failed");
}
double cameraFocusScore(const GrayFrame &frame){
    if(frame.width!=960||frame.height!=720||frame.pixels.size()!=960*720)throw std::runtime_error("Focus score requires tight960x720 GRAY8");
    int64_t sum=0;uint64_t squares=0;const auto *p=frame.pixels.data();
    for(unsigned y=240;y<480;y++)for(unsigned x=320;x<640;x++){
        unsigned i=y*960+x;int v=int(p[i-1])+p[i+1]+p[i-960]+p[i+960]-4*int(p[i]);sum+=v;squares+=uint64_t(v*v);
    }
    double mean=double(sum)/(320*240);return std::max(0.,double(squares)/(320*240)-mean*mean);
}
struct CalibrationRecorder::Impl {
    std::string folder;unsigned limit,interval,seen=0,saved=0;uint64_t last_id=0,last_stamp=0;bool observed=false,finished=false;std::ofstream index;
    Impl(std::string path,unsigned shots,unsigned every):folder(std::move(path)),limit(shots),interval(every){
        if(!shots||shots>60||!every||every>300)throw std::runtime_error("Calibration capture requires1..60 shots, interval1..300 frames");
        if(fs::exists(folder))throw std::runtime_error("Calibration folder exists");fs::create_directories(folder);
        index.open(folder+"/index.csv");index<<"file,frame_index,timestamp_ns,width,height\n";
        if(!index)throw std::runtime_error("Cannot create calibration image index");
    }
};
CalibrationRecorder::CalibrationRecorder(const std::string &folder,unsigned shots,unsigned interval):impl_(std::make_unique<Impl>(folder,shots,interval)){}
CalibrationRecorder::~CalibrationRecorder()=default;
unsigned CalibrationRecorder::saved()const{return impl_->saved;}
void CalibrationRecorder::finish(){impl_->index.flush();if(!impl_->index)throw std::runtime_error("Calibration index flush failed");impl_->finished=true;}
bool CalibrationRecorder::consider(const GrayFrame &frame){
    auto &s=*impl_;if(s.finished)throw std::runtime_error("Calibration recorder already finished");
    if(frame.width!=960||frame.height!=720||frame.pixels.size()!=960*720||!frame.timestamp_ns||
       (s.observed&&(frame.id<=s.last_id||frame.timestamp_ns<=s.last_stamp)))throw std::runtime_error("Calibration frame geometry/identity invalid");
    s.observed=true;s.last_id=frame.id;s.last_stamp=frame.timestamp_ns;
    if(s.saved==s.limit)return false;
    if(s.seen++%s.interval)return false;
    std::string name="shot_"+std::to_string(s.saved)+"_frame_"+std::to_string(frame.id)+".pgm";
    writeGrayPgm(frame,s.folder+"/"+name);
    s.index<<name<<','<<frame.id<<','<<frame.timestamp_ns<<",960,720\n";s.index.flush();
    if(!s.index)throw std::runtime_error("Calibration image index write failed");s.saved++;return true;
}
uint64_t CameraSequence::accept(uint32_t sequence,uint64_t stamp){
    if(!stamp||stamp<=stamp_)throw std::runtime_error("Camera timestamp is not strictly monotonic");
    if(!started_){sequence_=sequence;started_=true;}
    else {uint32_t delta=sequence-previous_;if(!delta||delta>=0x80000000u)throw std::runtime_error("Camera sequence repeated or moved backwards");sequence_+=delta;gaps_+=delta-1;}
    previous_=sequence;stamp_=stamp;return sequence_;
}
void unpackCameraGray(const uint8_t *data,std::size_t bytes,unsigned stride,unsigned width,unsigned height,CameraEncoding encoding,GrayFrame &out){
    const auto crop=cameraCrop(width,height);
    if(encoding!=CameraEncoding::Grey&&encoding!=CameraEncoding::Yuyv)throw std::runtime_error("Uncompressed camera encoding invalid");
    const unsigned step=encoding==CameraEncoding::Grey?1:2;
    const uint64_t required=uint64_t(stride)*(height-1)+uint64_t(width)*step;
    if(!data||stride<uint64_t(width)*step||stride>8*1024*1024||bytes<required)throw std::runtime_error("Camera uncompressed stride/length invalid");
    out.pixels.resize(960*720);out.width=960;out.height=720;
    for(unsigned y=0;y<720;y++){
        const auto *row=data+std::size_t(y+crop.y)*stride+crop.x*step;auto *dst=out.pixels.data()+y*960;
        if(step==1)std::memcpy(dst,row,960);else for(unsigned x=0;x<960;x++)dst[x]=row[2*x];
    }
}
struct MjpegGrayDecoder::Impl {
    tjhandle decoder=nullptr;unsigned width,height;bool region;std::vector<uint8_t> gray;
    Impl(unsigned w,unsigned h,bool partial):width(w),height(h),region(partial),gray(std::size_t(partial?960:w)*h){
        reset();
    }
    void reset(){
        if(decoder)tj3Destroy(decoder);decoder=nullptr;
        decoder=tj3Init(TJINIT_DECOMPRESS);if(!decoder)throw std::runtime_error("Cannot create TurboJPEG decoder");
        if(tj3Set(decoder,TJPARAM_STOPONWARNING,1)||tj3Set(decoder,TJPARAM_MAXMEMORY,16)||tj3Set(decoder,TJPARAM_MAXPIXELS,1280*800)){
            tj3Destroy(decoder);decoder=nullptr;throw std::runtime_error("Cannot bound JPEG decoder resources");}
    }
    ~Impl(){if(decoder)tj3Destroy(decoder);}
};
MjpegGrayDecoder::MjpegGrayDecoder(unsigned width,unsigned height,bool region_decode){cameraCrop(width,height);impl_=std::make_unique<Impl>(width,height,region_decode);}
MjpegGrayDecoder::~MjpegGrayDecoder()=default;
std::size_t MjpegGrayDecoder::scratchBytes()const{return impl_->gray.size();}
void MjpegGrayDecoder::decode(const uint8_t *data,std::size_t bytes,GrayFrame &out){
    if(!data||bytes<4||bytes>max_compressed_bytes||data[0]!=0xff||data[1]!=0xd8||data[bytes-2]!=0xff||data[bytes-1]!=0xd9)
        throw std::runtime_error("MJPEG SOI/EOI or bounded payload invalid");
    try {
    auto handle=impl_->decoder;
    if(tj3DecompressHeader(handle,data,bytes))throw std::runtime_error(std::string("MJPEG header: ")+tj3GetErrorStr(handle));
    if(tj3Get(handle,TJPARAM_JPEGWIDTH)!=int(impl_->width)||tj3Get(handle,TJPARAM_JPEGHEIGHT)!=int(impl_->height)||
       tj3Get(handle,TJPARAM_PRECISION)!=8||tj3Get(handle,TJPARAM_PROGRESSIVE)||tj3Get(handle,TJPARAM_LOSSLESS))
        throw std::runtime_error("MJPEG must be an 8-bit sequential image at the negotiated camera size");
    int colorspace=tj3Get(handle,TJPARAM_COLORSPACE);
    if(colorspace!=TJCS_GRAY&&colorspace!=TJCS_YCbCr)throw std::runtime_error("MJPEG camera colorspace unsupported");
    auto crop=cameraCrop(impl_->width,impl_->height);
    tjregion region=impl_->region?tjregion{int(crop.x),0,960,int(impl_->height)}:TJUNCROPPED;
    if(tj3SetCroppingRegion(handle,region))throw std::runtime_error(std::string("MJPEG crop: ")+tj3GetErrorStr(handle));
    unsigned pitch=impl_->region?960:impl_->width;
    // Decode luminance directly. No RGB allocation, image scaling or approximate IDCT.
    // Keep all source rows so normal entropy/EOI validation still runs to completion.
    if(tj3Decompress8(handle,data,bytes,impl_->gray.data(),int(pitch),TJPF_GRAY))
        throw std::runtime_error(std::string("MJPEG data: ")+tj3GetErrorStr(handle));
    if(impl_->region){
        out.width=960;out.height=720;out.pixels.resize(960*720);
        std::memcpy(out.pixels.data(),impl_->gray.data()+std::size_t(crop.y)*960,960*720);
    }else unpackCameraGray(impl_->gray.data(),impl_->gray.size(),impl_->width,impl_->width,impl_->height,CameraEncoding::Grey,out);
    } catch(...) {
        // A rejected header may leave libjpeg between SOI and image completion.
        // Recreate only the decoder, retaining the bounded pixel allocation.
        impl_->reset();throw;
    }
}
}
