#pragma once
#include "slam.hpp"
#include <fstream>
#include <map>
#include <deque>

namespace zslam {
// Single extraction-owner cache. Tags include integer pyramid coordinates;
// any camera-field bit change invalidates entries. Collisions recompute exactly.
class RecordDecodeCache {
    struct Entry {uint32_t tag=0;V2 uv;};
    static constexpr unsigned capacity_=65536;
    std::vector<Entry> entries_;Camera camera_;std::array<uint64_t,11> signature_{};
    bool prepared_=false;uint64_t hits_=0,misses_=0;
    void begin(const Camera&);
    V2 get(uint32_t,V2);
    friend Frame decodeRecords(const uint8_t*,std::size_t,uint64_t,uint64_t,const Camera&,RecordDecodeCache*);
public:
    RecordDecodeCache():entries_(capacity_){}
    uint64_t hits()const{return hits_;}uint64_t misses()const{return misses_;}
    std::size_t reservedBytes()const{return entries_.capacity()*sizeof(Entry);}
};
using Row=std::map<std::string,std::string>;
std::vector<std::string> csvFields(const std::string&);
class Csv {
    std::ifstream stream_;std::vector<std::string> header_;
public:
    explicit Csv(const std::string&);
    bool next(Row&);
};
uint64_t integer(const Row&,const std::string&);
double number(const Row&,const std::string&);
Pose readTwc(const Row&);
Camera readCamera(const std::string&,bool source_geometry=false);
class Replay {
    Csv csv_;std::ifstream records_;
    Camera camera_;uint64_t offset_=0,index_=0;
public:
    Replay(const std::string &folder,Camera);
    bool next(Frame&);
};
// A single writer owns each CSV. Rotation removes only paths it created.
class CsvLog {
    std::ofstream stream_;std::string base_,header_;std::deque<std::string> owned_;
    uint64_t part_=0,rows_=0;unsigned limit_,keep_,precision_;bool finished_=false;
    void openPart();
public:
    CsvLog(const std::string &path,const std::string &header,unsigned rows=0,unsigned keep=3,unsigned precision=12);
    std::ofstream &row();
    void finish();
};
class TrajectoryWriter {
    CsvLog log_;
public:
    explicit TrajectoryWriter(const std::string&,unsigned rows=0,unsigned keep=3);
    void append(const Status&);
    void finish(){log_.finish();}
};
} // namespace zslam
