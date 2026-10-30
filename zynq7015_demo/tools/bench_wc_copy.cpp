#include <chrono>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <arm_neon.h>
#include <time.h>
extern "C" {
#include "engine.h"
}
using Clock=std::chrono::steady_clock;
double cpuMs(){timespec t{};if(clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t))throw std::runtime_error("CPU clock unavailable");return double(t.tv_sec)*1000+t.tv_nsec*1e-6;}
void neonCopy(uint8_t *d,const uint8_t *s,std::size_t n){
    while(n>=128){
        if(n>=512)__builtin_prefetch(s+256,0,1);
        uint8x16_t a=vld1q_u8(s),b=vld1q_u8(s+16),c=vld1q_u8(s+32),e=vld1q_u8(s+48);
        uint8x16_t f=vld1q_u8(s+64),g=vld1q_u8(s+80),h=vld1q_u8(s+96),i=vld1q_u8(s+112);
        vst1q_u8(d,a);vst1q_u8(d+16,b);vst1q_u8(d+32,c);vst1q_u8(d+48,e);
        vst1q_u8(d+64,f);vst1q_u8(d+80,g);vst1q_u8(d+96,h);vst1q_u8(d+112,i);
        s+=128;d+=128;n-=128;
    }
    if(n)std::memcpy(d,s,n);
}
int main(int argc,char **argv){
    orb_engine engine{};engine.fd=-1;bool opened=false;
    try {
        if(argc!=2)throw std::runtime_error("Usage: bench-wc-copy /dev/uioN; stop baseline first");
        std::string device=argv[1],name=device.substr(device.find_last_of('/')+1),version;
        std::ifstream vf("/sys/class/uio/"+name+"/version");std::getline(vf,version);
        if(version!="wc1")throw std::runtime_error("Paired WC provider required");
        if(orb_engine_open(&engine,argv[1]))throw std::runtime_error("Exclusive paired UIO open failed");
        opened=true;
        auto regs=engine.regs[0]+0x8000/4;
        if(regs[10]!=0x5a564431u||regs[11]!=((1280u<<16)|720u))throw std::runtime_error("Unexpected HDMI core");
        uint32_t active=regs[4],underflows=regs[7],errors=regs[8];
        if(active!=0x20b00000u&&active!=0x20d00000u)throw std::runtime_error("Active frame outside owned slots");
        uint32_t back=active==0x20b00000u?0x20d00000u:0x20b00000u;
        auto d=engine.ddr+(back-ORB60_DDR_BASE)+64;
        std::vector<uint8_t> source(1843200+32);for(std::size_t i=0;i<source.size();i++)source[i]=static_cast<uint8_t>(i*37+i/123);
        const std::size_t sizes[]={0,1,15,16,127,128,129,691200,1843200};
        for(std::size_t n:sizes)for(unsigned offset:{0u,1u,7u}){
            std::memset(d-32,0xa5,n+64);neonCopy(d,source.data()+offset,n);orb_engine_publish_input();
            if(std::memcmp(d,source.data()+offset,n))throw std::runtime_error("NEON byte mismatch");
            for(unsigned guard=0;guard<32;guard++)if(d[-32+int(guard)]!=0xa5||d[n+guard]!=0xa5)throw std::runtime_error("NEON guard overwrite");
        }
        std::puts("WC_NEON_BYTES_UNALIGNED_SOURCE_ZERO_TAIL_GUARDS_PASS");
        for(unsigned n:{691200u,1843200u})for(unsigned mode=0;mode<2;mode++){
            auto start=Clock::now();double before=cpuMs();constexpr unsigned repeats=64;
            for(unsigned k=0;k<repeats;k++){if(mode)neonCopy(d,source.data(),n);else std::memcpy(d,source.data(),n);orb_engine_publish_input();}
            double cpu=cpuMs()-before,wall=std::chrono::duration<double,std::milli>(Clock::now()-start).count();
            if(std::memcmp(d,source.data(),n))throw std::runtime_error("Timed copy mismatch");
            std::printf("COPY mode=%s bytes=%u repeats=%u wall_ms=%.6f cpu_ms=%.6f per_copy_cpu_ms=%.6f MBps=%.3f\n",mode?"neon128":"libc",n,repeats,wall,cpu,cpu/repeats,double(n)*repeats/1000/wall);
        }
        if(regs[4]!=active||regs[7]!=underflows||regs[8]!=errors)throw std::runtime_error("Scanout changed or faulted during inactive-slot benchmark");
        std::puts("INACTIVE_SLOT_ONLY_NO_PUBLICATION_SCANOUT_UNCHANGED_PASS");
        orb_engine_close(&engine);return 0;
    }catch(const std::exception &e){std::fprintf(stderr,"COPY_BENCH_FAILED: %s\n",e.what());if(opened)orb_engine_close(&engine);return 1;}
}
