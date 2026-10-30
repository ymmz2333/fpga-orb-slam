#include "zslam/slam.hpp"
#include "zslam/formats.hpp"
#include <cstring>
#include "zslam/filesystem.hpp"
#include <fstream>
#include <stdexcept>
#include <unordered_map>

namespace zslam {
namespace {
uint32_t crc(const uint8_t *p,std::size_t n){uint32_t c=~0u;for(std::size_t i=0;i<n;i++){c^=p[i];for(int b=0;b<8;b++)c=(c>>1)^((0u-(c&1u))&0xedb88320u);}return ~c;}
struct Buffer {
    std::vector<uint8_t> data;std::size_t pos=0;
    void put(uint64_t value,unsigned n){for(unsigned i=0;i<n;i++)data.push_back(static_cast<uint8_t>(value>>(8*i)));}
    uint64_t get(unsigned n){if(pos+n>data.size())throw std::runtime_error("Truncated map");uint64_t v=0;for(unsigned i=0;i<n;i++)v|=uint64_t(data[pos++])<<(8*i);return v;}
    void real(double v){if(!std::isfinite(v))throw std::runtime_error("Non-finite map value");uint64_t bits;std::memcpy(&bits,&v,8);put(bits,8);}
    double real(){uint64_t bits=get(8);double v;std::memcpy(&v,&bits,8);if(!std::isfinite(v))throw std::runtime_error("Non-finite map value");return v;}
    void vector(V3 p){real(p.x);real(p.y);real(p.z);}
    V3 vector(){double x=real(),y=real(),z=real();return {x,y,z};}
    void pose(Pose p){for(double v:p.r.a)real(v);vector(p.t);}
    Pose pose(){Pose p;for(double &v:p.r.a)v=real();p.t=vector();if(!rigid(p))throw std::runtime_error("Corrupt map pose");return p;}
    void descriptor(const Descriptor &d){data.insert(data.end(),d.begin(),d.end());}
    Descriptor descriptor(){Descriptor d;for(auto &v:d)v=static_cast<uint8_t>(get(1));return d;}
};
}
void Slam::save(const std::string &path)const{
    if(fs::exists(path)||fs::exists(path+".part"))throw std::runtime_error("Map output already exists; choose a new filename");
    Buffer b;const std::string magic="ZSLMAP01";b.data.insert(b.data.end(),magic.begin(),magic.end());b.put(2,4);
    b.put(static_cast<unsigned>(camera_.width),4);b.put(static_cast<unsigned>(camera_.height),4);
    for(double v:{camera_.fx,camera_.fy,camera_.cx,camera_.cy})b.real(v);for(double v:camera_.d)b.real(v);
    unsigned count=0;for(const auto &p:map_)if(p.active)count++;b.put(count,4);b.put(keys_.size(),4);
    for(const auto &p:map_)if(p.active){b.put(p.id,8);b.vector(p.xyz);b.descriptor(p.descriptor);b.put(p.seen,4);b.put(p.fixed?1:0,1);}
    for(const auto &key:keys_){b.put(key.id,8);b.put(key.frame,8);b.put(key.anchor?1:0,1);b.pose(key.tcw);b.put(key.features.size(),4);
        for(unsigned i=0;i<key.features.size();i++){const auto &f=key.features[i];b.real(f.raw.x);b.real(f.raw.y);b.real(f.uv.x);b.real(f.uv.y);b.put(f.level,4);b.put(f.score,4);b.descriptor(f.descriptor);
            b.put(alive(key.refs[i])?map_[key.refs[i].slot].id:~uint64_t(0),8);}}
    b.put(crc(b.data.data(),b.data.size()),4);
    auto parent=fs::path(path).parent_path();if(!parent.empty())fs::create_directories(parent);
    std::ofstream file(path+".part",std::ios::binary);if(!file)throw std::runtime_error("Cannot create map output");file.write(reinterpret_cast<const char*>(b.data.data()),static_cast<std::streamsize>(b.data.size()));file.close();
    if(!file)throw std::runtime_error("Map write failed");fs::rename(path+".part",path);
}
void Slam::load(const std::string &path){
    std::ifstream file(path,std::ios::binary|std::ios::ate);if(!file)throw std::runtime_error("Cannot open map");auto size=file.tellg();
    if(size<104||size>32*1024*1024)throw std::runtime_error("Map exceeds bounded format size");Buffer b;b.data.resize(static_cast<std::size_t>(size));file.seekg(0);file.read(reinterpret_cast<char*>(b.data.data()),size);if(!file)throw std::runtime_error("Map read failed");
    b.pos=b.data.size()-4;uint32_t expected=static_cast<uint32_t>(b.get(4));if(crc(b.data.data(),b.data.size()-4)!=expected)throw std::runtime_error("Map CRC mismatch");b.data.resize(b.data.size()-4);b.pos=0;
    for(char c:std::string("ZSLMAP01"))if(b.get(1)!=static_cast<uint8_t>(c))throw std::runtime_error("Unknown map format");unsigned version=static_cast<unsigned>(b.get(4));if(version!=1&&version!=2)throw std::runtime_error("Unknown map version");
    Camera camera;camera.width=static_cast<int>(b.get(4));camera.height=static_cast<int>(b.get(4));camera.fx=b.real();camera.fy=b.real();camera.cx=b.real();camera.cy=b.real();for(double &v:camera.d)v=b.real();
    if(camera.width!=camera_.width||camera.height!=camera_.height||std::abs(camera.fx-camera_.fx)>1e-6||std::abs(camera.fy-camera_.fy)>1e-6||std::abs(camera.cx-camera_.cx)>1e-6||std::abs(camera.cy-camera_.cy)>1e-6)throw std::runtime_error("Map camera calibration mismatch");
    for(int i=0;i<5;i++)if(std::abs(camera.d[i]-camera_.d[i])>1e-8)throw std::runtime_error("Map distortion mismatch");
    unsigned points=static_cast<unsigned>(b.get(4)),keys=static_cast<unsigned>(b.get(4));if(points>config_.max_points||keys>config_.max_keyframes)throw std::runtime_error("Map exceeds configured capacity");
    Slam restored(camera_,config_);std::unordered_map<uint64_t,Ref> lookup;
    for(unsigned i=0;i<points;i++){uint64_t id=b.get(8);V3 xyz=b.vector();Descriptor d=b.descriptor();unsigned seen=static_cast<unsigned>(b.get(4)),fixed=version>=2?static_cast<unsigned>(b.get(1)):0;if(fixed>1)throw std::runtime_error("Invalid map anchor flag");Ref r=restored.addPoint(xyz,d,0);
        if(id==~uint64_t(0)||!lookup.emplace(id,r).second)throw std::runtime_error("Duplicate map point ID");auto &p=restored.map_[r.slot];p.id=id;p.seen=seen;p.fixed=fixed!=0;restored.next_point_=std::max(restored.next_point_,id+1);}
    for(unsigned i=0;i<keys;i++){uint64_t key_id=b.get(8),frame_id=b.get(8);bool anchor=b.get(1)!=0;Pose pose=b.pose();unsigned count=static_cast<unsigned>(b.get(4));if(count>max_features)throw std::runtime_error("Map keyframe too large");
        Frame frame;frame.id=frame_id;frame.features.resize(count);std::vector<Ref> refs(count);
        for(unsigned j=0;j<count;j++){auto &f=frame.features[j];f.raw={b.real(),b.real()};f.uv={b.real(),b.real()};f.level=static_cast<uint32_t>(b.get(4));f.score=static_cast<uint32_t>(b.get(4));f.descriptor=b.descriptor();uint64_t pid=b.get(8);
            if(f.level>=8)throw std::runtime_error("Map feature octave invalid");if(pid!=~uint64_t(0)){auto it=lookup.find(pid);if(it==lookup.end())throw std::runtime_error("Map references missing point");refs[j]=it->second;}}
        if(!key_id)throw std::runtime_error("Invalid map keyframe ID");restored.addKeyframe(frame,pose,std::move(refs),anchor);
    }
    if(b.pos!=b.data.size())throw std::runtime_error("Extra map payload");if(!restored.keys_.empty())restored.current_=restored.keys_.back().tcw;*this=std::move(restored);
}
void Slam::importHandoff(const std::string &folder){
    Slam restored(camera_,config_);Csv points(folder+"/points.csv");Row row;std::ifstream descriptors(folder+"/representative_descriptors.bin",std::ios::binary);if(!descriptors)throw std::runtime_error("Missing handoff descriptors");
    std::unordered_map<uint64_t,Ref> point_ids;unsigned count=0;
    while(points.next(row)){if(count++>=config_.max_points)throw std::runtime_error("Imported map exceeds point bound");Descriptor d;descriptors.read(reinterpret_cast<char*>(d.data()),32);if(descriptors.gcount()!=32)throw std::runtime_error("Truncated map descriptors");
        V3 xyz{number(row,"x"),number(row,"y"),number(row,"z")};uint64_t id=integer(row,"point_id");Ref r=restored.addPoint(xyz,d,0);if(id==~uint64_t(0)||!point_ids.emplace(id,r).second)throw std::runtime_error("Duplicate imported point");
        restored.map_[r.slot].id=id;restored.map_[r.slot].seen=static_cast<unsigned>(integer(row,"observations"));restored.map_[r.slot].fixed=true;restored.next_point_=std::max(restored.next_point_,id+1);}
    char extra;if(descriptors.get(extra))throw std::runtime_error("Extra map descriptor bytes");Csv keycsv(folder+"/keyframes.csv");std::vector<Row> all;while(keycsv.next(row))all.push_back(row);if(all.empty()||all.size()>10000)throw std::runtime_error("Invalid imported keyframe count");
    std::unordered_map<uint64_t,unsigned> key_ids;unsigned chosen=std::min(static_cast<unsigned>(all.size()),config_.max_keyframes);
    for(unsigned i=0;i<chosen;i++){unsigned index=chosen==1?0:static_cast<unsigned>((uint64_t(i)*(all.size()-1))/(chosen-1));const auto &r=all[index];
        if(std::abs(number(r,"fx")-camera_.fx)>1e-5||std::abs(number(r,"fy")-camera_.fy)>1e-5)throw std::runtime_error("Handoff calibration differs; use its camera CSV");
        Keyframe k;k.id=restored.next_key_++;k.frame=integer(r,"slam_frame_id");k.tcw=readTwc(r);k.anchor=i<2;
        key_ids.emplace(integer(r,"keyframe_id"),static_cast<unsigned>(restored.keys_.size()));restored.keys_.push_back(std::move(k));}
    Csv observations(folder+"/observations.csv");std::ifstream obsdesc(folder+"/observation_descriptors.bin",std::ios::binary);if(!obsdesc)throw std::runtime_error("Missing observation descriptors");uint64_t obs_index=0;
    while(observations.next(row)){Descriptor d;obsdesc.read(reinterpret_cast<char*>(d.data()),32);if(obsdesc.gcount()!=32||integer(row,"descriptor_row")!=obs_index++)throw std::runtime_error("Imported observation order mismatch");
        auto it=key_ids.find(integer(row,"keyframe_id"));if(it==key_ids.end())continue;auto point=point_ids.find(integer(row,"point_id"));if(point==point_ids.end())throw std::runtime_error("Unknown observed point");
        auto &key=restored.keys_[it->second];if(key.features.size()>=max_features)throw std::runtime_error("Imported keyframe exceeds feature bound");Feature f;f.raw={number(row,"raw_u"),number(row,"raw_v")};f.uv={number(row,"u"),number(row,"v")};f.level=static_cast<unsigned>(integer(row,"octave"));f.descriptor=d;
        if(f.level>=8)throw std::runtime_error("Imported octave invalid");key.features.push_back(f);key.refs.push_back(point->second);restored.observe(point->second,key,static_cast<unsigned>(key.features.size()-1));}
    if(obsdesc.get(extra))throw std::runtime_error("Extra observation descriptors");restored.current_=restored.keys_.back().tcw;*this=std::move(restored);
}
} // namespace zslam
