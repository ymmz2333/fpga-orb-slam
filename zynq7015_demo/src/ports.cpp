#include "zslam/ports.hpp"
#include "zslam/formats.hpp"
#include "zslam/profiling.hpp"
#include <chrono>
#include <cstring>
#include <fstream>
#include <stdexcept>
#if defined(_WIN32)
#include <conio.h>
#endif
#if defined(__linux__)
#include <cerrno>
#include <fcntl.h>
#include <linux/fb.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <termios.h>
#include <unistd.h>
#include <time.h>
extern "C" {
#include "engine.h"
}
#endif

namespace zslam {
namespace {
class Raw final:public CameraSource {
    std::ifstream stream_;uint64_t sequence_=0,period_;
    std::unique_ptr<Csv> index_;uint64_t last_stamp_=0;
    bool end(){if(index_){Row extra;if(index_->next(extra))throw std::runtime_error("Extra RAW timestamp rows");}return false;}
#if defined(__linux__)
    int fd_=-1;uint64_t offset_=0,prefetch_end_=0;
#endif
public:
    Raw(const std::string &path,unsigned fps,const std::string &index):period_(1000000000ull/fps),index_(index.empty()?nullptr:std::make_unique<Csv>(index)){
#if defined(__linux__)
        fd_=::open(path.c_str(),O_RDONLY);if(fd_<0)throw std::runtime_error("Cannot open raw GRAY8 source");
        posix_fadvise(fd_,0,0,POSIX_FADV_SEQUENTIAL);posix_fadvise(fd_,0,4*1024*1024,POSIX_FADV_WILLNEED);prefetch_end_=4*1024*1024;
#else
        stream_.open(path,std::ios::binary);if(!stream_)throw std::runtime_error("Cannot open raw GRAY8 source");
#endif
    }
    ~Raw()override{
#if defined(__linux__)
        if(fd_>=0)::close(fd_);
#endif
    }
    bool next(GrayFrame &f)override{f.pixels.resize(960*720);
#if defined(__linux__)
        std::size_t done=0;
        while(done<f.pixels.size()){
            auto n=::read(fd_,f.pixels.data()+done,f.pixels.size()-done);
            if(n<0){if(errno==EINTR)continue;throw std::runtime_error("GRAY8 read failed");}
            if(!n){if(!done)return end();throw std::runtime_error("Truncated GRAY8 frame");}
            done+=static_cast<std::size_t>(n);
        }
        offset_+=done;
        if(offset_+2*1024*1024>=prefetch_end_){posix_fadvise(fd_,offset_,4*1024*1024,POSIX_FADV_WILLNEED);prefetch_end_=offset_+4*1024*1024;}
#else
        stream_.read(reinterpret_cast<char*>(f.pixels.data()),960*720);auto n=stream_.gcount();
        if(!n&&stream_.eof())return end();if(n!=960*720)throw std::runtime_error("Truncated GRAY8 frame");
#endif
        f.width=960;f.height=720;f.id=sequence_;
        if(index_){Row row;if(!index_->next(row)||integer(row,"frame_index")!=sequence_||integer(row,"byte_offset")!=sequence_*uint64_t(960*720)||integer(row,"bytes")!=960*720)throw std::runtime_error("RAW identity/byte layout mismatch");
            f.timestamp_ns=integer(row,"timestamp_ns");if(!f.timestamp_ns||f.timestamp_ns<=last_stamp_)throw std::runtime_error("Non-monotonic RAW timestamps");last_stamp_=f.timestamp_ns;
        }else f.timestamp_ns=1000000000ull+sequence_*period_;
        sequence_++;return true;}
};
class ExternalCamera final:public CameraSource {
    zslam_camera_port port_;
public:
    explicit ExternalCamera(zslam_camera_port p):port_(p){if(!p.acquire||!p.release)throw std::runtime_error("Incomplete external camera callbacks");}
    bool next(GrayFrame &f)override{zslam_camera_frame in{};int result=port_.acquire(port_.context,&in);if(result==0)return false;if(result<0)throw std::runtime_error("External camera failure");
        try {if(!in.pixels||in.width!=960||in.height!=720||in.stride!=960||in.bytes!=960*720||!in.timestamp_ns)throw std::runtime_error("External camera GRAY8 contract mismatch");
            f.id=in.sequence;f.timestamp_ns=in.timestamp_ns;f.width=in.width;f.height=in.height;f.pixels.assign(in.pixels,in.pixels+in.bytes);
        }catch(...){port_.release(port_.context,in.lease);throw;}port_.release(port_.context,in.lease);return true;}
};
class ExternalDisplay final:public DisplaySink {
    zslam_display_port port_;
public:
    explicit ExternalDisplay(zslam_display_port p):port_(p){if(!p.present_rgb565)throw std::runtime_error("Incomplete display callback");}
    void present(const Dashboard &d,uint64_t frame)override{if(port_.present_rgb565(port_.context,d.pixels.data(),d.width,d.height,d.width*2,frame))throw std::runtime_error("External display failure");}
};
#if defined(__linux__)
int control(int fd,unsigned long request,void *argument){int r;do{r=ioctl(fd,request,argument);}while(r<0&&errno==EINTR);return r;}
class V4L2 final:public CameraSource {
    int fd_=-1;struct Buffer {void *address=nullptr;std::size_t bytes=0;};std::vector<Buffer> buffers_;unsigned stride_=0;bool streaming_=false;
    CameraCaptureConfig config_;CameraCaptureProfile profile_;CameraSequence sequence_;std::unique_ptr<MjpegGrayDecoder> decoder_;
    uint64_t last_color_stamp_=0;
    void close(){if(streaming_){int type=V4L2_BUF_TYPE_VIDEO_CAPTURE;control(fd_,VIDIOC_STREAMOFF,&type);}for(auto b:buffers_)if(b.address)munmap(b.address,b.bytes);if(fd_>=0)::close(fd_);fd_=-1;}
public:
    V4L2(const std::string &path,unsigned requested_fps,CameraCaptureConfig config):config_(config){
        auto crop=cameraCrop(config.width,config.height);
        fd_=::open(path.c_str(),O_RDWR|O_NONBLOCK);if(fd_<0)throw std::runtime_error("Cannot open V4L2 camera");
        try {
            v4l2_capability caps{};if(control(fd_,VIDIOC_QUERYCAP,&caps))throw std::runtime_error("V4L2 capability query failed");
            unsigned cap=caps.capabilities&V4L2_CAP_DEVICE_CAPS?caps.device_caps:caps.capabilities;
            if(!(cap&V4L2_CAP_VIDEO_CAPTURE)||!(cap&V4L2_CAP_STREAMING))throw std::runtime_error("Camera needs single-plane streaming capture");
            unsigned pix=config.encoding==CameraEncoding::Mjpeg?V4L2_PIX_FMT_MJPEG:(config.encoding==CameraEncoding::Grey?V4L2_PIX_FMT_GREY:V4L2_PIX_FMT_YUYV);
            v4l2_format fmt{};fmt.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;fmt.fmt.pix.width=config.width;fmt.fmt.pix.height=config.height;fmt.fmt.pix.pixelformat=pix;fmt.fmt.pix.field=V4L2_FIELD_NONE;
            if(control(fd_,VIDIOC_S_FMT,&fmt)||fmt.fmt.pix.width!=config.width||fmt.fmt.pix.height!=config.height||fmt.fmt.pix.pixelformat!=pix||fmt.fmt.pix.field!=V4L2_FIELD_NONE)
                throw std::runtime_error("Camera did not accept the explicit size/format/progressive scan; inspect its V4L2 modes");
            stride_=fmt.fmt.pix.bytesperline;
            unsigned minimum=config.width*(config.encoding==CameraEncoding::Yuyv?2:1);
            if(config.encoding!=CameraEncoding::Mjpeg&&(stride_<minimum||stride_>8*1024*1024))throw std::runtime_error("Invalid camera stride");
            if(config.encoding==CameraEncoding::Mjpeg)decoder_=std::make_unique<MjpegGrayDecoder>(config.width,config.height,config.jpeg_region_decode);
            v4l2_streamparm rate{};rate.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;rate.parm.capture.timeperframe={1,requested_fps};
            if(control(fd_,VIDIOC_S_PARM,&rate))throw std::runtime_error("Camera cannot negotiate the requested frame rate");
            rate={};rate.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;
            if(control(fd_,VIDIOC_G_PARM,&rate)||!rate.parm.capture.timeperframe.numerator||!rate.parm.capture.timeperframe.denominator||
               double(rate.parm.capture.timeperframe.denominator)/rate.parm.capture.timeperframe.numerator<requested_fps*.995||
               double(rate.parm.capture.timeperframe.denominator)/rate.parm.capture.timeperframe.numerator>requested_fps*1.005)
                throw std::runtime_error("Camera driver did not negotiate the requested frame rate (within0.5%)");
            profile_.width=config.width;profile_.height=config.height;profile_.crop_x=crop.x;profile_.crop_y=crop.y;profile_.encoding=config.encoding;
            profile_.rate_numerator=rate.parm.capture.timeperframe.numerator;profile_.rate_denominator=rate.parm.capture.timeperframe.denominator;
            profile_.decoder_scratch_bytes=decoder_?decoder_->scratchBytes():0;
            profile_.jpeg_region_decode=decoder_&&config.jpeg_region_decode;
            v4l2_requestbuffers req{};req.count=3;req.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;req.memory=V4L2_MEMORY_MMAP;
            if(control(fd_,VIDIOC_REQBUFS,&req)||req.count<2||req.count>8)throw std::runtime_error("Camera buffer allocation failed");
            for(unsigned i=0;i<req.count;i++){v4l2_buffer b{};b.type=req.type;b.memory=req.memory;b.index=i;if(control(fd_,VIDIOC_QUERYBUF,&b))throw std::runtime_error("Camera buffer query failed");
                uint64_t required=config.encoding==CameraEncoding::Mjpeg?4:uint64_t(stride_)*(config.height-1)+minimum;
                if(b.length>8*1024*1024||b.length<required)throw std::runtime_error("Camera buffer size invalid");
                void *p=mmap(nullptr,b.length,PROT_READ|PROT_WRITE,MAP_SHARED,fd_,b.m.offset);if(p==MAP_FAILED)throw std::runtime_error("Camera mapping failed");buffers_.push_back({p,b.length});
                profile_.capture_buffers++;profile_.capture_mmap_bytes+=b.length;
                if(control(fd_,VIDIOC_QBUF,&b))throw std::runtime_error("Camera queue failed");}
            int type=V4L2_BUF_TYPE_VIDEO_CAPTURE;if(control(fd_,VIDIOC_STREAMON,&type))throw std::runtime_error("Camera stream start failed");streaming_=true;
        }catch(...){close();throw;}
    }
    ~V4L2()override{close();}
    CameraCaptureProfile profile()const override{return profile_;}
    bool next(GrayFrame &f)override{
        pollfd ready{fd_,POLLIN,0};int result;do{result=poll(&ready,1,2000);}while(result<0&&errno==EINTR);
        if(result<=0||!(ready.revents&POLLIN))throw std::runtime_error("Camera capture timeout/error");
        v4l2_buffer b{};b.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;b.memory=V4L2_MEMORY_MMAP;if(control(fd_,VIDIOC_DQBUF,&b))throw std::runtime_error("Camera dequeue failed");
        if(b.index>=buffers_.size())throw std::runtime_error("Camera buffer index invalid");
        try {
            if((b.flags&V4L2_BUF_FLAG_ERROR)||!b.bytesused||b.bytesused>buffers_[b.index].bytes)throw std::runtime_error("Camera reports a corrupt/empty/oversized frame");
            uint64_t stamp=0;
            if((b.flags&V4L2_BUF_FLAG_TIMESTAMP_MASK)==V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC){
                if(b.timestamp.tv_sec<0||b.timestamp.tv_usec<0||b.timestamp.tv_usec>=1000000)throw std::runtime_error("Invalid V4L2 timestamp fields");
                stamp=uint64_t(b.timestamp.tv_sec)*1000000000ull+uint64_t(b.timestamp.tv_usec)*1000;
            }else{stamp=static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count());profile_.host_timestamps++;}
            f.id=sequence_.accept(b.sequence,stamp);f.timestamp_ns=stamp;
            const auto *data=static_cast<const uint8_t*>(buffers_[b.index].address);double start=threadCpuMs();
            if(decoder_){decoder_->decode(data,b.bytesused,f);profile_.compressed_bytes+=b.bytesused;}
            else unpackCameraGray(data,b.bytesused,stride_,config_.width,config_.height,config_.encoding,f);
            f.color_jpeg.clear();
            if(decoder_&&config_.color_interval_ns&&(!last_color_stamp_||stamp-last_color_stamp_>=config_.color_interval_ns)){
                f.color_jpeg.assign(data,data+b.bytesused);last_color_stamp_=stamp;}
            profile_.decode_cpu_ms+=threadCpuMs()-start;profile_.frames++;profile_.sequence_gaps=sequence_.gaps();
            if(!profile_.first_timestamp_ns)profile_.first_timestamp_ns=stamp;profile_.last_timestamp_ns=stamp;
        }catch(...){control(fd_,VIDIOC_QBUF,&b);throw;}
        if(control(fd_,VIDIOC_QBUF,&b))throw std::runtime_error("Camera buffer release failed");return true;
    }
};
class Framebuffer final:public DisplaySink {
    int fd_=-1;uint8_t *memory_=nullptr;std::size_t bytes_=0;fb_var_screeninfo mode_{};fb_fix_screeninfo fixed_{};
public:
    explicit Framebuffer(const std::string &path){fd_=::open(path.c_str(),O_RDWR);if(fd_<0)throw std::runtime_error("Cannot open HDMI framebuffer");
        if(control(fd_,FBIOGET_FSCREENINFO,&fixed_)||control(fd_,FBIOGET_VSCREENINFO,&mode_)||mode_.xres<1280||mode_.yres<720||(mode_.bits_per_pixel!=16&&mode_.bits_per_pixel!=32)||fixed_.type!=FB_TYPE_PACKED_PIXELS||fixed_.visual!=FB_VISUAL_TRUECOLOR){::close(fd_);fd_=-1;throw std::runtime_error("Need >=1280x720 packed RGB16/RGB32 framebuffer");}
        unsigned bpp=mode_.bits_per_pixel/8;
        if(mode_.red.length>8||mode_.green.length>8||mode_.blue.length>8||mode_.transp.length>8||mode_.red.msb_right||mode_.green.msb_right||mode_.blue.msb_right||mode_.transp.msb_right||mode_.red.offset+mode_.red.length>mode_.bits_per_pixel||mode_.green.offset+mode_.green.length>mode_.bits_per_pixel||mode_.blue.offset+mode_.blue.length>mode_.bits_per_pixel||mode_.transp.offset+mode_.transp.length>mode_.bits_per_pixel||fixed_.line_length<(mode_.xoffset+1280)*bpp||uint64_t(mode_.yoffset+720)*fixed_.line_length>fixed_.smem_len){::close(fd_);fd_=-1;throw std::runtime_error("Unsupported framebuffer bitfields/stride");}
        bytes_=fixed_.smem_len;void *p=mmap(nullptr,bytes_,PROT_READ|PROT_WRITE,MAP_SHARED,fd_,0);if(p==MAP_FAILED){::close(fd_);fd_=-1;throw std::runtime_error("Framebuffer mmap failed");}memory_=static_cast<uint8_t*>(p);
    }
    ~Framebuffer()override{if(memory_)munmap(memory_,bytes_);if(fd_>=0)::close(fd_);}
    void present(const Dashboard &ui,uint64_t)override{
        if(ui.width!=1280||ui.height!=720)throw std::runtime_error("Dashboard geometry mismatch");
        unsigned bpp=mode_.bits_per_pixel/8;
        for(unsigned y=0;y<ui.height;y++){uint8_t *row=memory_+(y+mode_.yoffset)*fixed_.line_length+mode_.xoffset*bpp;
            for(unsigned x=0;x<ui.width;x++){unsigned pixel=ui.pixels[y*ui.width+x],r=((pixel>>11)&31)*255/31,g=((pixel>>5)&63)*255/63,b=(pixel&31)*255/31;
                uint32_t packed=((r>>(8-mode_.red.length))<<mode_.red.offset)|((g>>(8-mode_.green.length))<<mode_.green.offset)|((b>>(8-mode_.blue.length))<<mode_.blue.offset);
                if(mode_.transp.length)packed|=((1u<<mode_.transp.length)-1)<<mode_.transp.offset;
                if(bpp==2){uint16_t v=static_cast<uint16_t>(packed);std::memcpy(row+2*x,&v,2);}else std::memcpy(row+4*x,&packed,4);}}
        // Existing scanout driver owns timing; this API does not configure clocks/pins.
    }
};
#endif
}
std::unique_ptr<CameraSource> rawCamera(const std::string &path,unsigned fps,const std::string &index){if(!fps||fps>240)throw std::runtime_error("Invalid source FPS");return std::make_unique<Raw>(path,fps,index);}
std::unique_ptr<CameraSource> externalCamera(zslam_camera_port p){return std::make_unique<ExternalCamera>(p);}
std::unique_ptr<DisplaySink> externalDisplay(zslam_display_port p){return std::make_unique<ExternalDisplay>(p);}
std::unique_ptr<CameraSource> v4l2Camera(const std::string &path,unsigned requested_fps,CameraCaptureConfig config){
    if(!requested_fps||requested_fps>240)throw std::runtime_error("Invalid requested camera FPS");
#if defined(__linux__)
    return std::make_unique<V4L2>(path,requested_fps,config);
#else
    (void)path;(void)config;throw std::runtime_error("V4L2 source requires Zynq Linux");
#endif
}
std::unique_ptr<DisplaySink> framebufferDisplay(const std::string &path){
#if defined(__linux__)
    return std::make_unique<Framebuffer>(path);
#else
    (void)path;throw std::runtime_error("Framebuffer sink requires Zynq Linux");
#endif
}
struct LiveOrb::Impl {
    OrbCpuProfile profile;
    std::vector<uint8_t> last_payload;
#if defined(__linux__)
    orb_engine engine{};std::array<uint8_t,ORB60_RESULT_MAX> payload{};bool opened=false,failed=false;
    uint32_t (*original_read)(orb_engine*,unsigned,unsigned)=nullptr;unsigned poll_pause_us=0;
    static uint32_t cooperativeRead(orb_engine *engine,unsigned core,unsigned offset){
        auto *self=static_cast<Impl*>(engine->test_context);
        // Exactly one read: AP_DONE is clear-on-read. Yield only while a core
        // is busy, without changing the frozen engine's ordering or timeout.
        uint32_t value=self->original_read(engine,core,offset);
        if(offset==0&&!(value&6u)&&self->poll_pause_us){timespec pause{0,long(self->poll_pause_us)*1000};nanosleep(&pause,nullptr);}
        return value;
    }
    std::string uio;
    std::unique_ptr<RecordDecodeCache> decode_cache;
    std::unique_ptr<Csv> oracle_rows;std::ifstream oracle_bytes;
    void verify(const uint8_t *data,unsigned count,uint64_t frame){
        if(!oracle_rows)return;Row row;std::array<uint8_t,64000> expected{};
        if(!oracle_rows->next(row)||integer(row,"frame_index")!=frame||integer(row,"count")!=count)throw std::runtime_error("Physical ORB golden identity/count mismatch");
        oracle_bytes.read(reinterpret_cast<char*>(expected.data()),count*64);
        if(oracle_bytes.gcount()!=count*64||std::memcmp(expected.data(),data,count*64))throw std::runtime_error("Physical ORB record byte mismatch");
    }
    Frame finishRecords(size_t bytes,uint32_t count,uint64_t id,uint64_t stamp,const Camera &camera,double start){
        double verified=threadCpuMs();profile.engine_ms+=verified-start;
        if(count>1000||bytes!=ORB60_META_BYTES+64*count+ORB60_STATS_BYTES){failed=true;throw std::runtime_error("Physical ORB payload ABI mismatch");}
        verify(payload.data()+ORB60_META_BYTES,count,id);
        last_payload.assign(payload.begin(),payload.begin()+bytes);
        double decoded=threadCpuMs();profile.verify_ms+=decoded-verified;
        Frame result=decodeRecords(payload.data()+ORB60_META_BYTES,64*count,id,stamp,camera,decode_cache.get());
        profile.decode_ms+=threadCpuMs()-decoded;profile.frames++;return result;
    }
    ~Impl(){if(opened)orb_engine_close(&engine);}
#endif
};
LiveOrb::LiveOrb(const std::string &uio,unsigned poll_pause_us,bool decode_cache):impl_(std::make_shared<Impl>()){
    if(poll_pause_us>1000)throw std::runtime_error("ORB poll pause exceeds bounded 1000us");
#if defined(__linux__)
    if(orb_engine_open(&impl_->engine,uio.c_str()))throw std::runtime_error("Cannot exclusively open paired ORB UIO");impl_->opened=true;impl_->uio=uio;
    impl_->original_read=impl_->engine.read;impl_->poll_pause_us=poll_pause_us;impl_->engine.test_context=impl_.get();
    impl_->engine.read=&Impl::cooperativeRead;
    if(decode_cache)impl_->decode_cache=std::make_unique<RecordDecodeCache>();
#else
    (void)uio;(void)decode_cache;throw std::runtime_error("Physical ORB backend requires Zynq Linux");
#endif
}
LiveOrb::~LiveOrb()=default;
std::vector<uint8_t> LiveOrb::resultPayload()const{return impl_->last_payload;}
OrbCpuProfile LiveOrb::profile()const{auto result=impl_->profile;
#if defined(__linux__)
    if(impl_->decode_cache){result.cache_hits=impl_->decode_cache->hits();result.cache_misses=impl_->decode_cache->misses();result.cache_bytes=impl_->decode_cache->reservedBytes();}
#endif
    return result;}
