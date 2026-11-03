// Read-only, per-task Linux CPU sampling for an explicitly selected owned run.
// No sysctl, driver, firmware, affinity, scheduling or target-memory writes.
#include <linux/perf_event.h>
#include <sys/syscall.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <signal.h>
#include <dirent.h>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {
void require(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
std::string read(const std::string& path){std::ifstream f(path);return {std::istreambuf_iterator<char>(f),{}};}
struct DirCloser {void operator()(DIR* p)const{if(p)closedir(p);}};
struct Counter {
    int fd=-1,tid=0;size_t page=0,size=0;void* memory=MAP_FAILED;uint64_t tail=0;
    explicit Counter(int task):tid(task) {
        perf_event_attr a{};a.type=PERF_TYPE_SOFTWARE;a.size=sizeof(a);
        a.config=PERF_COUNT_SW_CPU_CLOCK;a.sample_period=10000000;
        a.sample_type=PERF_SAMPLE_IP|PERF_SAMPLE_TID|PERF_SAMPLE_TIME|PERF_SAMPLE_CALLCHAIN;
        a.disabled=1;a.exclude_kernel=1;a.exclude_hv=1;a.exclude_callchain_kernel=1;
        a.sample_max_stack=64;a.wakeup_events=1;
        fd=int(syscall(__NR_perf_event_open,&a,tid,-1,-1,PERF_FLAG_FD_CLOEXEC));
        if(fd<0)throw std::runtime_error("perf_event_open failed: "+std::string(strerror(errno)));
        page=size_t(sysconf(_SC_PAGESIZE));size=page*8;
        memory=mmap(nullptr,page+size,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
        if(memory==MAP_FAILED){close(fd);fd=-1;throw std::runtime_error("perf mmap failed");}
        if(ioctl(fd,PERF_EVENT_IOC_RESET,0)||ioctl(fd,PERF_EVENT_IOC_ENABLE,0)) {
            munmap(memory,page+size);close(fd);fd=-1;throw std::runtime_error("perf counter enable failed");
        }
    }
    ~Counter(){if(fd>=0){ioctl(fd,PERF_EVENT_IOC_DISABLE,0);munmap(memory,page+size);close(fd);}}
    void copy(void* output,uint64_t position,size_t count) {
        const auto* data=static_cast<const unsigned char*>(memory)+page;
        auto* out=static_cast<unsigned char*>(output);
        for(size_t i=0;i<count;++i)out[i]=data[(position+i)%size];
    }
    void drain(std::ostream& out,uint64_t& samples,uint64_t& lost) {
        auto* meta=static_cast<perf_event_mmap_page*>(memory);
        const auto head=__atomic_load_n(&meta->data_head,__ATOMIC_ACQUIRE);
        require(head>=tail&&head-tail<=size,"perf ring overflow: evidence incomplete");
        while(tail<head) {
            perf_event_header h{};require(head-tail>=sizeof(h),"truncated perf header");copy(&h,tail,sizeof(h));
            require(h.size>=sizeof(h)&&h.size<=size&&tail+h.size<=head,"invalid perf record length");
            std::vector<unsigned char> record(h.size);copy(record.data(),tail,h.size);tail+=h.size;
            auto u64=[&](size_t off){require(off+8<=record.size(),"truncated perf sample");uint64_t v;std::memcpy(&v,record.data()+off,8);return v;};
            if(h.type==PERF_RECORD_SAMPLE) {
                const auto ip=u64(8),ids=u64(16),time=u64(24),nr=u64(32);
                require(nr<=1024&&40+nr*8==record.size(),"invalid perf callchain");
                const uint32_t pid=uint32_t(ids),sample_tid=uint32_t(ids>>32);
                require(int(sample_tid)==tid,"unexpected sampled task");
                out<<"{\"type\":\"sample\",\"pid\":"<<pid<<",\"tid\":"<<sample_tid<<",\"time_ns\":"<<time
                   <<",\"ip\":\"0x"<<std::hex<<ip<<std::dec<<"\",\"callchain\":[";
                for(uint64_t i=0;i<nr;++i){if(i)out<<',';out<<"\"0x"<<std::hex<<u64(40+8*i)<<std::dec<<'"';}
                out<<"]}\n";++samples;
            } else if(h.type==PERF_RECORD_LOST) {
                lost+=u64(16);out<<"{\"type\":\"lost\",\"tid\":"<<tid<<",\"lost\":"<<u64(16)<<"}\n";
            } else if(h.type==PERF_RECORD_LOST_SAMPLES) {
                lost+=u64(8);out<<"{\"type\":\"lost\",\"tid\":"<<tid<<",\"lost\":"<<u64(8)<<"}\n";
            } else {
                out<<"{\"type\":\"other\",\"tid\":"<<tid<<",\"record_type\":"<<h.type<<"}\n";
                if(h.type==PERF_RECORD_THROTTLE)++lost;
            }
        }
        __atomic_store_n(&meta->data_tail,tail,__ATOMIC_RELEASE);
        require(bool(out),"sample output write failed");
    }
};
}

int main(int argc,char** argv){try {
    require(argc==4,"Usage: sample_native_cpu PID EXISTING_FRESH_OUTPUT_DIR MAX_SECONDS");
    const int pid=std::stoi(argv[1]),seconds=std::stoi(argv[3]);require(pid>1&&seconds>0&&seconds<=600,"invalid explicit sampling bound");
    const std::string folder=argv[2],proc="/proc/"+std::to_string(pid);
    require(access((folder+"/samples.jsonl").c_str(),F_OK)!=0,"fresh sample output required");
    const auto maps=read(proc+"/maps");require(!maps.empty(),"target maps unreadable");
    {std::ofstream f(folder+"/maps.txt");f<<maps;require(bool(f),"maps write failed");}
    std::vector<std::unique_ptr<Counter>> events;
    std::unique_ptr<DIR,DirCloser> tasks(opendir((proc+"/task").c_str()));require(bool(tasks),"target tasks unreadable");
    {std::ofstream f(folder+"/threads.jsonl");
     while(auto* entry=readdir(tasks.get())) {
        if(entry->d_name[0]=='.')continue;
        const int tid=std::stoi(entry->d_name);
        events.emplace_back(new Counter(tid));
        f<<"{\"tid\":"<<tid<<",\"main\":"<<(tid==pid?"true":"false")<<"}\n";
     }
     require(bool(f)&&!events.empty(),"task capture incomplete");}
    std::ofstream output(folder+"/samples.jsonl");require(bool(output),"cannot open sample output");
    uint64_t samples=0,lost=0;const auto start=std::chrono::steady_clock::now();
    std::cout<<"NATIVE_CPU_SAMPLER_STARTED tasks="<<events.size()<<std::endl;
    for(;;) {
        for(auto& e:events)e->drain(output,samples,lost);
        if(kill(pid,0)&&errno==ESRCH)break;
        if(std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()>=seconds)break;
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    for(auto& e:events){ioctl(e->fd,PERF_EVENT_IOC_DISABLE,0);e->drain(output,samples,lost);}
    output.close();require(bool(output),"sample close failed");
    std::ofstream final_maps(folder+"/maps_final.txt");final_maps<<read(proc+"/maps");
    const auto elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    std::ofstream result(folder+"/SAMPLER.json");result<<"{\"status\":\""<<(samples&&!lost?"NATIVE_CPU_SAMPLES_RECORDED":"FAILED_INCOMPLETE_SAMPLING")
      <<"\",\"pid\":"<<pid<<",\"sample_period_cpu_ns\":10000000,\"tasks\":"<<events.size()<<",\"samples\":"<<samples
      <<",\"lost\":"<<lost<<",\"elapsed_wall_seconds\":"<<elapsed<<",\"scope\":\"CPU diagnostic only, no performance acceptance\"}\n";
    require(bool(result)&&samples&&!lost,"no complete CPU sample evidence");
    std::cout<<"NATIVE_CPU_SAMPLES_RECORDED samples="<<samples<<std::endl;return 0;
}catch(const std::exception& error){std::cerr<<"NATIVE_CPU_SAMPLER_FAILED: "<<error.what()<<std::endl;return 1;}}
