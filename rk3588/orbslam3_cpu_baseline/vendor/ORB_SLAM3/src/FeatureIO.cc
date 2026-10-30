#include "FeatureIO.h"
#include "ORBextractor.h"
#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <sys/stat.h>
#include <cerrno>

namespace ORB_SLAM3 {
namespace {
using Clock=std::chrono::steady_clock;
double ms(Clock::time_point start) { return std::chrono::duration<double,std::milli>(Clock::now()-start).count(); }
std::string mode="inactive", root;
thread_local FeatureIOStats stats;
thread_local ORBextractor* extractors[2]={nullptr,nullptr};
void require(bool condition,const std::string& message) { if(!condition) throw std::runtime_error("FeatureIO: "+message); }
void mkdirs(const std::string& path) {
    for(size_t i=1;i<=path.size();++i) if(i==path.size() || path[i]=='/') {
        std::string part=path.substr(0,i);
        require(::mkdir(part.c_str(),0755)==0 || errno==EEXIST,"mkdir "+part);
    }
}
void u16(std::vector<uint8_t>& v,size_t offset,uint16_t value) { for(int i=0;i<2;++i) v.at(offset+i)=uint8_t(value>>(i*8)); }
void u32(std::vector<uint8_t>& v,size_t offset,uint32_t value) { for(int i=0;i<4;++i) v.at(offset+i)=uint8_t(value>>(i*8)); }
void u64(std::vector<uint8_t>& v,size_t offset,uint64_t value) { for(int i=0;i<8;++i) v.at(offset+i)=uint8_t(value>>(i*8)); }
uint64_t get(const std::vector<uint8_t>& v,size_t offset,int bytes) { uint64_t x=0; for(int i=0;i<bytes;++i) x|=uint64_t(v.at(offset+i))<<(8*i); return x; }
uint32_t bits(float x) { uint32_t v; std::memcpy(&v,&x,4); return v; }
float real(const std::vector<uint8_t>& v,size_t offset) { uint32_t b=uint32_t(get(v,offset,4)); float x; std::memcpy(&x,&b,4); return x; }
int32_t integer(const std::vector<uint8_t>& v,size_t offset) { uint32_t b=uint32_t(get(v,offset,4)); int32_t x; std::memcpy(&x,&b,4); return x; }
std::string name(int role) { return role==0 ? "normal" : "initialization"; }
std::string file(int role) { return root+"/"+name(role)+"/"+std::to_string(stats.timestamp_ns)+".orb"; }
void write(const std::string& path,const void* data,size_t size) {
    std::ifstream existing(path,std::ios::binary); require(!existing.good(),"refusing overwrite "+path);
    std::ofstream out(path,std::ios::binary); require(bool(out),"cannot open "+path);
    out.write(static_cast<const char*>(data),std::streamsize(size)); out.close(); require(bool(out),"write failed "+path);
}
struct MemoryRecord {
    float x,y; int32_t octave; float angle,size,response; int32_t class_id; uint32_t reserved; uint8_t descriptor[32];
};
static_assert(sizeof(float)==4 && std::numeric_limits<float>::is_iec559,"float32 required");
static_assert(sizeof(MemoryRecord)==64,"memory snapshot layout mismatch");
}
void FeatureIO::Configure(const std::string& selected,const std::string& directory) {
    require(selected=="native" || selected=="dump" || selected=="inject","invalid mode");
    require(selected=="native" || !directory.empty(),"feature directory required");
    mode=selected; root=directory;
    if(mode=="dump") for(int role=0;role<2;++role) { mkdirs(root+"/"+name(role)); mkdirs(root+"/memory/"+name(role)); }
}
bool FeatureIO::Active() { return mode!="inactive"; }
void FeatureIO::Begin(uint64_t timestamp_ns) { stats=FeatureIOStats(); stats.timestamp_ns=timestamp_ns; }
void FeatureIO::SetExtractors(ORBextractor* normal,ORBextractor* initialization) { extractors[0]=normal; extractors[1]=initialization; }
FeatureIOStats FeatureIO::Stats() { return stats; }
void FeatureIO::SavePacket(const std::string& path,const std::string& memory_path,uint64_t timestamp_ns,int role,
                           int width,int height,ORBextractor* extractor,int mono_left,
                           const std::vector<cv::KeyPoint>& keys,const cv::Mat& descriptors) {
    require(keys.empty() || (descriptors.type()==CV_8UC1 && descriptors.cols==32 && descriptors.rows==int(keys.size())),"descriptor shape mismatch");
    std::vector<uint8_t> bytes(64+64*keys.size(),0);
    std::memcpy(bytes.data(),"ORBFEAT\0",8);
    u16(bytes,8,1); u16(bytes,10,64); u16(bytes,12,64); bytes[14]=uint8_t(role);
    u64(bytes,16,timestamp_ns); u32(bytes,24,width); u32(bytes,28,height); u32(bytes,32,keys.size());
    u32(bytes,36,extractor->GetLevels()); u32(bytes,40,bits(extractor->GetScaleFactor()));
    u32(bytes,44,extractor->GetFeatures()); u32(bytes,48,32); u32(bytes,56,mono_left);
    std::vector<MemoryRecord> memory(keys.size());
    for(size_t i=0;i<keys.size();++i) {
        const auto& k=keys[i]; size_t offset=64+i*64;
        u32(bytes,offset,bits(k.pt.x)); u32(bytes,offset+4,bits(k.pt.y)); u32(bytes,offset+8,k.octave);
        u32(bytes,offset+12,bits(k.angle)); u32(bytes,offset+16,bits(k.size)); u32(bytes,offset+20,bits(k.response)); u32(bytes,offset+24,k.class_id);
        std::memcpy(bytes.data()+offset+32,descriptors.ptr(i),32);
        // Independent memory snapshot path: direct field assignments, not encoded-buffer reuse.
        auto& r=memory[i]; r.x=k.pt.x; r.y=k.pt.y; r.octave=k.octave; r.angle=k.angle; r.size=k.size;
        r.response=k.response; r.class_id=k.class_id; r.reserved=0; std::memcpy(r.descriptor,descriptors.ptr(i),32);
    }
    write(path,bytes.data(),bytes.size());
    if(!memory_path.empty()) {
        const uint16_t one=1; require(*reinterpret_cast<const uint8_t*>(&one)==1,"memory verification requires little-endian host");
        write(memory_path,memory.data(),memory.size()*64);
    }
}
int FeatureIO::LoadPacket(const std::string& path,uint64_t timestamp_ns,int role,int width,int height,
                          ORBextractor* extractor,std::vector<cv::KeyPoint>& keys,cv::Mat& descriptors,double& read_ms,double& decode_ms) {
    auto start=Clock::now();
    std::ifstream in(path,std::ios::binary|std::ios::ate); require(bool(in),"missing "+path);
    auto length=in.tellg(); require(length>=64 && length<=64+64*100000,"invalid file size");
    std::vector<uint8_t> bytes(static_cast<size_t>(length)); in.seekg(0); in.read(reinterpret_cast<char*>(bytes.data()),static_cast<std::streamsize>(length));
    require(bool(in),"short read"); read_ms=ms(start); start=Clock::now();
    require(std::memcmp(bytes.data(),"ORBFEAT\0",8)==0 && get(bytes,8,2)==1,"magic/version mismatch");
    require(get(bytes,10,2)==64 && get(bytes,12,2)==64 && bytes[14]==role && bytes[15]==0,"layout/role mismatch");
    require(get(bytes,16,8)==timestamp_ns && get(bytes,24,4)==uint32_t(width) && get(bytes,28,4)==uint32_t(height),"timestamp/image mismatch");
    require(get(bytes,36,4)==uint32_t(extractor->GetLevels()) && get(bytes,40,4)==bits(extractor->GetScaleFactor()) &&
            get(bytes,44,4)==uint32_t(extractor->GetFeatures()),"extractor configuration mismatch");
    require(get(bytes,48,4)==32 && get(bytes,52,4)==0 && get(bytes,60,4)==0,"descriptor/coordinate/reserved mismatch");
    size_t count=get(bytes,32,4); int mono_left=integer(bytes,56);
    require(bytes.size()==64+64*count && mono_left>=0 && mono_left<=int(count),"count/monoLeft mismatch");
    keys.resize(count); if(count) descriptors.create(int(count),32,CV_8UC1); else descriptors.release();
    for(size_t i=0;i<count;++i) {
        size_t o=64+i*64; auto& k=keys[i];
        k.pt.x=real(bytes,o); k.pt.y=real(bytes,o+4); k.octave=integer(bytes,o+8); k.angle=real(bytes,o+12);
        k.size=real(bytes,o+16); k.response=real(bytes,o+20); k.class_id=integer(bytes,o+24);
        require(std::isfinite(k.pt.x) && std::isfinite(k.pt.y) && k.pt.x>=0 && k.pt.x<width && k.pt.y>=0 && k.pt.y<height,"invalid coordinate");
        require(k.octave>=0 && k.octave<extractor->GetLevels() && std::isfinite(k.angle) && k.angle>=0 && k.angle<360 &&
                std::isfinite(k.size) && k.size>0 && std::isfinite(k.response) && get(bytes,o+28,4)==0,"invalid keypoint");
        std::memcpy(descriptors.ptr(i),bytes.data()+o+32,32);
    }
    decode_ms=ms(start); return mono_left;
}
int FeatureIO::Process(ORBextractor* extractor,const cv::Mat& image,std::vector<cv::KeyPoint>& keys,
                       cv::Mat& descriptors,std::vector<int>& lapping) {
    require(stats.timestamp_ns>0 && extractors[0] && extractors[1],"missing monocular frame context");
    int role=extractor==extractors[1] ? 1 : 0; require(extractor==extractors[role],"unknown extractor");
    stats.role=role; int mono_left;
    if(mode=="inject") mono_left=LoadPacket(file(role),stats.timestamp_ns,role,image.cols,image.rows,extractor,keys,descriptors,stats.read_ms,stats.decode_ms);
    else {
        auto start=Clock::now(); mono_left=(*extractor)(image,cv::Mat(),keys,descriptors,lapping); stats.native_ms=ms(start); ++stats.extractor_calls;
        if(mode=="dump") {
            start=Clock::now(); SavePacket(file(role),root+"/memory/"+name(role)+"/"+std::to_string(stats.timestamp_ns)+".bin",
                stats.timestamp_ns,role,image.cols,image.rows,extractor,mono_left,keys,descriptors); stats.dump_ms+=ms(start);
            int other=1-role; std::vector<cv::KeyPoint> extra; cv::Mat desc;
            start=Clock::now(); int extra_mono=(*extractors[other])(image,cv::Mat(),extra,desc,lapping); stats.auxiliary_ms=ms(start); ++stats.extractor_calls;
            start=Clock::now(); SavePacket(file(other),root+"/memory/"+name(other)+"/"+std::to_string(stats.timestamp_ns)+".bin",
                stats.timestamp_ns,other,image.cols,image.rows,extractors[other],extra_mono,extra,desc); stats.dump_ms+=ms(start);
        }
    }
    stats.count=keys.size(); return mono_left;
}
}