void LiveOrb::verifyGolden(const std::string &path){
#if defined(__linux__)
    impl_->oracle_rows=std::make_unique<Csv>(path+"/frames.csv");impl_->oracle_bytes.open(path+"/features.bin",std::ios::binary);
    if(!impl_->oracle_bytes)throw std::runtime_error("Cannot open physical ORB record oracle");
#else
    (void)path;throw std::runtime_error("Physical ORB verification requires Linux");
#endif
}
std::unique_ptr<DisplaySink> LiveOrb::hdmiDisplay(){
#if defined(__linux__)
    class Hdmi final:public DisplaySink {
        std::shared_ptr<Impl> owner_;volatile uint32_t *regs_;
        uint32_t ticket_,initial_frames_,initial_underflows_,initial_errors_;
        unsigned submitted_=0;bool pending_=false;
        std::chrono::steady_clock::time_point start_=std::chrono::steady_clock::now();
        void wait(){auto end=std::chrono::steady_clock::now()+std::chrono::seconds(1);
            while(pending_&&regs_[5]!=ticket_){if(std::chrono::steady_clock::now()>end)throw std::runtime_error("HDMI frame switch timeout");timespec pause{0,1000000};nanosleep(&pause,nullptr);}
            pending_=false;orb_engine_publish_input();
            if(regs_[7]!=initial_underflows_||regs_[8]!=initial_errors_)throw std::runtime_error("HDMI scanout underrun/AXI error; inspect hardware counters");}
    public:
        explicit Hdmi(std::shared_ptr<Impl> owner):owner_(std::move(owner)),regs_(owner_->engine.regs[0]+0x8000/4){
            auto slash=owner_->uio.find_last_of('/');auto name=owner_->uio.substr(slash==std::string::npos?0:slash+1);
            std::ifstream version_file("/sys/class/uio/"+name+"/version");std::string version;std::getline(version_file,version);
            if(version!="wc1")throw std::runtime_error("HDMI requires paired reserved-DDR WC UIO provider wc1");
            if(regs_[10]!=0x5a564431u||regs_[11]!=((1280u<<16)|720u))throw std::runtime_error("Paired HDMI_2 core/version not present");
            ticket_=regs_[2];initial_frames_=regs_[6];initial_underflows_=regs_[7];initial_errors_=regs_[8];}
        void present(const Dashboard &ui,uint64_t)override{
            if(ui.width!=1280||ui.height!=720||ui.pixels.size()!=1280*720)throw std::runtime_error("HDMI needs tight 1280x720 RGB565");
            wait();uint32_t current=regs_[4];
            if(current!=0x20b00000u&&current!=0x20d00000u)throw std::runtime_error("HDMI active buffer outside owned aperture");
            uint32_t back=current==0x20b00000u?0x20d00000u:0x20b00000u;
            std::memcpy(owner_->engine.ddr+(back-ORB60_DDR_BASE),ui.pixels.data(),ui.pixels.size()*2);
            orb_engine_publish_input();regs_[1]=back;orb_engine_publish_input();regs_[2]=++ticket_;
            regs_[0]=1;orb_engine_publish_input();pending_=true;submitted_++;
        }
        void report(const std::string &path)override{
            wait();double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start_).count();
            std::ofstream f(path);f<<"{\n  \"interface\": \"HDMI_2 TMDS/DVI 1280x720p60\",\n  \"submitted\": "<<submitted_
                <<",\n  \"last_ticket\": "<<regs_[5]<<",\n  \"scan_frames\": "<<uint32_t(regs_[6]-initial_frames_)
                <<",\n  \"scan_interval_s\": "<<seconds<<",\n  \"scan_refresh_hz\": "<<(seconds>0?uint32_t(regs_[6]-initial_frames_)/seconds:0)
                <<",\n  \"underruns\": "<<uint32_t(regs_[7]-initial_underflows_)<<",\n  \"axi_errors\": "<<uint32_t(regs_[8]-initial_errors_)<<"\n}\n";
            if(!f)throw std::runtime_error("HDMI report write failed");
        }
    };
    return std::make_unique<Hdmi>(impl_);
