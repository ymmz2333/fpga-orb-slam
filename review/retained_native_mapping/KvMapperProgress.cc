#include "KvMapperProgress.h"
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <set>
#include <stdexcept>
#include <string>
namespace KvMapperProgress {
namespace {
std::mutex mutex;std::condition_variable changed;std::set<const void*> pending;
uint64_t submitted_count=0,published_count=0;std::string failure;
void fail(const char* why){if(failure.empty())failure=why;changed.notify_all();}
}
void submitted(const void* keyframe) {
    std::lock_guard<std::mutex> lock(mutex);
    if(!keyframe||pending.size()>=64||!pending.insert(keyframe).second){fail("Invalid/duplicate/unbounded mapper submission");return;}
    ++submitted_count;changed.notify_all();
}
void published(const void* keyframe) {
    std::lock_guard<std::mutex> lock(mutex);
    if(!pending.erase(keyframe)){fail("Mapper published an unknown keyframe");return;}
    ++published_count;changed.notify_all();
}
double wait(unsigned timeout_ms) {
    if(!timeout_ms||timeout_ms>10000)throw std::runtime_error("Invalid mapper publication timeout");
    const auto started=std::chrono::steady_clock::now();std::unique_lock<std::mutex> lock(mutex);
    if(!changed.wait_for(lock,std::chrono::milliseconds(timeout_ms),[]{return !failure.empty()||pending.empty();}))
        throw std::runtime_error("Mapper publication timed out; submitted geometry is incomplete");
    if(!failure.empty())throw std::runtime_error(failure);
    return std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();
}
Counts counts(){std::lock_guard<std::mutex> lock(mutex);return {submitted_count,published_count,pending.size()};}
#ifdef KV_MAPPER_PROGRESS_TEST
void reset_for_test(){std::lock_guard<std::mutex> lock(mutex);pending.clear();failure.clear();submitted_count=published_count=0;}
#endif
}
