#include "zslam/demo_runtime.hpp"
#include "zslam/demo_color.hpp"
#include <iostream>
#include <cassert>

int main(int argc,char**argv){using namespace demo;try{
    if(argc==5&&std::string(argv[1])=="--serve-color-test"){
        State state;state.mode=Mode::Mapping;state.session=77;auto jpeg=readFile(argv[3]);
        ColorChannel channel(state,argv[4],unsigned(std::stoul(argv[2])));
        const auto start=std::chrono::steady_clock::now();uint64_t frame=0;
        while(std::chrono::steady_clock::now()-start<std::chrono::seconds(4)){
            frame++;channel.publish(77,frame,frame*500000000+1000000000,123,jpeg);
            std::this_thread::sleep_for(std::chrono::milliseconds(5));}
        std::cout<<channel.report();return 0;}
    if(argc==4&&std::string(argv[1])=="--current-test"){MapStore store(argv[2],argv[3]);std::cout<<store.current()<<'\n';return 0;}
    if(argc>=2&&std::string(argv[1])=="--wire"){
        auto raw=readFile(argv[2]);if(raw.size()<64)throw std::runtime_error("Truncated input");std::array<uint8_t,64>h;std::copy(raw.begin(),raw.begin()+64,h.begin());auto p=Packet::parse(h);
        if(raw.size()!=64+p.body.size())throw std::runtime_error("Body length mismatch");p.body.assign(raw.begin()+64,raw.end());if(crc32(p.body.data(),p.body.size())!=get32(h.data()+52))throw std::runtime_error("CRC differs");
        auto encoded=p.header();std::vector<uint8_t>out(encoded.begin(),encoded.end());out.insert(out.end(),p.body.begin(),p.body.end());writeFile(argv[3],out);return 0;}
    if(argc>=2&&std::string(argv[1])=="--serve-test"){
        if(argc!=8)throw std::runtime_error("test arguments");State s;s.hardware_verified=true;MapStore maps(argv[2],argv[3]);Runtime runtime(s,maps,argv[3],unsigned(std::stoul(argv[4])),unsigned(std::stoul(argv[5])),unsigned(std::stoul(argv[6])));
        const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(std::stoul(argv[7]));uint64_t frame=0;
        while(std::chrono::steady_clock::now()<end){Mode mode;std::string pending;{std::lock_guard<std::mutex>l(s.mutex);mode=s.mode;pending=std::move(s.pending_version);s.pending_version.clear();}
            if(!pending.empty()){maps.publish(pending);std::lock_guard<std::mutex>l(s.mutex);s.version=pending;s.mode=Mode::Local;}
            if(mode==Mode::Mapping){Packet p;p.kind=demo::Frame;p.frame=++frame;p.stamp=frame*33333333+1000000000;p.body={1,2,3};runtime.enqueue(std::move(p));}
            // Explicit protocol test fixture only. Production zynq-demo has no synthetic backend.
            if(mode==Mode::Local)s.observe(true);
            std::this_thread::sleep_for(std::chrono::milliseconds(10));}
        std::cout<<runtime.status()<<'\n';return 0;}
    assert(sha256({})=="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    assert(sha256(bytes("abc"))=="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    assert(crc32(reinterpret_cast<const uint8_t*>("123456789"),9)==0xcbf43926u);
    State s;bool rejected=false;try{s.start(1);}catch(...){rejected=true;}assert(rejected);s.hardware_verified=true;s.start(1);s.start(2);assert(s.session==1);
    s.transportFailure("test loss");assert(s.mode==Mode::Fault&&!s.ready);s.start(2);s.finalize();assert(s.mode==Mode::Finalizing);
    s.mode=Mode::Local;for(int i=0;i<29;i++)s.observe(true);assert(!s.ready);s.observe(true);assert(s.ready);s.observe(false);assert(!s.ready);
    s.hardware_fault=true;rejected=false;try{s.start(3);}catch(...){rejected=true;}assert(rejected);
    std::cout<<"BRIDGE_CORE_PASS native_only\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
