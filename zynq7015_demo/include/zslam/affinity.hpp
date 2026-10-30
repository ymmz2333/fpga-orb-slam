#pragma once
#include <atomic>
#include <stdexcept>
#include <string>
#if defined(__linux__)
#include <sched.h>
#include <sys/syscall.h>
#include <unistd.h>
#endif
namespace zslam {
// This target has CPU0/1. Integer masks are explicit and remain process-local.
struct CpuPlan {unsigned capture=1,orb=2,slam=1,render=2;};
inline CpuPlan cpuPlan(const std::string &policy,bool async_display){
    if(policy=="legacy")return {async_display?1u:2u,2,1,2};
    if(policy=="capture-auto")return {3,2,1,2};
    if(policy=="capture-dedicated")return {1,2,2,2};
    throw std::runtime_error("Unknown CPU policy");
}
inline unsigned threadId(){
#if defined(__linux__)
    return static_cast<unsigned>(::syscall(SYS_gettid));
#else
    return 0;
#endif
}
inline unsigned cpuMask(unsigned tid=0){
#if defined(__linux__)
    cpu_set_t allowed;if(sched_getaffinity(tid,sizeof(allowed),&allowed))return 0;
    unsigned result=0;for(unsigned cpu=0;cpu<32&&cpu<CPU_SETSIZE;cpu++)if(CPU_ISSET(cpu,&allowed))result|=1u<<cpu;return result;
#else
    (void)tid;return 0;
#endif
}
inline bool setCpuMask(unsigned mask){
#if defined(__linux__)
    if(!mask||(cpuMask()&mask)!=mask)return false;
    cpu_set_t target;CPU_ZERO(&target);for(unsigned cpu=0;cpu<32&&cpu<CPU_SETSIZE;cpu++)if(mask&(1u<<cpu))CPU_SET(cpu,&target);
    return sched_setaffinity(0,sizeof(target),&target)==0;
#else
    (void)mask;return false;
#endif
}
struct AffinitySnapshot {unsigned tid=0,requested_mask=0,actual_mask=0;bool applied=false,live_read=false;};
class ThreadAffinityRecord {
    std::atomic<unsigned> tid_{0},requested_{0},actual_{0};std::atomic<bool> applied_{false};
public:
    void begin(unsigned mask,bool enable){requested_=enable?mask:0;applied_=enable&&setCpuMask(mask);actual_=cpuMask();tid_=threadId();}
    void refresh(){actual_=cpuMask();}
    AffinitySnapshot snapshot()const{
        AffinitySnapshot s;s.tid=tid_;s.requested_mask=requested_;s.applied=applied_;
        unsigned live=s.tid?cpuMask(s.tid):0;s.live_read=live!=0;s.actual_mask=live?live:actual_.load();return s;
    }
};
} // namespace zslam
