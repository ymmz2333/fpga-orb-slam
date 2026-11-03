#include "zslam/demo_runtime.hpp"
#include "zslam/demo_color.hpp"
#include "zslam/pipeline.hpp"
#include "zslam/async_stage.hpp"
#include "zslam/network_camera.hpp"
#include <csignal>
#include <iostream>

namespace {volatile std::sig_atomic_t stopped=0;void interrupt(int){stopped=1;}}
int main(int argc,char**argv){using namespace zslam;try{
    std::string source_calibration,working_calibration,store_path,output,camera_device="/dev/video0",uio="/dev/uio0",raw_path,raw_index;unsigned frame_limit=0,stream_port=5601,control_port=5602,map_port=5603,color_port=5604,color_fps=2;
    unsigned network_port=0;std::string network_mode;bool fixed_map_multiview=false,network_manual=false;
    for(int i=1;i<argc;i++){std::string key=argv[i];auto value=[&](){if(++i>=argc)throw std::runtime_error("Missing option value");return std::string(argv[i]);};
        if(key=="--source-calibration")source_calibration=value();else if(key=="--calibration")working_calibration=value();else if(key=="--maps")store_path=value();else if(key=="--output")output=value();
        else if(key=="--camera")camera_device=value();else if(key=="--uio")uio=value();else if(key=="--stream-port")stream_port=unsigned(std::stoul(value()));else if(key=="--control-port")control_port=unsigned(std::stoul(value()));else if(key=="--map-port")map_port=unsigned(std::stoul(value()));
        else if(key=="--color-port")color_port=unsigned(std::stoul(value()));else if(key=="--color-fps")color_fps=unsigned(std::stoul(value()));
        else if(key=="--raw")raw_path=value();else if(key=="--raw-index")raw_index=value();else if(key=="--frames")frame_limit=unsigned(std::stoul(value()));
        else if(key=="--network-camera-port")network_port=unsigned(std::stoul(value()));else if(key=="--network-input-mode")network_mode=value();
        else if(key=="--fixed-map-multiview")fixed_map_multiview=true;
        else if(key=="--network-manual")network_manual=true;
        else throw std::runtime_error("Unknown demo option: "+key);}
    if(color_fps>5||color_port<1024||color_port>65535||color_port==stream_port||color_port==control_port||color_port==map_port)throw std::runtime_error("Color port must be distinct and sampling frequency 0..5 FPS");
    if(network_manual&&(!network_port||frame_limit||network_mode!="live_camera"))throw std::runtime_error("Manual network input requires explicit live mode and no frame limit");
    if(network_port&&(network_port<1024||network_port>65535||network_port==stream_port||network_port==control_port||network_port==map_port||network_port==color_port||!raw_path.empty()||(!network_manual&&(!frame_limit||frame_limit>36000))||(network_mode!="live_camera"&&network_mode!="recorded_diagnostic")))throw std::runtime_error("Explicit network camera mode and distinct port required");
    if(!network_port&&!network_mode.empty())throw std::runtime_error("Network input mode requires its explicit port");
    if((source_calibration.empty()&&!network_port)||working_calibration.empty()||store_path.empty()||output.empty()||fs::exists(output)||stream_port<1024||stream_port>65535||control_port<1024||control_port>65535||map_port<1024||map_port>65535||stream_port==control_port||map_port==stream_port||map_port==control_port)throw std::runtime_error("Explicit calibrations, distinct ports, map store and new output directory required");
    fs::create_directories(output);CameraCaptureConfig capture_config;capture_config.width=1280;capture_config.height=720;capture_config.encoding=CameraEncoding::Mjpeg;
    capture_config.color_interval_ns=color_fps?1000000000ull/color_fps:0;
    if(!raw_path.empty()&&raw_index.empty())throw std::runtime_error("Recorded input requires its exact frame/timestamp index");
    Camera camera=raw_path.empty()&&!network_port?croppedCamera(readCamera(source_calibration,true),1280,720):readCamera(working_calibration),expected=readCamera(working_calibration);
    if(camera.width!=expected.width||camera.height!=expected.height||camera.fx!=expected.fx||camera.fy!=expected.fy||camera.cx!=expected.cx||camera.cy!=expected.cy||camera.d!=expected.d)throw std::runtime_error("Source/cropped calibration mismatch");
    demo::State state;demo::MapStore maps(store_path,working_calibration);Config config;config.mapping=false;config.max_points=zslam::handoff_max_points;config.max_keyframes=zslam::handoff_max_keyframes;config.fixed_map_multiview=fixed_map_multiview;
    auto slam=std::make_unique<Slam>(camera,config);auto capture=network_port?networkCamera(network_port,working_calibration,network_mode=="live_camera"?0:1,frame_limit,output+"/network_input.csv",network_manual):(raw_path.empty()?v4l2Camera(camera_device,30,capture_config):rawCamera(raw_path,30,raw_index));LiveOrb orb(uio);auto display=orb.hdmiDisplay();
    // Real PL transaction for both camera and explicitly selected recorded pixels.
    GrayFrame preflight;if(!capture->next(preflight))throw std::runtime_error("No camera preflight frame");orb.extract(preflight,camera);state.hardware_verified=true;
    if(!raw_path.empty())capture=rawCamera(raw_path,30,raw_index);
    if(network_port)capture=replayPreflightCamera(std::move(capture),std::move(preflight));
    auto environmentFor=[&](const std::string &version){auto result=std::make_shared<std::vector<DensePoint>>();if(version.empty())return result;
        auto path=maps.versionPath(version);auto manifest=demo::Manifest::parse(demo::readFile(path+"/manifest.txt",4096),maps.calibration());
        if(manifest.files.count("dense_environment.bin")){auto file=path+"/dense_environment.bin";if(demo::sha256(demo::readFile(file))!=manifest.files.at("dense_environment.bin").digest)throw std::runtime_error("Installed dense environment SHA mismatch");
            *result=readDenseEnvironment(file,manifest.files.at("points.csv").digest,maps.calibration());}return result;};
    auto current=maps.current();if(!current.empty()){slam->load(maps.versionPath(current)+"/map.zmap");state.version=current;state.mode=demo::Mode::Local;state.map_id=demo::Manifest::parse(demo::readFile(maps.versionPath(current)+"/manifest.txt"),maps.calibration()).map_id;}
    auto environment=environmentFor(current);std::shared_ptr<std::vector<DensePoint>> rendered_environment;
    auto empty_environment=std::make_shared<std::vector<DensePoint>>();
    std::cout<<"DEMO_INPUT="<<(network_port?(network_mode=="live_camera"?"KV260_CAMERA":"EXPLICIT_NETWORK_RECORDING"):(raw_path.empty()?"CAMERA":"EXPLICIT_RECORDING"))<<" DENSE_ENVIRONMENT_POINTS="<<environment->size()<<" FIXED_MAP_MULTIVIEW="<<fixed_map_multiview<<" CPU_ORB=0\n"<<std::flush;
    demo::Runtime bridge(state,maps,working_calibration,stream_port,control_port,map_port);
    demo::ColorChannel color(state,maps.calibration(),color_port);
    CsvLog timing(output+"/timing.csv","frame_id,timestamp_ns,mode,map_id,map_version,features,pose_valid,matches,inliers,capture_ms,orb_ms,localization_ms",network_manual?0:3600,3);
    CsvLog poses(output+"/poses.csv","frame_id,timestamp_ns,map_id,map_version,pose_valid,tx,ty,tz,r00,r01,r02,r10,r11,r12,r20,r21,r22",network_manual?0:3600,3,17);
    CsvLog rendering(output+"/render.csv","frame_id,draw_cpu_ms,image_cpu_ms,geometry_cpu_ms,labels_cpu_ms,present_ms,background_builds,background_hits,trajectory_hits,trajectory_misses",network_manual?0:3600,3);
    auto buffers=std::make_shared<GrayBufferPool>();Dashboard dashboard(true);
    struct Render {GrayFrame gray;Frame frame;SceneSnapshot scene;Status status;Timings time;std::string banner;std::shared_ptr<std::vector<DensePoint>> environment;};
    AsyncStage<Render> renderer([&](Render&&p){{std::lock_guard<std::mutex>l(state.mutex);
        if(state.mode!=demo::Mode::Local){p.status.pose_valid=false;p.scene=SceneSnapshot{};p.environment=empty_environment;}
        if(state.mode==demo::Mode::Stopped||state.mode==demo::Mode::Fault){p.status.state=State::Lost;p.status.mapping=false;p.frame.features.clear();p.banner=std::string(demo::name(state.mode))+" - PROCESSING STOPPED | "+state.failure;}}
        if(p.environment&&rendered_environment!=p.environment){dashboard.setDenseEnvironment(*p.environment);rendered_environment=p.environment;}
        double draw_begin=threadCpuMs();dashboard.draw(&p.gray,p.frame,p.scene,p.status,p.time);dashboard.demoBanner(p.banner);
        double draw_ms=threadCpuMs()-draw_begin;auto present_begin=std::chrono::steady_clock::now();display->present(dashboard,p.gray.id);
        const auto &profile=dashboard.lastProfile();rendering.row()<<p.gray.id<<','<<draw_ms<<','<<profile.image_cpu_ms<<','<<profile.geometry_cpu_ms<<','<<profile.labels_cpu_ms<<','
            <<std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-present_begin).count()<<','<<profile.background_builds<<','<<profile.background_hits<<','<<profile.trajectory_hits<<','<<profile.trajectory_misses<<'\n';
        buffers->release(std::move(p.gray.pixels));},true);
    bool extracted=false;
    auto pipeline=std::make_unique<FramePipeline>(*capture,[&](const GrayFrame&g){demo::Mode mode;{std::lock_guard<std::mutex>l(state.mutex);mode=state.mode;}
        extracted=false;if(mode==demo::Mode::Stopped||mode==demo::Mode::Fault){Frame f;f.id=g.id;f.timestamp_ns=g.timestamp_ns;return f;}auto f=orb.extract(g,camera);extracted=true;return f;
    },frame_limit,true,0,buffers,[&]{return extracted?orb.resultPayload():std::vector<uint8_t>{};},3,2);
    preferCpu(0);
    std::signal(SIGINT,interrupt);std::signal(SIGTERM,interrupt);auto start=std::chrono::steady_clock::now();uint64_t frames=0,valid=0;
    bool failed=false;PipelineFrame f;try{while(!stopped&&pipeline->next(f)){
        std::string pending;{std::lock_guard<std::mutex>l(state.mutex);if(state.mode==demo::Mode::Installing)pending=std::move(state.pending_version);state.pending_version.clear();}
        if(!pending.empty()){try{auto restored=std::make_unique<Slam>(camera,config);restored->load(maps.versionPath(pending)+"/map.zmap");
                auto map_id=demo::Manifest::parse(demo::readFile(maps.versionPath(pending)+"/manifest.txt"),maps.calibration()).map_id;auto pending_environment=environmentFor(pending);
                std::lock_guard<std::mutex>l(state.mutex);if(state.mode==demo::Mode::Installing){maps.publish(pending);slam.swap(restored);environment=pending_environment;state.version=pending;state.mode=demo::Mode::Local;state.consecutive=0;state.ready=false;state.failure.clear();state.map_id=map_id;}
            }catch(const std::exception&e){state.fault(e.what());}}
        if(readControlKey()=='r'){std::lock_guard<std::mutex>l(state.mutex);if(!state.version.empty()&&state.mode==demo::Mode::Local){state.pending_version=state.version;state.mode=demo::Mode::Installing;state.ready=false;}}
        demo::Mode mode;uint64_t mid,sid;std::string version;{std::lock_guard<std::mutex>l(state.mutex);mode=state.mode;mid=state.map_id;sid=state.session;version=state.version;}
        if((mode==demo::Mode::Mapping||mode==demo::Mode::Local)&&f.raw_payload.empty()){buffers->release(std::move(f.gray.pixels));continue;}
        Status status;status.frame=f.gray.id;status.timestamp_ns=f.gray.timestamp_ns;status.features=unsigned(f.features.features.size());status.mapping=false;
        auto began=std::chrono::steady_clock::now();double loc_ms=0;
        if(mode==demo::Mode::Mapping){if(f.raw_payload.size()!=128+f.features.features.size()*64+1024)throw std::runtime_error("Raw PL payload/frame count mismatch");demo::Packet packet;packet.kind=demo::Frame;packet.frame=f.gray.id;packet.stamp=f.gray.timestamp_ns;packet.count=status.features;packet.aux=demo::crc32(f.gray.pixels.data(),f.gray.pixels.size());
            if(!f.gray.color_jpeg.empty())packet.flags|=demo::color_expected;
            color.publish(sid,f.gray.id,f.gray.timestamp_ns,packet.aux,std::move(f.gray.color_jpeg));
            packet.body=std::move(f.gray.pixels);packet.body.insert(packet.body.end(),f.raw_payload.begin(),f.raw_payload.end());f.gray.pixels.assign(packet.body.begin(),packet.body.begin()+demo::image_bytes);bridge.enqueue(std::move(packet));}
        else if(mode==demo::Mode::Local){status=slam->process(f.features);loc_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-began).count();state.observe(status.pose_valid);}
        frames++;valid+=status.pose_valid;timing.row()<<f.gray.id<<','<<f.gray.timestamp_ns<<','<<demo::name(mode)<<','<<mid<<','<<version<<','<<status.features<<','<<status.pose_valid<<','<<status.matches<<','<<status.inliers<<','<<f.capture_ms<<','<<f.orb_ms<<','<<loc_ms<<'\n';
        auto &row=poses.row();row<<f.gray.id<<','<<f.gray.timestamp_ns<<','<<mid<<','<<version<<','<<status.pose_valid;
        if(status.pose_valid){auto twc=status.tcw.inverse();row<<','<<twc.t.x<<','<<twc.t.y<<','<<twc.t.z;for(double v:twc.r.a)row<<','<<v;}else for(int i=0;i<12;i++)row<<',';row<<'\n';
        Render p;p.gray=std::move(f.gray);p.frame=std::move(f.features);p.status=status;if(mode==demo::Mode::Local)p.scene=SceneSnapshot(*slam);p.time.physical=true;p.time.capture_ms=f.capture_ms;p.time.orb_ms=f.orb_ms;p.time.slam_ms=loc_ms;
        p.environment=environment;p.time.recorded=!raw_path.empty()||(network_port&&network_mode=="recorded_diagnostic");p.time.fps=frames/std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();p.banner=(network_port?(network_mode=="live_camera"?"KV260 CAMERA | ":"RECORDED NETWORK INPUT | "):(raw_path.empty()?"CAMERA | ":"RECORDED INPUT + LIVE PL | "))+std::string(demo::name(mode))+" | "+(mode==demo::Mode::Mapping?"KV260 MAPPING - HDMI CAMERA/FEATURES ONLY":mode==demo::Mode::Local?"SPARSE LOCALIZATION / DENSE ENVIRONMENT":"NO VALID POSE");
        {std::lock_guard<std::mutex>l(state.mutex);if(state.ready)p.banner+=network_port?" | FIXED MAP LOCALIZATION READY":" | READY TO DISCONNECT KV260";if(!state.failure.empty())p.banner+=" | "+state.failure;}
        renderer.submit(std::move(p));
    }}catch(const std::exception&e){failed=true;state.fault(e.what(),true);pipeline.reset();
        try{Render fault;fault.gray.pixels.assign(960*720,0);fault.time.physical=true;fault.banner=std::string("ERROR - PROCESSING STOPPED | ")+e.what();renderer.submit(std::move(fault));}catch(...){}
        std::cerr<<"DEMO_PROCESSING_STOPPED: "<<e.what()<<'\n';}
    pipeline.reset();try{renderer.finish();}catch(const std::exception&e){failed=true;state.fault(e.what(),true);}
    timing.finish();poses.finish();rendering.finish();try{display->report(output+"/display.json");}catch(const std::exception&e){failed=true;state.fault(e.what(),true);}
    if(failed){demo::writeFile(output+"/fault.json",demo::bytes(bridge.status()));while(!stopped){bool stop;{std::lock_guard<std::mutex>l(state.mutex);stop=state.mode==demo::Mode::Stopped;}if(stop)break;std::this_thread::sleep_for(std::chrono::milliseconds(100));}}
    demo::writeFile(output+"/color.json",demo::bytes(color.report()));
    demo::writeFile(output+"/status.json",demo::bytes(bridge.status()));std::cout<<"DEMO_STOPPED frames="<<frames<<" valid="<<valid<<" cpu_orb=0\n";return failed?1:0;
}catch(const std::exception&e){std::cerr<<"DEMO_FAILED: "<<e.what()<<'\n';return 1;}}
