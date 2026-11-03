// PS input transport only. The optional LAN sender emulates sensor bytes.
#pragma once
#include "Orb60Protocol.h"
#include <array>
#include <cerrno>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <netdb.h>
#include <poll.h>
#include <stdexcept>
#include <string>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
#include <vector>
namespace KvNetwork {
class PackedByteStream {
    std::ifstream file;int fd=-1,listener=-1;bool network=false,ended=false;std::streamsize count=0;
    std::vector<uint8_t> headers;size_t next_header=0;
    std::string trace_path,master_sha;
    void trace(const char* status) {
        if(trace_path.empty())return;
        std::ofstream out(trace_path+".tmp");out<<"{\"transport\":\"tcp_camera_emulator\",\"status\":\""<<status<<"\",\"master_sha256\":\""<<master_sha<<"\",\"headers_verified\":"<<next_header<<",\"expected_frames\":"<<headers.size()/32<<"}\n";out.close();
        if(!out||std::rename((trace_path+".tmp").c_str(),trace_path.c_str()))throw std::runtime_error("Cannot persist owned sensor-source trace");
    }
    void close_all(){if(fd>=0){::close(fd);fd=-1;}if(listener>=0){::close(listener);listener=-1;}}
    size_t receive(uint8_t* p,size_t bytes) {
        size_t used=0;
        while(used<bytes) {
            const auto n=::recv(fd,p+used,bytes-used,0);
            if(n==0){ended=true;break;}
            if(n<0){if(errno==EINTR)continue;throw std::runtime_error("Packed sensor stream receive failed/timed out");}
            used+=size_t(n);
        }
        return used;
    }
    static unsigned hex(char c){if(c>='0'&&c<='9')return c-'0';if(c>='a'&&c<='f')return c-'a'+10;if(c>='A'&&c<='F')return c-'A'+10;throw std::runtime_error("Invalid sensor source SHA256");}
    void listen_source(const std::string& endpoint) {
        const char* manifest=std::getenv("ORB60_PACKED_HEADERS");const char* sha=std::getenv("ORB60_PACKED_STREAM_SHA256");
        if(!manifest||!*manifest||!sha||std::strlen(sha)!=64)throw std::runtime_error("Explicit sensor-stream source/header proofs required");
        std::ifstream h(manifest,std::ios::binary);h.seekg(0,std::ios::end);const auto length=h.tellg();
        if(length<=0||length%32||length>8192*32)throw std::runtime_error("Sensor header manifest length mismatch");
        h.seekg(0);headers.resize(size_t(length));h.read(reinterpret_cast<char*>(headers.data()),length);
        if(h.gcount()!=length)throw std::runtime_error("Truncated sensor header manifest");
        std::string node,port;
        if(!endpoint.empty()&&endpoint[0]=='['){auto end=endpoint.find(']');if(end==std::string::npos||endpoint.substr(end+1,1)!=":")throw std::runtime_error("Expected [IPv6%interface]:port");node=endpoint.substr(1,end-1);port=endpoint.substr(end+2);}
        else{auto end=endpoint.rfind(':');if(end==std::string::npos)throw std::runtime_error("Expected sensor-listen address:port");node=endpoint.substr(0,end);port=endpoint.substr(end+1);}
        if(node.empty()||port.empty())throw std::runtime_error("Empty sensor-listen endpoint");
        addrinfo hint{};hint.ai_socktype=SOCK_STREAM;hint.ai_family=AF_UNSPEC;hint.ai_flags=AI_NUMERICHOST|AI_NUMERICSERV;addrinfo* info=nullptr;
        if(getaddrinfo(node.c_str(),port.c_str(),&hint,&info))throw std::runtime_error("Invalid numeric sensor-listen endpoint");
        for(auto p=info;p;p=p->ai_next) {
            int s=::socket(p->ai_family,p->ai_socktype,p->ai_protocol);if(s<0)continue;int yes=1;setsockopt(s,SOL_SOCKET,SO_REUSEADDR,&yes,sizeof(yes));
            if(!::bind(s,p->ai_addr,p->ai_addrlen)&&!::listen(s,1)){listener=s;break;}::close(s);
        }
        freeaddrinfo(info);if(listener<0)throw std::runtime_error("Cannot bind explicit sensor-listen endpoint");
        pollfd ready{listener,POLLIN,0};int status;
        do{status=::poll(&ready,1,180000);}while(status<0&&errno==EINTR);
        if(status<=0)throw std::runtime_error("No camera-emulation source connected within180seconds");
        fd=::accept(listener,nullptr,nullptr);if(fd<0)throw std::runtime_error("Cannot accept sensor-byte source");::close(listener);listener=-1;
        timeval timeout{20,0};if(setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout)))throw std::runtime_error("Cannot set bounded sensor receive timeout");
        uint8_t prelude[48];if(receive(prelude,48)!=48||std::memcmp(prelude,"ORBSTRM1",8)||orb_get64(prelude+40)!=headers.size()/32)throw std::runtime_error("Sensor source prelude/count mismatch");
        for(size_t i=0;i<32;++i)if(prelude[8+i]!=(hex(sha[i*2])*16+hex(sha[i*2+1])))throw std::runtime_error("Sensor source master SHA256 mismatch");
        master_sha=sha;const char* path=std::getenv("ORB60_PACKED_STREAM_STATUS");if(path&&*path)trace_path=path;trace("ACCEPTED");
    }
public:
    PackedByteStream(const std::string& path,std::ios::openmode mode) {
        try{network=path.compare(0,7,"listen:")==0;if(network)listen_source(path.substr(7));else file.open(path,mode);}
        catch(...){close_all();throw;}
    }
    ~PackedByteStream(){close_all();}
    explicit operator bool() const{return network?fd>=0:bool(file);}
    void read(char* p,std::streamsize bytes) {
        if(!network){file.read(p,bytes);count=file.gcount();return;}
        if(bytes!=32&&bytes!=960*720*2)throw std::runtime_error("Unexpected sensor read size");
        count=std::streamsize(receive(reinterpret_cast<uint8_t*>(p),size_t(bytes)));
        if(bytes==32) {
            if(count==0){if(next_header!=headers.size()/32)throw std::runtime_error("Sensor stream ended before all declared frames");trace("DRAINED");return;}
            if(count!=32||next_header>=headers.size()/32||std::memcmp(p,headers.data()+next_header*32,32))throw std::runtime_error("Sensor frame header differs from independently sealed source");
            ++next_header;
            if(next_header%30==0||next_header==headers.size()/32)trace("RECEIVING");
        }
    }
    std::streamsize gcount()const{return count;}
    bool eof()const{return network?ended:file.eof();}
};
}
