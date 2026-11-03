#include "zslam/network_camera.hpp"
#include <iostream>
#include <limits>
#include <utility>

namespace zslam {namespace {
demo::Socket listen6(unsigned port){
    demo::socketInit();auto s=::socket(AF_INET6,SOCK_STREAM,0);
    if(s==demo::invalid_socket)throw std::runtime_error("Network camera socket failed");
    int yes=1,no=0;sockaddr_in6 addr{};addr.sin6_family=AF_INET6;addr.sin6_port=htons(uint16_t(port));
    bool failed=setsockopt(s,SOL_SOCKET,SO_REUSEADDR,reinterpret_cast<const char*>(&yes),sizeof(yes))!=0||
        setsockopt(s,IPPROTO_IPV6,IPV6_V6ONLY,reinterpret_cast<const char*>(&no),sizeof(no))!=0||
        ::bind(s,reinterpret_cast<sockaddr*>(&addr),sizeof(addr))!=0||::listen(s,1)!=0;
    if(failed){demo::closeSocket(s);throw std::runtime_error("Network camera bind/listen failed");}return s;
}
class NetworkCamera final:public CameraSource {
    demo::Connection listener_,peer_;std::string calibration_;unsigned mode_,limit_;
    uint64_t frames_=0,stamp_=0,gaps_=0;uint32_t previous_=0;bool failed_=false,manual_=false,ended_=false;std::string end_path_;std::ofstream journal_;
public:
    NetworkCamera(unsigned port,const std::string& calibration,unsigned mode,unsigned frames,const std::string& journal,bool manual):
        calibration_(demo::sha256(demo::readFile(calibration,4096))),mode_(mode),limit_(frames),manual_(manual),end_path_(journal+".end.json"),journal_(journal){
        if(port<1024||port>65535||mode>1||(manual?(mode!=0||frames!=0):(!frames||frames>36000))||!journal_)throw std::runtime_error("Explicit finite or manual network-camera configuration required");
        listener_.fd=listen6(port);journal_<<"frame_id,timestamp_ns,capture_sequence,sequence_gaps,gray_crc,input_mode\n";
        std::cout<<"NETWORK_CAMERA_READY port="<<port<<" mode="<<mode<<" calibration="<<calibration_<<'\n'<<std::flush;
    }
    bool next(GrayFrame& f)override{
        if(failed_)throw std::runtime_error("Network camera fault is latched; source cannot be reused");
        try {
        if(ended_||(!manual_&&frames_==limit_))return false;
        if(peer_.fd==demo::invalid_socket){fd_set reads;FD_ZERO(&reads);FD_SET(listener_.fd,&reads);timeval timeout{30,0};
#if defined(_WIN32)
            const int count=0;
#else
            const int count=listener_.fd+1;
#endif
            if(::select(count,&reads,nullptr,nullptr,&timeout)!=1)throw std::runtime_error("Network camera accept timed out");
            peer_.fd=::accept(listener_.fd,nullptr,nullptr);if(peer_.fd==demo::invalid_socket)throw std::runtime_error("Network camera accept failed");
            int yes=1;setsockopt(peer_.fd,IPPROTO_TCP,TCP_NODELAY,reinterpret_cast<const char*>(&yes),sizeof(yes));peer_.timeout(15);
        }
        std::array<uint8_t,128> h{};peer_.transfer(h.data(),h.size(),false);
        const uint32_t header_crc=demo::get32(h.data()+56);demo::put32(h.data()+56,0);
        if(!std::memcmp(h.data(),"ORBGRAY3",8)){
            if(!manual_||!frames_||demo::get32(h.data()+8)!=1||demo::get32(h.data()+12)!=128||
               demo::get64(h.data()+16)!=frames_||demo::get64(h.data()+24)!=stamp_||demo::get32(h.data()+32)||demo::get32(h.data()+36)||
               demo::get32(h.data()+40)!=960||demo::get32(h.data()+44)!=720||demo::get32(h.data()+48)!=mode_||
               demo::get32(h.data()+52)!=previous_||demo::get32(h.data()+60)!=1||demo::crc32(h.data(),h.size())!=header_crc||
               std::memcmp(h.data()+64,calibration_.data(),64))throw std::runtime_error("Invalid explicit manual network end");
            std::ofstream end(end_path_);end<<"{\"status\":\"OPERATOR_STREAM_END_RECEIVED\",\"frames\":"<<frames_<<"}\n";
            end.close();if(!end)throw std::runtime_error("Manual network end receipt write failed");
            std::array<uint8_t,32> ack{};std::memcpy(ack.data(),"ORBEND02",8);demo::put64(ack.data()+8,frames_);demo::put64(ack.data()+16,stamp_);
            demo::put32(ack.data()+28,demo::crc32(ack.data(),28));peer_.transfer(ack.data(),ack.size(),true);ended_=true;return false;
        }
        if(std::memcmp(h.data(),"ORBGRAY1",8)||demo::get32(h.data()+8)!=1||demo::get32(h.data()+12)!=128||
           demo::get32(h.data()+32)!=demo::image_bytes||demo::get32(h.data()+40)!=960||demo::get32(h.data()+44)!=720||
           demo::get32(h.data()+48)!=mode_||demo::get32(h.data()+60)||demo::crc32(h.data(),h.size())!=header_crc||
           std::memcmp(h.data()+64,calibration_.data(),64))throw std::runtime_error("Network camera header/format/mode/calibration mismatch");
        uint64_t id=demo::get64(h.data()+16),stamp=demo::get64(h.data()+24);uint32_t sequence=demo::get32(h.data()+52),delta=sequence-previous_;
        if(id!=frames_||!stamp||stamp<=stamp_||(mode_==1&&sequence!=id)||
           (mode_==0&&frames_&&(!delta||delta>=0x80000000u)))throw std::runtime_error("Network camera identity repeated/reordered");
        f.pixels.resize(demo::image_bytes);peer_.transfer(f.pixels.data(),f.pixels.size(),false);
        uint32_t crc=demo::crc32(f.pixels.data(),f.pixels.size());if(crc!=demo::get32(h.data()+36))throw std::runtime_error("Network camera pixels CRC mismatch");
        f.id=id;f.timestamp_ns=stamp;f.width=960;f.height=720;f.color_jpeg.clear();
        if(mode_==0&&frames_)gaps_+=delta-1;previous_=sequence;stamp_=stamp;frames_++;
        journal_<<id<<','<<stamp<<','<<sequence<<','<<gaps_<<','<<crc<<','<<mode_<<'\n';journal_.flush();
        if(!journal_)throw std::runtime_error("Network camera input journal failed");
        std::array<uint8_t,32> ack{};std::memcpy(ack.data(),"ORBGRAY2",8);demo::put64(ack.data()+8,id);demo::put64(ack.data()+16,stamp);
        demo::put32(ack.data()+24,crc);demo::put32(ack.data()+28,demo::crc32(ack.data(),28));peer_.transfer(ack.data(),ack.size(),true);return true;
        }catch(...){failed_=true;throw;}
    }
};
class PreflightCamera final:public CameraSource {
    std::unique_ptr<CameraSource> source_;GrayFrame first_;bool pending_=true;
public:
    PreflightCamera(std::unique_ptr<CameraSource> source,GrayFrame first):source_(std::move(source)),first_(std::move(first)){}
    bool next(GrayFrame& out)override{
        if(!pending_)return source_->next(out);pending_=false;
        out.id=first_.id;out.timestamp_ns=first_.timestamp_ns;out.width=first_.width;out.height=first_.height;
        out.pixels.resize(first_.pixels.size());std::memcpy(out.pixels.data(),first_.pixels.data(),first_.pixels.size());out.color_jpeg.clear();first_.pixels.clear();return true;
    }
    CameraCaptureProfile profile()const override{return source_->profile();}
};
}
std::unique_ptr<CameraSource> networkCamera(unsigned port,const std::string& calibration,unsigned mode,unsigned frames,const std::string& journal,bool manual){
    return std::make_unique<NetworkCamera>(port,calibration,mode,frames,journal,manual);
}
std::unique_ptr<CameraSource> replayPreflightCamera(std::unique_ptr<CameraSource> source,GrayFrame first){
    if(!source||first.width!=960||first.height!=720||first.pixels.size()!=demo::image_bytes||!first.timestamp_ns)throw std::runtime_error("Invalid real preflight frame");
    return std::make_unique<PreflightCamera>(std::move(source),std::move(first));
}
}
