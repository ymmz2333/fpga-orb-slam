#pragma once
#include "pipeline.hpp"
#include <stdexcept>
namespace zslam {
// A bounded, ordered consumer. finish drains; destruction cancels queued work.
// The consumer must own immutable packets and have a bounded callback duration.
template<class T,std::size_t Capacity=2>class AsyncStage {
    BoundedQueue<T,Capacity> queue_;
    std::mutex mutex_;std::exception_ptr error_;
    std::atomic<bool> pinned_{false};std::thread worker_;
    ThreadAffinityRecord affinity_;
    void check(){std::lock_guard<std::mutex> lock(mutex_);if(error_)std::rethrow_exception(error_);}
    void join(){if(worker_.joinable())worker_.join();}
public:
    explicit AsyncStage(std::function<void(T&&)> work,bool affinity=false,unsigned mask=2){
        worker_=std::thread([this,work=std::move(work),affinity,mask](){
            try {
                affinity_.begin(mask,affinity);pinned_=affinity_.snapshot().applied;
                T value;while(queue_.pop(value))work(std::move(value));
                affinity_.refresh();
            }catch(...){
                {std::lock_guard<std::mutex> lock(mutex_);error_=std::current_exception();}
                queue_.close(true);
            }
        });
    }
    ~AsyncStage(){queue_.close(true);join();}
    void submit(T value){if(!queue_.push(std::move(value))){check();throw std::runtime_error("Async consumer closed");}check();}
    void finish(){queue_.close();join();check();}
    bool pinned()const{return pinned_;}
    AffinitySnapshot affinity()const{return affinity_.snapshot();}
};
}
