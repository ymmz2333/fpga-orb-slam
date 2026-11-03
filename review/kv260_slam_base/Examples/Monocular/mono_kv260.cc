// GPL-3.0-or-later, linked with the retained FPGA-enabled ORB-SLAM3.
#include "System.h"
#include "FeatureIO.h"
#include "BridgeFeatures.h"
#include "OrbTelemetry.h"
#include "DenseFrameTelemetry.h"
#include "bridge_wire.hpp"
#include "BridgeFrame.h"
#include "BridgeDisplay.h"
#include "BridgeTrackingDiagnostics.h"
#include <netdb.h>
#include <csignal>
#include <iostream>

namespace {volatile std::sig_atomic_t interrupted=0;void stop(int){interrupted=1;}}
int main(int argc,char**argv){using namespace ORB_SLAM3;try{
    if(argc!=8)throw std::runtime_error("Usage: mono_kv260 VOCAB KV_YAML CAMERA_ORB_CSV LOCAL_FRONTEND_HOST STREAM_PORT NEW_OUTPUT TELEMETRY_DIR");
    std::string out=argv[6];if(mkdir(out.c_str(),0755))throw std::runtime_error("New output directory required");auto camera=demo::readFile(argv[3],4096);const auto calibration=demo::sha256(camera);
    if(std::getenv("ORB60_VALID_MASK"))throw std::runtime_error("Camera bridge does not use the old video validity mask");
    FeatureIO::Configure("fpga-camera","physical-camera");System slam(argv[1],argv[2],System::MONOCULAR,false);
    if(slam.GetImageScale()!=1.f)throw std::runtime_error("SLAM image scaling must remain1");
    addrinfo hint{},*list=nullptr;hint.ai_socktype=SOCK_STREAM;if(getaddrinfo(argv[4],argv[5],&hint,&list))throw std::runtime_error("Local feature producer lookup failed");
    int fd=-1;for(auto*a=list;a;a=a->ai_next){fd=socket(a->ai_family,a->ai_socktype,a->ai_protocol);if(fd<0)continue;if(!connect(fd,a->ai_addr,a->ai_addrlen))break;close(fd);fd=-1;}freeaddrinfo(list);if(fd<0)throw std::runtime_error("Local feature producer connection failed");
    demo::Connection peer(fd);peer.timeout(10);peer.send(demo::response(demo::Hello,calibration));auto hello=peer.receive();
    if(hello.kind!=demo::Hello||demo::string(hello.body)!=calibration+"\n"+demo::profile+"\n"+demo::string(camera))throw std::runtime_error("Zynq profile/calibration handshake mismatch");
    std::cout<<"BRIDGE_RECEIVER_READY cpu_orb=0"<<std::endl;DenseFrameTelemetry telemetry(argv[7],false);
    std::ofstream journal(out+"/frames.csv");journal<<"source_frame_id,timestamp_ns,slam_timestamp_ns,session,gray_crc,record_crc,count,tracking_state,pose_valid,track_ms,cpu_orb_calls\n"<<std::setprecision(17);
    BridgeDiag::Writer diagnostics(out);
    std::cout<<"BRIDGE_TRACKING_DIAGNOSTICS_V1 enabled; matching policy unchanged"<<std::endl;
    const std::string dense=std::getenv("ORB60_BRIDGE_COLOR_POSES")?std::getenv("ORB60_BRIDGE_COLOR_POSES"):"";
    uint64_t session=0,last_id=0,last_stamp=0,frames=0;bool ended=false;std::signal(SIGTERM,stop);std::signal(SIGINT,stop);
    for(;;){auto p=peer.receive();if(p.kind==demo::End){if(!frames||p.session!=session||p.frame!=last_id||p.stamp!=last_stamp)throw std::runtime_error("End/drain identity mismatch");
            demo::Packet ack;ack.kind=demo::Ack;ack.session=p.session;ack.frame=p.frame;ack.stamp=p.stamp;peer.send(ack);ended=true;break;}
        if(interrupted)throw std::runtime_error("Mapping explicitly stopped; no map published");
        if(p.kind!=demo::Frame||!p.session||(p.flags&~demo::color_expected)||!p.stamp||p.count>1000||p.body.size()!=demo::image_bytes+128+p.count*64+1024||
           (frames&&(p.session!=session||p.frame<=last_id||p.stamp<=last_stamp))||demo::crc32(p.body.data(),demo::image_bytes)!=p.aux)throw std::runtime_error("Invalid physical camera frame");
        session=p.session;last_id=p.frame;last_stamp=p.stamp;cv::Mat image(720,960,CV_8UC1,p.body.data());
        std::vector<uint8_t>payload(p.body.begin()+demo::image_bytes,p.body.end());BridgeFeatures::arm(p.stamp,p.aux,p.count,std::move(payload));
        FeatureIO::Begin(p.stamp);
        BridgeDiag::begin(p.frame,p.stamp,p.count,p.body.data()+demo::image_bytes+128);
        auto start=std::chrono::steady_clock::now();auto pose=slam.TrackMonocular(image,double(p.stamp)*1e-9,{},std::to_string(p.frame));auto stats=FeatureIO::Stats();
        if(stats.extractor_calls||stats.count!=p.count)throw std::runtime_error("CPU ORB/count violation");double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
        auto input_keys=BridgeDisplayKeys(p);
        telemetry.capture(slam,image,pose,p.frame,p.stamp,stats,ms,frames==0,&input_keys);int state=slam.GetTrackingState();
        std::array<double,12> diagnostic_pose{};
        const bool diagnostic_pose_valid=state==2&&pose.matrix().allFinite();
        if(diagnostic_pose_valid){auto matrix=pose.matrix();for(int r=0;r<3;++r)for(int c=0;c<4;++c)diagnostic_pose[4*r+c]=matrix(r,c);}
        diagnostics.write(state,diagnostic_pose_valid?diagnostic_pose.data():nullptr);
        bridgeFrame(slam,pose,p,dense);
        journal<<p.frame<<','<<p.stamp<<','<<std::llround(double(p.stamp)*1e-9*1e9)<<','<<session<<','<<p.aux<<','<<demo::crc32(p.body.data()+demo::image_bytes+128,p.count*64)<<','<<p.count<<','<<state<<','<<(state==2&&pose.matrix().allFinite())<<','<<ms<<",0\n";
        demo::Packet ack;ack.kind=demo::Ack;ack.session=session;ack.frame=p.frame;ack.stamp=p.stamp;peer.send(ack);frames++;
    }
    telemetry.finish();diagnostics.finish();journal.close();if(!ended||!journal)throw std::runtime_error("Input drain/journal incomplete");
    auto stage=[&](const std::string&name){std::ofstream f(out+"/handover_stage.json.part");f<<"{\"stage\":\""<<name<<"\",\"frames\":"<<frames<<",\"cpu_orb_calls\":0}\n";f.close();
        if(!f||std::rename((out+"/handover_stage.json.part").c_str(),(out+"/handover_stage.json").c_str()))throw std::runtime_error("Cannot persist handover stage");
        std::cout<<"BRIDGE_HANDOVER_STAGE "<<name<<std::endl;};
    stage("SHUTDOWN_BEGIN");slam.Shutdown();stage("SHUTDOWN_DONE");stage("EXPORT_BEGIN");slam.ExportBridgeMap(out+"/map");stage("EXPORT_DONE");std::cout<<"BRIDGE_FINAL_MAP_READY frames="<<frames<<" cpu_orb=0"<<std::endl;return 0;
}catch(const std::exception&e){std::cerr<<"KV260_PS_FAILED: "<<e.what()<<std::endl;return 1;}}