#else
    throw std::runtime_error("HDMI_2 requires the paired Linux UIO mapping");
#endif
}
Frame LiveOrb::extract(const GrayFrame &f,const Camera &c){
#if defined(__linux__)
    if(impl_->failed)throw std::runtime_error("ORB fault is latched: reset/reload required");
    if(f.width!=960||f.height!=720||f.pixels.size()!=960*720)throw std::runtime_error("Physical ORB input geometry mismatch");
    size_t bytes=0;uint32_t count=0;double start=threadCpuMs();
    if(orb_engine_run(&impl_->engine,f.pixels.data(),impl_->payload.data(),&bytes,&count,1000)){impl_->failed=true;throw std::runtime_error("PL ORB failed; stop and reset/reload before reuse");}
    return impl_->finishRecords(bytes,count,f.id,f.timestamp_ns,c,start);
#else
    (void)f;(void)c;throw std::runtime_error("Physical ORB backend unavailable");
#endif
}
Frame LiveOrb::extractDdr(unsigned offset,uint64_t sequence,uint64_t stamp,const Camera &c){
#if defined(__linux__)
    if(impl_->failed)throw std::runtime_error("ORB fault is latched: reset/reload required");
    if(!stamp||offset<ORB60_RX_BASE||offset>=ORB60_RX_BASE+3*ORB60_RX_STRIDE||(offset-ORB60_RX_BASE)%ORB60_RX_STRIDE)throw std::runtime_error("Invalid camera DDR receive slot");
    size_t bytes=0;uint32_t count=0;double start=threadCpuMs();orb_engine_publish_input();
    if(orb_engine_run_at(&impl_->engine,offset,0,impl_->payload.data(),&bytes,&count,1000)){impl_->failed=true;throw std::runtime_error("PL fault: retain DMA lease until reset/reload");}
    return impl_->finishRecords(bytes,count,sequence,stamp,c,start);
#else
    (void)offset;(void)sequence;(void)stamp;(void)c;throw std::runtime_error("Direct DDR camera backend requires Zynq Linux");
#endif
}
int readControlKey(){
#if defined(_WIN32)
    return _kbhit()?_getch():-1;
#elif defined(__linux__)
    pollfd p{STDIN_FILENO,POLLIN,0};if(poll(&p,1,0)>0){unsigned char c;if(::read(STDIN_FILENO,&c,1)==1)return c;}return -1;
#else
    return -1;
#endif
}
} // namespace zslam
