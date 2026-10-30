// GPL-3.0-or-later. PC/PS adapter for exact R11 PL records over Ethernet.
#ifndef ORB_SLAM3_FPGA_ORB_H
#define ORB_SLAM3_FPGA_ORB_H
#include "Orb60Protocol.h"
#include "ORBextractor.h"
#include <cerrno>
#include <chrono>
#include <cstring>
#include <iostream>
#include <netdb.h>
#include <netinet/tcp.h>
#include <stdexcept>
#include <string>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
#include <vector>
namespace ORB_SLAM3 {
class FpgaORB {
protected:
    int fd=-1;
    std::string endpoint;
    uint64_t sequence=0;
    static void require(bool ok,const std::string& message) {
        if(!ok)throw std::runtime_error("FpgaORB: "+message);
    }
    void transfer(void *data,size_t size,bool sending) {
        uint8_t *p=static_cast<uint8_t *>(data);
        while(size) {
            ssize_t n=sending ? ::send(fd,p,size,MSG_NOSIGNAL) : ::recv(fd,p,size,0);
            if(n<0&&errno==EINTR)continue;
            require(n>0,"socket timeout/disconnect; no CPU ORB fallback");p+=n;size-=size_t(n);
        }
    }
    void connect(const std::string& selected) {
        if(fd>=0 && endpoint==selected)return;
        if(fd>=0){::close(fd);fd=-1;}
        std::string host,port="5600";
        if(!selected.empty()&&selected[0]=='[') {
            size_t end=selected.find(']');require(end!=std::string::npos,"bracketed IPv6 endpoint required");
            host=selected.substr(1,end-1);
            if(end+1<selected.size()){require(selected[end+1]==':',"endpoint port syntax");port=selected.substr(end+2);}
        }else {
            size_t colon=selected.find(':');require(colon==selected.rfind(':'),"use [IPv6%interface]:port");
            host=selected.substr(0,colon);if(colon!=std::string::npos)port=selected.substr(colon+1);
        }
        require(!host.empty()&&!port.empty(),"missing endpoint");
        struct addrinfo hint={};hint.ai_socktype=SOCK_STREAM;struct addrinfo *list=nullptr;
        int error=::getaddrinfo(host.c_str(),port.c_str(),&hint,&list);
        require(error==0,std::string("endpoint lookup: ")+gai_strerror(error));
        for(auto a=list;a;a=a->ai_next) {
            fd=::socket(a->ai_family,a->ai_socktype,a->ai_protocol);if(fd<0)continue;
            struct timeval timeout={10,0};int yes=1;
            ::setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));
            ::setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
            ::setsockopt(fd,IPPROTO_TCP,TCP_NODELAY,&yes,sizeof(yes));
            if(::connect(fd,a->ai_addr,a->ai_addrlen)==0)break;
            ::close(fd);fd=-1;
        }
        ::freeaddrinfo(list);require(fd>=0,"cannot connect to Zynq");endpoint=selected;
    }
    static void decode(const std::vector<uint8_t>& payload,unsigned count,ORBextractor *extractor,
                       std::vector<cv::KeyPoint>& keys,cv::Mat& descriptors,double& decode_ms) {
        require(extractor->GetFeatures()==1000&&extractor->GetLevels()==8&&extractor->GetScaleFactor()==1.2f,"fixed FPGA profile");
        require(count<=1000&&payload.size()==128+count*64+1024,"record length");
        auto start=std::chrono::steady_clock::now();
        const unsigned budgets[8]={217,181,151,126,105,87,73,60};
        const unsigned widths[8]={960,800,667,556,463,386,322,268};
        const unsigned heights[8]={720,600,500,417,347,289,241,201};
        auto scales=extractor->GetScaleFactors();unsigned total=0;
        keys.resize(count);if(count)descriptors.create(int(count),32,CV_8UC1);else descriptors.release();
        for(unsigned l=0;l<8;++l) {
            unsigned n=orb_get32(payload.data()+4*l),offset=orb_get32(payload.data()+32+4*l);
            require(offset==total&&n<=budgets[l]&&n<=count-total,"layer count/order");
            const uint8_t *stats=payload.data()+128+count*64+l*128;
            require(orb_get32(stats)==0x600003&&orb_get32(stats+4)==0&&orb_get32(stats+8)==l
                &&orb_get32(stats+12)==widths[l]&&orb_get32(stats+16)==heights[l]&&orb_get32(stats+44)>0,"image stats ABI");
            require(orb_get32(stats+64)==0x600002&&orb_get32(stats+68)==0&&orb_get32(stats+72)==l
                &&orb_get32(stats+76)==n&&orb_get32(stats+80)==n&&orb_get32(stats+84)==offset
                &&orb_get32(stats+104)>0,"descriptor stats ABI");
            for(unsigned j=0;j<n;++j) {
                unsigned index=total+j;const uint8_t *r=payload.data()+128+64*index;
                unsigned x=orb_get32(r),y=orb_get32(r+4),score=orb_get32(r+8),octave=orb_get32(r+12);
                unsigned bin=orb_get32(r+16),angle=orb_get32(r+28);
                require(x<widths[l]&&y<heights[l]&&score>0&&score<=255&&octave==l&&bin<32&&angle==bin*737280u,"PL feature layout");
                auto& k=keys[index];k.pt=cv::Point2f(float(x)*scales[l],float(y)*scales[l]);
                k.octave=int(l);k.angle=float(angle)/65536.f;k.size=31.f*scales[l];k.response=float(score);k.class_id=-1;
                require(k.pt.x<960&&k.pt.y<720,"scaled coordinate");std::memcpy(descriptors.ptr(int(index)),r+32,32);
            }
            total+=n;
        }
        require(total==count,"frame count");
        for(unsigned i=80;i<128;++i)require(payload[i]==0,"metadata reserved");
        decode_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
    }
