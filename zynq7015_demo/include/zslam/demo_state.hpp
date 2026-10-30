#pragma once
#include <cstdint>
#include <algorithm>
#include <mutex>
#include <stdexcept>
#include <string>

namespace demo {
enum class Mode {Waiting,Mapping,Finalizing,Installing,Local,Stopped,Fault};
inline const char* name(Mode m){switch(m){case Mode::Waiting:return "WAITING";case Mode::Mapping:return "MAPPING";
case Mode::Finalizing:return "FINALIZING";case Mode::Installing:return "INSTALLING";case Mode::Local:return "LOCAL";
case Mode::Stopped:return "STOPPED";default:return "ERROR";}}
// All transitions are explicit. A network failure can never select local mode.
struct State {
    mutable std::mutex mutex;Mode mode=Mode::Waiting;uint64_t session=0,sent=0,acknowledged=0;
    unsigned consecutive=0;bool hardware_verified=false,hardware_fault=false,ready=false;
    std::string failure,version,pending_version;uint64_t map_id=0;
    bool start(uint64_t next){std::lock_guard<std::mutex>l(mutex);if(mode==Mode::Mapping)return false;
        if(hardware_fault||!hardware_verified||mode==Mode::Finalizing||mode==Mode::Installing)throw std::runtime_error("Hardware not ready or handover in progress");
        if(!next||next<=session)throw std::runtime_error("Session identity must increase");session=next;sent=acknowledged=0;consecutive=0;ready=false;failure.clear();mode=Mode::Mapping;return true;}
    void finalize(){std::lock_guard<std::mutex>l(mutex);if(mode==Mode::Mapping)mode=Mode::Finalizing;
        else if(mode!=Mode::Finalizing&&mode!=Mode::Installing&&mode!=Mode::Local)throw std::runtime_error("No mapping session to finalize");}
    void transportFailure(const std::string&why){std::lock_guard<std::mutex>l(mutex);if(mode==Mode::Mapping||mode==Mode::Finalizing){mode=Mode::Fault;failure=why;ready=false;}}
    void fault(const std::string&why,bool pl=false){std::lock_guard<std::mutex>l(mutex);failure=why;hardware_fault=hardware_fault||pl;mode=Mode::Fault;ready=false;consecutive=0;}
    void observe(bool valid){std::lock_guard<std::mutex>l(mutex);if(mode!=Mode::Local)return;consecutive=valid?std::min(30u,consecutive+1):0;ready=consecutive>=30;}
};
} // namespace demo
