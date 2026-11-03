// GPL-3.0-or-later. KV260 PS mapping with actual external 7015 ORB, no CPU ORB.
#include "System.h"
#include "FeatureIO.h"
#include "Kv260VideoPipeline.h"
#include "Kv260NetworkRecord.h"
#include "Kv260DepthKeyframes.h"
#include "DenseFrameTelemetry.h"
#include "bridge_wire.hpp"
#include <opencv2/imgcodecs.hpp>
#include <openssl/sha.h>
#include <sys/stat.h>
#include <csignal>
#include <time.h>
#include <sched.h>
#include <cmath>
#include <iomanip>
#include <iostream>
#ifdef ORB60_ENABLE_MAPPER_PUBLISHED
#include "KvMapperProgress.h"
#endif
namespace {
volatile std::sig_atomic_t stopping=0;void stop(int){stopping=1;}
void require(bool ok,const std::string& why){if(!ok)throw std::runtime_error(why);}
uint64_t monotonic_ns(){timespec t{};require(!clock_gettime(CLOCK_MONOTONIC,&t),"Monotonic clock failed");return uint64_t(t.tv_sec)*1000000000ULL+t.tv_nsec;}
uint64_t thread_cpu_ns(){timespec t{};require(!clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t),"Thread CPU clock failed");return uint64_t(t.tv_sec)*1000000000ULL+t.tv_nsec;}
void atomic_json(const std::string& path,const std::string& value){std::ofstream f(path+".part");f<<value<<'\n';f.close();require(bool(f)&&!std::rename((path+".part").c_str(),path.c_str()),"Progress commit failed");}
std::string sha(const uint8_t* p,size_t size){unsigned char hash[SHA256_DIGEST_LENGTH];SHA256(p,size,hash);std::ostringstream s;s<<std::hex<<std::setfill('0');for(auto v:hash)s<<std::setw(2)<<unsigned(v);return s.str();}
void publish_rgb(const KvNetwork::VideoFrame& frame,const std::string& folder) {
    const auto stem=folder+"/f"+std::to_string(frame.id.index);std::vector<uint8_t> png;
    require(cv::imencode(".png",frame.bgr,png,{cv::IMWRITE_PNG_COMPRESSION,1}),"RGB PNG encoding failed");
    {std::ofstream f(stem+".png.part",std::ios::binary);f.write(reinterpret_cast<const char*>(png.data()),png.size());f.close();require(bool(f),"RGB write failed");}
    require(!std::rename((stem+".png.part").c_str(),(stem+".png").c_str()),"RGB commit failed");
    std::ofstream meta(stem+".json.part");meta<<"{\"source_frame_id\":"<<frame.id.index<<",\"timestamp_ns\":"<<frame.id.stamp
      <<",\"gray_crc\":"<<frame.id.crc<<",\"gray_sha256\":\""<<sha(frame.gray.data,frame.gray.total())
      <<"\",\"rgb\":\"f"<<frame.id.index<<".png\",\"rgb_sha256\":\""<<sha(png.data(),png.size())<<"\"}\n";
    meta.close();require(bool(meta)&&!std::rename((stem+".json.part").c_str(),(stem+".json").c_str()),"RGB metadata commit failed");
}
}
int main(int argc,char** argv){using namespace ORB_SLAM3;try {
    cv::setNumThreads(1);
    if(argc==4&&std::string(argv[1])=="--verify-video") {
        auto ids=KvNetwork::identities(argv[3]);KvNetwork::VideoSource video(argv[2]);
        for(auto id:ids)KvNetwork::decode(video,id);
        cv::Mat extra;require(!video.read(extra),"Extra unindexed source frames");
        std::cout<<"NATIVE_VIDEO_IDENTITY_PASS frames="<<ids.size()<<std::endl;return 0;
    }
    require(argc==9,"Usage: mono_kv260_network VOCAB YAML VIDEO IDENTITIES ENDPOINT NEW_RUN MAX_FRAMES TELEMETRY(0|1)");
    const std::string out=argv[6];const size_t limit=std::stoull(argv[7]);const bool display=std::stoi(argv[8])!=0;
    const bool color_preview=std::getenv("ORB60_NATIVE_COLOR_PREVIEW")&&std::string(std::getenv("ORB60_NATIVE_COLOR_PREVIEW"))=="1";
    const bool mapper_barrier=std::getenv("ORB60_MAPPER_BARRIER")&&std::string(std::getenv("ORB60_MAPPER_BARRIER"))=="1";
#if !defined(ORB60_ENABLE_MAPPER_BARRIER) && !defined(ORB60_ENABLE_MAPPER_PUBLISHED)
    require(!mapper_barrier,"This executable does not implement the requested mapper scheduling mode");
#endif
    int tracking_core=-1;if(const char* value=std::getenv("ORB60_TRACKING_CORE")){size_t used=0;std::string s(value);tracking_core=std::stoi(s,&used);require(used==s.size()&&tracking_core>=-1&&tracking_core<CPU_SETSIZE,"Invalid tracking CPU core");}
    auto ids=KvNetwork::identities(argv[4],limit);require(!mkdir(out.c_str(),0755),"Fresh run directory required");
    for(auto name:{"tracking","dense","dense/rgb_cache","dense/color_poses"})require(!mkdir((out+"/"+name).c_str(),0755),"Cannot create owned run folders");
    const std::string poses=out+"/dense/color_poses";setenv("ORB60_BRIDGE_COLOR_POSES",poses.c_str(),1);
    setenv("ORB60_KV260_KEYFRAME_DEPTH","1",1);
    FeatureIO::Configure("fpga-pipeline",argv[5]);System slam(argv[1],argv[2],System::MONOCULAR,false);
    require(slam.GetImageScale()==1.f,"Unchanged 960x720 working image required");
    std::unique_ptr<DenseFrameTelemetry> telemetry;if(display)telemetry.reset(new DenseFrameTelemetry(out+"/tracking/telemetry",false));
    std::ofstream journal(out+"/tracking/frames.csv"),source(out+"/source_frames.csv");
    journal<<"source_frame_id,timestamp_ns,slam_timestamp_ns,session,gray_crc,record_crc,count,tracking_state,pose_valid,track_ms,cpu_orb_calls,decode_ms,feature_wait_ms,engine_ns,track_cpu_ms,map_sync_ms\n"<<std::setprecision(17);
    source<<"timestamp_ns,source_frame_index\n";
    std::signal(SIGTERM,stop);std::signal(SIGINT,stop);
    const auto start=std::chrono::steady_clock::now();const uint64_t started_ns=monotonic_ns();size_t valid=0,selected=0;
    atomic_json(out+"/processing_started.json","{\"started_monotonic_ns\":"+std::to_string(started_ns)+"}");
    {
        KvNetwork::VideoPipeline input(argv[3],ids,limit==0);
        if(tracking_core>=0){cpu_set_t mask;CPU_ZERO(&mask);CPU_SET(tracking_core,&mask);require(!sched_setaffinity(0,sizeof(mask),&mask),"Cannot pin tracking thread");}
        for(size_t i=0;i<ids.size();++i) {
            require(!stopping,"Explicitly stopped: partial run is not accepted");auto f=input.get(i);
            source<<f.id.stamp<<','<<i<<'\n';source.flush();require(bool(source),"Source identity journal failed");
            FeatureIO::Begin(f.id.stamp);KvDepth::begin(i,f.id.stamp,f.id.crc);
            const uint64_t cpu_began=thread_cpu_ns();
            const auto began=std::chrono::steady_clock::now();auto pose=slam.TrackMonocular(f.gray,double(f.id.stamp)*1e-9);
            const double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-began).count();
            const double cpu_ms=double(thread_cpu_ns()-cpu_began)*1e-6;
            double map_sync_ms=0;
#ifdef ORB60_ENABLE_MAPPER_BARRIER
            if(mapper_barrier)map_sync_ms=slam.WaitForLocalMapping(10000);
#endif
#ifdef ORB60_ENABLE_MAPPER_PUBLISHED
            if(mapper_barrier)map_sync_ms=KvMapperProgress::wait(10000);
#endif
            auto stats=FeatureIO::Stats();auto& raw=KvNetwork::current();
            require(!stats.extractor_calls&&raw.timestamp==f.id.stamp&&raw.count==unsigned(stats.count),"Actual 7015 result identity/CPU ORB violation");
            const int state=slam.GetTrackingState();const bool ok=state==2&&pose.matrix().allFinite();valid+=ok;
            if(KvDepth::ack()=="{\"depth_keyframe_selected\":true}"){publish_rgb(f,out+"/dense/rgb_cache");++selected;}
            if(telemetry)telemetry->capture(slam,color_preview?f.bgr:f.gray,pose,i,f.id.stamp,stats,ms,i+1==ids.size(),&raw.keys);
            journal<<i<<','<<f.id.stamp<<','<<std::llround(double(f.id.stamp)*1e-9*1e9)<<",1,"<<f.id.crc<<','<<raw.records_crc<<','<<stats.count<<','<<state<<','<<ok<<','<<ms<<",0,"<<f.decode_ms<<','<<stats.read_ms<<','<<raw.engine_ns<<','<<cpu_ms<<','<<map_sync_ms<<'\n';
            if((i+1)%30==0||i+1==ids.size()) {
                std::ostringstream progress;progress<<std::setprecision(17)<<"{\"frames\":"<<i+1<<",\"last_state\":"<<state<<",\"valid_poses\":"<<valid<<",\"selected_keyframes\":"<<selected<<",\"seconds\":"<<double(monotonic_ns()-started_ns)*1e-9<<",\"cpu_orb_calls\":0}";
                atomic_json(out+"/processing_progress.json",progress.str());
            }
        }
        input.finish();
    }
    const double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    const uint64_t finished_ns=monotonic_ns();
    journal.close();source.close();require(bool(journal)&&bool(source),"Incomplete native journals");if(telemetry)telemetry->finish();
    std::ofstream result(out+"/network_mapping.json");result<<std::setprecision(17)
      <<"{\"status\":\"MAPPING_DRAINED_EXPORT_PENDING\",\"frames\":"<<ids.size()<<",\"valid_poses\":"<<valid
      <<",\"selected_keyframes\":"<<selected<<",\"cpu_orb_calls\":0,\"seconds\":"<<seconds<<",\"fps\":"<<ids.size()/seconds
      <<",\"started_monotonic_ns\":"<<started_ns<<",\"finished_monotonic_ns\":"<<finished_ns
      <<",\"native_color_preview\":"<<(color_preview?"true":"false")
      <<",\"mapper_barrier\":"<<(mapper_barrier?"true":"false")
#ifdef ORB60_ENABLE_MAPPER_PUBLISHED
      <<",\"mapper_wait_mode\":\""<<(mapper_barrier?"published":"none")<<"\""
#else
      <<",\"mapper_wait_mode\":\""<<(mapper_barrier?"idle":"none")<<"\""
#endif
      <<",\"tracking_cpu_core\":"<<tracking_core
      <<",\"frontend\":\"actual_zynq7015_PL\",\"mapping\":\"KV260_PS\",\"video_decode_included\":true,\"vocabulary_and_final_BA_excluded\":true}\n";result.close();
    std::cout<<"KV260_NETWORK_DRAINED frames="<<ids.size()<<" valid="<<valid<<" seconds="<<seconds<<" fps="<<ids.size()/seconds<<" cpu_orb=0"<<std::endl;
    slam.Shutdown();slam.ExportBridgeMap(out+"/tracking/map");
    std::ofstream done(out+"/NATIVE_COMPLETE");done<<"Actual 7015 PL, KV260 PS mapping, original video decoded and fully drained\n";
    std::cout<<"KV260_NETWORK_MAP_COMPLETE"<<std::endl;return 0;
}catch(const std::exception& e){std::cerr<<"KV260_NETWORK_FAILED: "<<e.what()<<std::endl;return 1;}}
