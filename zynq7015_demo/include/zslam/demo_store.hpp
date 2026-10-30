#pragma once
#include "bridge_wire.hpp"
#include "formats.hpp"
#include "filesystem.hpp"
#include "dense_environment.hpp"
#include <atomic>
#include <map>
#include <set>
#include <cstdio>
#if defined(__linux__)
#include <fcntl.h>
#endif

namespace demo {
inline void syncFile(const std::string&path){
#if defined(__linux__)
    int fd=::open(path.c_str(),O_RDONLY);if(fd<0)throw std::runtime_error("Cannot sync file/directory");int rc=::fsync(fd);::close(fd);if(rc)throw std::runtime_error("fsync failed");
#else
    (void)path; // Native Windows tests do not claim SD power-loss durability.
#endif
}
inline void writeFile(const std::string&path,const std::vector<uint8_t>&data){std::ofstream f(path,std::ios::binary|std::ios::trunc);
    if(!f)throw std::runtime_error("Cannot write map file");f.write(reinterpret_cast<const char*>(data.data()),static_cast<std::streamsize>(data.size()));f.close();if(!f)throw std::runtime_error("Map file write failed");syncFile(path);}
inline bool hexDigest(const std::string&s){return s.size()==64&&s.find_first_not_of("0123456789abcdef")==std::string::npos;}
struct MapEntry {uint64_t size=0;std::string digest;};
struct Manifest {
    std::map<std::string,MapEntry> files;std::string version,calibration;uint64_t map_id=0;unsigned points=0,keys=0;
    static Manifest parse(const std::vector<uint8_t>&raw,const std::string&calibration){
        if(raw.size()>4096)throw std::runtime_error("Manifest too large");std::istringstream lines(string(raw));std::string line,magic,hash,abi,extra;Manifest m;
        if(!std::getline(lines,line))throw std::runtime_error("Empty manifest");std::istringstream head(line);
        if(!(head>>magic>>hash>>abi>>m.map_id>>m.points>>m.keys)||(head>>extra)||(magic!="ORB60_MAP_V1"&&magic!="ORB60_MAP_V2")||hash!=calibration||abi!=profile||!m.points||m.points>zslam::handoff_max_points||!m.keys||m.keys>zslam::handoff_max_keyframes)throw std::runtime_error("Map capacity/calibration/profile mismatch");
        std::set<std::string>names={"camera_orb.csv","points.csv","representative_descriptors.bin","keyframes.csv","observations.csv","observation_descriptors.bin","map.json"};if(magic=="ORB60_MAP_V2")names.insert("dense_environment.bin");uint64_t total=0;
        while(std::getline(lines,line)){std::istringstream row(line);std::string name,digest;uint64_t size;
            if(!(row>>digest>>size>>name)||(row>>extra)||!names.count(name)||!hexDigest(digest)||size>max_body||!m.files.emplace(name,MapEntry{size,digest}).second)throw std::runtime_error("Invalid manifest entry");total+=size;}
        if(m.files.size()!=names.size()||total>64*1024*1024)throw std::runtime_error("Incomplete/oversized map");m.version=sha256(raw);m.calibration=hash;return m;
    }
};
class MapStore {
    std::string root_,camera_path_,calibration_,staging_;std::vector<uint8_t>camera_bytes_,manifest_bytes_;Manifest manifest_;std::set<std::string>written_;
public:
    explicit MapStore(std::string root,std::string camera):root_(std::move(root)),camera_path_(std::move(camera)){
        zslam::fs::create_directories(root_+"/versions");camera_bytes_=readFile(camera_path_,4096);calibration_=sha256(camera_bytes_);}
    const std::string&calibration()const{return calibration_;}
    const Manifest&manifest()const{return manifest_;}
    std::string versionPath(const std::string&version)const{if(!hexDigest(version))throw std::runtime_error("Invalid map version");return root_+"/versions/"+version;}
    void begin(const std::vector<uint8_t>&raw){manifest_=Manifest::parse(raw,calibration_);manifest_bytes_=raw;written_.clear();
        static std::atomic<unsigned> sequence{0};staging_=root_+"/.staging-"+manifest_.version+"-"+std::to_string(++sequence);
        if(zslam::fs::exists(staging_))throw std::runtime_error("Staging directory exists; preserve for diagnosis");zslam::fs::create_directory(staging_);writeFile(staging_+"/manifest.txt",raw);}
    void file(const std::vector<uint8_t>&body){if(staging_.empty())throw std::runtime_error("Map begin required");auto sep=std::find(body.begin(),body.end(),uint8_t('\n'));
        if(sep==body.end()||sep-body.begin()>80)throw std::runtime_error("Invalid map filename");std::string name(body.begin(),sep);auto it=manifest_.files.find(name);
        if(it==manifest_.files.end()||written_.count(name))throw std::runtime_error("Unexpected/duplicate map file");std::vector<uint8_t>data(sep+1,body.end());
        if(data.size()!=it->second.size||sha256(data)!=it->second.digest)throw std::runtime_error("Map file SHA256/size mismatch");writeFile(staging_+"/"+name,data);written_.insert(name);}
    std::string prepare(){if(staging_.empty()||written_.size()!=manifest_.files.size())throw std::runtime_error("Incomplete map transfer");
        if(readFile(staging_+"/camera_orb.csv")!=camera_bytes_)throw std::runtime_error("Map calibration bytes mismatch");
        auto camera=zslam::readCamera(camera_path_);unsigned key_count=0,point_count=0;
        {zslam::Csv keys(staging_+"/keyframes.csv");zslam::Row r;
        while(keys.next(r)){key_count++;for(auto name:{"fx","fy","cx","cy","d0","d1","d2","d3","d4"}){
            double expected=name[0]=='d'?camera.d[name[1]-'0']:(std::string(name)=="fx"?camera.fx:std::string(name)=="fy"?camera.fy:std::string(name)=="cx"?camera.cx:camera.cy);
            if(std::abs(zslam::number(r,name)-expected)>1e-8)throw std::runtime_error("Keyframe calibration mismatch");}}
        zslam::Csv points(staging_+"/points.csv");while(points.next(r)){point_count++;if(zslam::integer(r,"observations")<3)throw std::runtime_error("Unreliable map point");}}
        if(key_count!=manifest_.keys||point_count!=manifest_.points)throw std::runtime_error("Map manifest counts differ");
        if(manifest_.files.count("dense_environment.bin"))zslam::readDenseEnvironment(staging_+"/dense_environment.bin",manifest_.files.at("points.csv").digest,calibration_);
        zslam::Config config;config.mapping=false;config.max_points=zslam::handoff_max_points;config.max_keyframes=zslam::handoff_max_keyframes;zslam::Slam imported(camera,config);imported.importHandoff(staging_);
        imported.save(staging_+"/map.zmap");syncFile(staging_+"/map.zmap");zslam::Slam reloaded(camera,config);reloaded.load(staging_+"/map.zmap");reloaded.save(staging_+"/roundtrip.zmap");
        if(readFile(staging_+"/map.zmap")!=readFile(staging_+"/roundtrip.zmap"))throw std::runtime_error("Native map roundtrip differs");
        auto digest=sha256(readFile(staging_+"/map.zmap"));writeFile(staging_+"/native.sha256",bytes(digest+"\n"));syncFile(staging_);
        auto target=versionPath(manifest_.version);
        if(zslam::fs::exists(target)){if(readFile(target+"/manifest.txt")!=manifest_bytes_||sha256(readFile(target+"/map.zmap"))!=digest)throw std::runtime_error("Existing map version differs");}
        else {zslam::fs::rename(staging_,target);syncFile(root_+"/versions");}
        staging_.clear();return manifest_.version;
    }
    std::string current()const{if(!zslam::fs::exists(root_+"/current"))return {};auto raw=readFile(root_+"/current",256);std::istringstream in(string(raw));std::string version,digest,extra;
        if(!(in>>version>>digest)||(in>>extra)||!hexDigest(version)||!hexDigest(digest))throw std::runtime_error("Invalid published map pointer");
        if(sha256(readFile(versionPath(version)+"/map.zmap"))!=digest)throw std::runtime_error("Published native map checksum mismatch");
        if(Manifest::parse(readFile(versionPath(version)+"/manifest.txt",4096),calibration_).version!=version)throw std::runtime_error("Published map manifest SHA256 mismatch");return version;}
    void publish(const std::string&version){auto path=versionPath(version);if(Manifest::parse(readFile(path+"/manifest.txt",4096),calibration_).version!=version)throw std::runtime_error("Map version/manifest SHA256 mismatch");
        auto digest=sha256(readFile(path+"/map.zmap"));if(string(readFile(path+"/native.sha256",100))!=digest+"\n")throw std::runtime_error("Native map checksum changed");
        writeFile(root_+"/current.part",bytes(version+"\n"+digest+"\n"));
#if defined(_WIN32)
        if(!MoveFileExA((root_+"/current.part").c_str(),(root_+"/current").c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))throw std::runtime_error("Atomic map pointer publish failed");
#else
        if(std::rename((root_+"/current.part").c_str(),(root_+"/current").c_str()))throw std::runtime_error("Atomic map pointer publish failed");
#endif
        syncFile(root_);}
};
} // namespace demo