public:
    FpgaORB()=default;
    FpgaORB(const FpgaORB&)=delete;
    FpgaORB& operator=(const FpgaORB&)=delete;
    ~FpgaORB(){if(fd>=0)::close(fd);}
    int extract(const std::string& selected,uint64_t timestamp,int role,ORBextractor *extractor,
                const cv::Mat& image,std::vector<cv::KeyPoint>& keys,cv::Mat& descriptors,
                double& network_ms,double& decode_ms) {
        require(image.type()==CV_8UC1&&image.cols==960&&image.rows==720,"960x720 GRAY8 required");
        require(extractor->GetFeatures()==1000&&extractor->GetLevels()==8&&extractor->GetScaleFactor()==1.2f,
                "fixed PL profile requires1000 features,8 levels,1.2 scale");
        connect(selected);
        try {
            using Clock=std::chrono::steady_clock;auto start=Clock::now();
            cv::Mat contiguous=image.isContinuous()?image:image.clone();
            uint8_t request[64]={};std::memcpy(request,"ORB60NET",8);
            orb_put32(request+8,0x00400001u);orb_put32(request+12,ORB60_FRAME);
            uint64_t id=++sequence;orb_put64(request+16,id);orb_put64(request+24,timestamp);
            orb_put32(request+32,960);orb_put32(request+36,720);orb_put32(request+40,unsigned(role));
            orb_put32(request+44,1000);orb_put32(request+48,ORB60_IMAGE_BYTES);
            orb_put32(request+56,orb_crc32(contiguous.data,ORB60_IMAGE_BYTES));
            transfer(request,sizeof(request),true);transfer(contiguous.data,ORB60_IMAGE_BYTES,true);
            uint8_t reply[64];transfer(reply,sizeof(reply),false);
            require(std::memcmp(reply,"ORB60NET",8)==0&&orb_get32(reply+8)==0x00400001u
                &&orb_get32(reply+12)==ORB60_RESULT&&orb_get64(reply+16)==id&&orb_get64(reply+24)==timestamp
                &&orb_get32(reply+32)==960&&orb_get32(reply+36)==720&&orb_get32(reply+40)==unsigned(role),"reply identity/ABI");
            unsigned count=orb_get32(reply+44),bytes=orb_get32(reply+48);
            require(bytes<=ORB60_RESULT_MAX,"reply capacity");std::vector<uint8_t> payload(bytes);
            transfer(payload.data(),payload.size(),false);
            network_ms=std::chrono::duration<double,std::milli>(Clock::now()-start).count();start=Clock::now();
            require(orb_get32(reply+56)==orb_crc32(payload.data(),payload.size()),"reply CRC");
            require(orb_get32(reply+52)==0,"PL reported error");
            require(orb_get32(reply+60)==0,"simulated backend refused");
            require(count<=1000&&bytes==128+count*64+1024,"result record length");
            decode(payload,count,extractor,keys,descriptors,decode_ms);
            std::cout<<"FPGA_ORB_NET frame="<<id<<" role="<<role<<" count="<<count
                     <<" engine_ns="<<orb_get64(payload.data()+64)<<" network_ms="<<network_ms<<" record_crc="<<orb_crc32(payload.data()+128,count*64)<<" cpu_orb=0"<<std::endl;
            return int(count);
        }catch(...) {::close(fd);fd=-1;throw;}
    }
};
}
#endif
