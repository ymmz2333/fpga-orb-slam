#pragma once
#include "ports.hpp"
#include "profiling.hpp"
#include "affinity.hpp"
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <exception>
#include <functional>
#include <mutex>
#include <thread>
#if defined(__linux__)
#include <sched.h>
#endif

namespace zslam {
inline bool preferCpu(unsigned cpu){
    return cpu<32&&setCpuMask(1u<<cpu);
}
template<class T,std::size_t Capacity>class BoundedQueue {
    static_assert(Capacity>0,"Queue capacity must be positive");
    std::mutex mutex_;std::condition_variable changed_;std::deque<T> values_;bool closed_=false;
public:
    bool push(T value){std::unique_lock<std::mutex> lock(mutex_);
        changed_.wait(lock,[&](){return closed_||values_.size()<Capacity;});
        if(closed_)return false;values_.push_back(std::move(value));changed_.notify_all();return true;}
    bool pop(T &value){std::unique_lock<std::mutex> lock(mutex_);
        changed_.wait(lock,[&](){return closed_||!values_.empty();});
        if(values_.empty())return false;value=std::move(values_.front());values_.pop_front();changed_.notify_all();return true;}
    void close(bool discard=false){std::lock_guard<std::mutex> lock(mutex_);closed_=true;if(discard)values_.clear();changed_.notify_all();}
};
struct PipelineFrame {
    GrayFrame gray;Frame features;std::vector<uint8_t> raw_payload;double capture_ms=0,orb_ms=0,capture_cpu_ms=0,orb_cpu_ms=0;
    std::chrono::steady_clock::time_point capture_start;
};
// Ten leases cover capture, both depth-two input queues, ORB, SLAM,
// the depth-two render queue and renderer. No growth or blocking on exhaustion.
// Only the final image consumer returns a buffer; ORB never releases it early.
class GrayBufferPool {
    std::mutex mutex_;std::vector<std::vector<uint8_t>> free_;
public:
    static constexpr std::size_t bytes_per_frame=960*720,capacity=10;
    GrayBufferPool(){free_.reserve(capacity);for(std::size_t i=0;i<capacity;i++)free_.emplace_back(bytes_per_frame);}
    std::vector<uint8_t> acquire(){std::lock_guard<std::mutex> lock(mutex_);
        if(free_.empty())throw std::runtime_error("Gray buffer ownership bound exceeded");
        auto value=std::move(free_.back());free_.pop_back();return value;}
    void release(std::vector<uint8_t> value){
        if(value.empty())return;
        if(value.size()!=bytes_per_frame||value.capacity()!=bytes_per_frame)throw std::runtime_error("Invalid recycled gray buffer");
        std::lock_guard<std::mutex> lock(mutex_);if(free_.size()==capacity)throw std::runtime_error("Duplicate gray buffer return");
        free_.push_back(std::move(value));}
    std::size_t reservedBytes()const{return bytes_per_frame*capacity;}
};
// One capture owner, one ORB owner, bounded queues, FIFO ordering, no frame drops.
// SLAM and UI have distinct owners; HDMI is disjoint from ORB DDR.
class FramePipeline {
    BoundedQueue<PipelineFrame,2> captured_,extracted_;
    std::atomic<bool> stopped_{false};std::mutex error_mutex_;std::exception_ptr error_;
    std::thread capture_thread_,orb_thread_;
    std::atomic<bool> capture_pinned_{false},orb_pinned_{false};
    ThreadAffinityRecord capture_affinity_,orb_affinity_;
    void fail(){
        {std::lock_guard<std::mutex> lock(error_mutex_);if(!error_)error_=std::current_exception();}
        cancel();
    }
    void cancel(){stopped_=true;captured_.close(true);extracted_.close(true);}
    void join(){if(capture_thread_.joinable())capture_thread_.join();if(orb_thread_.joinable())orb_thread_.join();}
public:
    FramePipeline(CameraSource &source,std::function<Frame(const GrayFrame&)> extract,unsigned limit,bool affinity=false,unsigned capture_cpu=1,std::shared_ptr<GrayBufferPool> buffers=nullptr,std::function<std::vector<uint8_t>()> payload={},unsigned capture_mask=0,unsigned orb_mask=2){
        using Clock=std::chrono::steady_clock;
        try {
            capture_thread_=std::thread([&,limit,affinity,capture_cpu,buffers,capture_mask](){try {
                capture_affinity_.begin(capture_mask?capture_mask:(capture_cpu<32?1u<<capture_cpu:0),affinity);capture_pinned_=capture_affinity_.snapshot().applied;
                unsigned count=0;
                while(!stopped_&&(!limit||count<limit)){
                    PipelineFrame f;f.capture_start=Clock::now();double cpu_start=threadCpuMs();
                    if(buffers)f.gray.pixels=buffers->acquire();if(!source.next(f.gray))break;
                    f.capture_cpu_ms=threadCpuMs()-cpu_start;
                    f.capture_ms=std::chrono::duration<double,std::milli>(Clock::now()-f.capture_start).count();
                    if(!captured_.push(std::move(f)))break;count++;
                }
                capture_affinity_.refresh();captured_.close();
            }catch(...){fail();}});
            orb_thread_=std::thread([this,extract,affinity,orb_mask,payload](){try {
                orb_affinity_.begin(orb_mask,affinity);orb_pinned_=orb_affinity_.snapshot().applied;
                PipelineFrame f;
                while(!stopped_&&captured_.pop(f)){
                    auto start=Clock::now();double cpu_start=threadCpuMs();f.features=extract(f.gray);f.orb_cpu_ms=threadCpuMs()-cpu_start;
                    if(payload)f.raw_payload=payload();
                    f.orb_ms=std::chrono::duration<double,std::milli>(Clock::now()-start).count();
                    if(!extracted_.push(std::move(f)))break;
                }
                orb_affinity_.refresh();extracted_.close();
            }catch(...){fail();}});
        }catch(...){cancel();join();throw;}
    }
    ~FramePipeline(){cancel();join();}
    bool next(PipelineFrame &f){bool okay=extracted_.pop(f);
        std::lock_guard<std::mutex> lock(error_mutex_);if(error_)std::rethrow_exception(error_);return okay;}
    bool workersPinned()const{return capture_pinned_&&orb_pinned_;}
    AffinitySnapshot captureAffinity()const{return capture_affinity_.snapshot();}
    AffinitySnapshot orbAffinity()const{return orb_affinity_.snapshot();}
    FramePipeline(const FramePipeline&)=delete;FramePipeline &operator=(const FramePipeline&)=delete;
};
} // namespace zslam
