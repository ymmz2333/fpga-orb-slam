// GPL-3.0-or-later. Observation only: never changes matching or pose decisions.
#pragma once
#include <array>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <fstream>
#include <initializer_list>
#include <ostream>
#include <stdexcept>
#include <string>
#include <utility>

namespace ORB_SLAM3 { namespace BridgeDiag {
using Field=std::pair<const char*,double>;
// Storage is defined once in Tracking.cc. Worker threads remain disabled.
bool active();
void begin(uint64_t source_frame,uint64_t stamp,unsigned count,const uint8_t* records);
void event(const char* stage,std::initializer_list<Field> fields);
bool decision(const char* stage,bool accepted,int matches,int inliers);
void writeFrame(std::ostream&,int tracking_state,const double* valid_tcw);

template<class F> class Exit {
    F fn;
public:
    explicit Exit(F f):fn(std::move(f)){}
    Exit(Exit&& other):fn(std::move(other.fn)),enabled(other.enabled){other.enabled=false;}
    Exit(const Exit&)=delete;
    ~Exit(){if(enabled)fn();}
private: bool enabled=true;
};
template<class F> Exit<F> onExit(F f){return Exit<F>(std::move(f));}

// Four retained parts, 3000 frames each. No images or unbounded RAM queue.
class Writer {
    std::string directory;
    std::ofstream output;
    std::deque<std::string> owned;
    unsigned part=0,rows=0;
    int previous_state=-99;
    void open(){
        if(output.is_open()){output.close();if(!output)throw std::runtime_error("Diagnostic close failed");}
        char name[64];std::snprintf(name,sizeof(name),"/tracking_diagnostics.part%06u.jsonl",part++);
        const auto path=directory+name;
        {std::ifstream existing(path);if(existing.good())throw std::runtime_error("Diagnostic file already exists");}
        output.open(path);if(!output)throw std::runtime_error("Cannot open tracking diagnostics");
        owned.push_back(path);rows=0;
        while(owned.size()>4){if(std::remove(owned.front().c_str()))throw std::runtime_error("Diagnostic retention failed");owned.pop_front();}
    }
public:
    explicit Writer(std::string path):directory(std::move(path)){open();}
    void write(int state,const double* tcw){
        if(rows==3000)open();
        writeFrame(output,state,tcw);++rows;
        if(rows%30==0||state!=previous_state)output.flush();
        previous_state=state;
        if(!output)throw std::runtime_error("Tracking diagnostic write failed");
    }
    void finish(){output.close();if(!output)throw std::runtime_error("Tracking diagnostic close failed");}
};
} }
