#pragma once
#include "demo_runtime.hpp"
#include <memory>

namespace demo {
// Lossy preview/NPU side branch. Its TCP writer never runs on capture/ORB/SLAM.
// A single pending JPEG bounds memory; slow clients replace that pending sample.
class ColorChannel {
    State&state_;std::string hello_;Socket listener_,active_=invalid_socket;
    std::mutex mutex_;std::unique_ptr<Packet> pending_;std::thread thread_;
    std::atomic<bool> stopping_{false};uint64_t sent_=0,dropped_=0,bytes_=0;
    void loop(){while(!stopping_){try{
        if(!readable(listener_,100))continue;Connection peer(::accept(listener_,nullptr,nullptr));if(peer.fd==invalid_socket)continue;
        struct Guard{ColorChannel&owner;Guard(ColorChannel&o,Socket fd):owner(o){std::lock_guard<std::mutex>l(owner.mutex_);owner.active_=fd;}
            ~Guard(){std::lock_guard<std::mutex>l(owner.mutex_);owner.active_=invalid_socket;}}guard(*this,peer.fd);peer.timeout(2);
        auto h=peer.receive();if(h.kind!=Hello||string(h.body)!=hello_)throw std::runtime_error("Color calibration handshake mismatch");
        auto accepted=response(Hello,hello_+"\n"+profile+"\nMJPEG1280x720-CROP160-V1");accepted.count=1;peer.send(accepted);
        while(!stopping_){std::unique_ptr<Packet>p;
            {std::lock_guard<std::mutex>l(mutex_);p=std::move(pending_);}
            if(!p){std::this_thread::sleep_for(std::chrono::milliseconds(5));continue;}
            bool current;{std::lock_guard<std::mutex>l(state_.mutex);current=state_.mode==Mode::Mapping&&p->session==state_.session;}
            if(!current){std::lock_guard<std::mutex>l(mutex_);dropped_++;continue;}
            peer.send(*p);{std::lock_guard<std::mutex>l(mutex_);sent_++;bytes_+=p->body.size();}
        }
    }catch(const std::exception&){/* Main gray/feature transport owns the fail-stop policy. */}
    }}
public:
    ColorChannel(State&s,const std::string&calibration,unsigned port):state_(s),hello_(calibration),listener_(listenSocket(port)){
        thread_=std::thread([this]{loop();});}
    ~ColorChannel(){stopping_=true;{std::lock_guard<std::mutex>l(mutex_);if(active_!=invalid_socket)shutdown(active_,2);}
        if(thread_.joinable())thread_.join();closeSocket(listener_);}
    void publish(uint64_t session,uint64_t frame,uint64_t stamp,uint32_t gray_crc,std::vector<uint8_t>jpeg){
        if(jpeg.empty())return;if(jpeg.size()>4*1024*1024)throw std::runtime_error("Color JPEG exceeds camera bound");
        auto p=std::make_unique<Packet>();p->kind=Color;p->session=session;p->frame=frame;p->stamp=stamp;p->aux=gray_crc;p->body=std::move(jpeg);
        std::lock_guard<std::mutex>l(mutex_);if(pending_)dropped_++;pending_=std::move(p);}
    std::string report(){std::lock_guard<std::mutex>l(mutex_);std::ostringstream o;
        o<<"{\"sent\":"<<sent_<<",\"dropped\":"<<dropped_<<",\"jpeg_bytes\":"<<bytes_<<",\"pending_capacity\":1}\n";return o.str();}
};
}
