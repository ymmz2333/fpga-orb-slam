#include "zslam/formats.hpp"
#include "zslam/ports.hpp"
#include "zslam/pipeline.hpp"
#include "zslam/async_stage.hpp"
#include <chrono>
#include <csignal>
#include "zslam/filesystem.hpp"
#include <iomanip>
#include <iostream>
#include <memory>
#include <stdexcept>
#if defined(__linux__)
#include <sys/resource.h>
#endif

namespace {
volatile std::sig_atomic_t stopped=0;
void interrupt(int){stopped=1;}
using Clock=std::chrono::steady_clock;
double elapsed(Clock::time_point p){return std::chrono::duration<double,std::milli>(Clock::now()-p).count();}
unsigned boundedUnsigned(const std::string &text,unsigned maximum){std::size_t end=0;if(text.empty()||text[0]=='-')throw std::runtime_error("Invalid numeric option");unsigned long n=std::stoul(text,&end);if(end!=text.size()||n>maximum)throw std::runtime_error("Numeric option outside bounds");return static_cast<unsigned>(n);}
void usage(){std::cout<<
"zynq-slam --replay HANDOFF/golden [--import-map HANDOFF/map] [--loc-only]\n"
"          --raw gray8.bin --uio /dev/uio0 [--fb /dev/fb0]\n"
"          --camera /dev/video0 --uio /dev/uio0 [--fb /dev/fb0]\n"
"          --camera /dev/video0 --capture-only --frames 300 (no calibration/PL)\n"
"          --camera /dev/video0 --camera-preview --hdmi-uio /dev/uio0 (focus only)\n"
"         --camera-format mjpeg|yuyv|grey (default mjpeg)\n"
"         --camera-width N --camera-height N (default1280x720; center crop960x720)\n"
"         --full-jpeg-decode selects full-width decode for exact region-decode A/B\n"
"         --jpeg-region-decode selects exact horizontal region decode (default on)\n"
"         --calibration-shots N --calibration-every N (capture-only/preview; at most60 PGM images)\n"
"          [--hdmi-uio /dev/uio0] uses paired HDMI_2 scanout, also with replay\n"
"          [--verify-golden GOLDEN] verifies every physical ORB record byte\n"
"Options: --calibration camera.csv --load map.zmap --save new-map.zmap\n"
"         --frames N --skip N --output NEW_DIRECTORY --snapshot\n"
"         --serial disables the bounded capture/ORB pipeline for diagnosis\n"
"         --sync-ui keeps rendering on the SLAM thread for comparison\n"
"         --fresh-gray disables bounded gray-buffer reuse for comparison\n"
"         --no-decode-cache disables exact coordinate caching for comparison\n"
"         --no-trajectory-cache disables exact UI trajectory projections for comparison\n"
"         --trajectory-cache enables experimental UI trajectory caching (default off)\n"
"         --legacy-retrieval-invalidation selects prior index invalidation for comparison\n"
"         --precise-retrieval-invalidation enables experimental precise invalidation\n"
"         --max-points N --max-keyframes N --keyframe-interval N\n"
"         --relocalization-interval N (default 3 after repeated failures)\n"
"         --target-fps N (default30; requests camera rate and sets deadline)\n"
"         --orb-poll-us N (default50; 0 selects baseline busy polling)\n"
"         --log-rows N --log-keep N (camera defaults3600 rows/3 parts; 0 rows means full logs)\n"
"Recorded GRAY8 keeps its original30Hz timestamps regardless of target.\n"
"Controls: m mapping, l localization, s save version, r reset, q quit.\n"
"Live input and framebuffer drivers must already be configured. No PL loading.\n";}
}
int main(int argc,char **argv){
    using namespace zslam;
    try {
        std::string replay_path,raw_path,camera_path,uio_path,fb_path,hdmi_path,oracle_path,calibration,load_path,save_path,import_path,output="output/run";
        Config config;CameraCaptureConfig camera_config;unsigned limit=0,skip=0,target_fps=30,poll_pause_us=50,log_rows=0,log_keep=3,calibration_shots=0,calibration_every=30;bool snapshot=false,serial=false,sync_ui=false,fresh_gray=false,log_rows_set=false,decode_cache=true,trajectory_cache=false,capture_only=false,camera_preview=false;
        for(int i=1;i<argc;i++){std::string arg=argv[i];auto value=[&](){if(++i>=argc)throw std::runtime_error("Missing option value: "+arg);return std::string(argv[i]);};
            if(arg=="--help"){usage();return 0;}else if(arg=="--replay")replay_path=value();else if(arg=="--raw")raw_path=value();
            else if(arg=="--camera")camera_path=value();else if(arg=="--uio")uio_path=value();else if(arg=="--fb")fb_path=value();
            else if(arg=="--hdmi-uio")hdmi_path=value();
            else if(arg=="--verify-golden")oracle_path=value();
            else if(arg=="--calibration")calibration=value();else if(arg=="--load")load_path=value();else if(arg=="--save")save_path=value();
            else if(arg=="--import-map")import_path=value();else if(arg=="--output")output=value();else if(arg=="--frames")limit=boundedUnsigned(value(),100000000);
            else if(arg=="--skip")skip=boundedUnsigned(value(),100000000);else if(arg=="--max-points")config.max_points=boundedUnsigned(value(),50000);
            else if(arg=="--max-keyframes")config.max_keyframes=boundedUnsigned(value(),256);else if(arg=="--keyframe-interval")config.keyframe_interval=boundedUnsigned(value(),10000);
            else if(arg=="--relocalization-interval")config.relocalization_interval=boundedUnsigned(value(),30);
            else if(arg=="--target-fps")target_fps=boundedUnsigned(value(),240);
            else if(arg=="--camera-width")camera_config.width=boundedUnsigned(value(),1280);
            else if(arg=="--camera-height")camera_config.height=boundedUnsigned(value(),800);
            else if(arg=="--camera-format"){auto format=value();if(format=="mjpeg")camera_config.encoding=CameraEncoding::Mjpeg;else if(format=="yuyv")camera_config.encoding=CameraEncoding::Yuyv;else if(format=="grey")camera_config.encoding=CameraEncoding::Grey;else throw std::runtime_error("Unknown camera format");}
            else if(arg=="--full-jpeg-decode")camera_config.jpeg_region_decode=false;
            else if(arg=="--jpeg-region-decode")camera_config.jpeg_region_decode=true;
            else if(arg=="--capture-only")capture_only=true;
            else if(arg=="--camera-preview")camera_preview=true;
            else if(arg=="--calibration-shots")calibration_shots=boundedUnsigned(value(),60);
            else if(arg=="--calibration-every")calibration_every=boundedUnsigned(value(),300);
            else if(arg=="--orb-poll-us")poll_pause_us=boundedUnsigned(value(),1000);
            else if(arg=="--fresh-gray")fresh_gray=true;
            else if(arg=="--no-decode-cache")decode_cache=false;
            else if(arg=="--no-trajectory-cache")trajectory_cache=false;
            else if(arg=="--trajectory-cache")trajectory_cache=true;
            else if(arg=="--legacy-retrieval-invalidation")config.precise_retrieval_invalidation=false;
            else if(arg=="--precise-retrieval-invalidation")config.precise_retrieval_invalidation=true;
            else if(arg=="--log-rows"){log_rows=boundedUnsigned(value(),1000000);log_rows_set=true;}
            else if(arg=="--log-keep")log_keep=boundedUnsigned(value(),16);
            else if(arg=="--loc-only")config.mapping=false;else if(arg=="--snapshot")snapshot=true;else if(arg=="--serial")serial=true;else if(arg=="--sync-ui")sync_ui=true;else throw std::runtime_error("Unknown option: "+arg);
        }
        bool replay=!replay_path.empty();
        if(!target_fps)throw std::runtime_error("Target FPS must be positive");
        if(!log_keep)throw std::runtime_error("Log retention count must be positive");
        if(!calibration_every||(!(capture_only||camera_preview)&&calibration_shots))throw std::runtime_error("Calibration shots require capture-only/preview and positive interval");
        if(capture_only&&camera_preview)throw std::runtime_error("Choose capture-only or camera-preview");
        if(!camera_path.empty()&&!log_rows_set)log_rows=3600;
        if(capture_only){
            if(camera_path.empty()||replay||!raw_path.empty()||!uio_path.empty()||!hdmi_path.empty()||!fb_path.empty()||!import_path.empty()||!load_path.empty()||!save_path.empty()||!oracle_path.empty()||!calibration.empty()||skip)
                throw std::runtime_error("--capture-only needs only a USB camera; no PL/map/display/replay options");
            if(fs::exists(output))throw std::runtime_error("Output directory exists");fs::create_directories(output);
            auto input=v4l2Camera(camera_path,target_fps,camera_config);GrayFrame gray;unsigned captured=0;auto start=Clock::now();
            std::unique_ptr<CalibrationRecorder> shots;if(calibration_shots)shots=std::make_unique<CalibrationRecorder>(output+"/calibration-frames",calibration_shots,calibration_every);
            unsigned capture_limit=limit?limit:(calibration_shots?calibration_shots*calibration_every:300);
            CsvLog log(output+"/capture.csv","frame_index,timestamp_ns,capture_wall_ms,capture_cpu_ms",log_rows,log_keep);
            std::signal(SIGINT,interrupt);std::signal(SIGTERM,interrupt);
            while(!stopped&&captured<capture_limit){auto begin=Clock::now();double cpu=threadCpuMs();if(!input->next(gray))break;
                double capture_wall=elapsed(begin),capture_cpu=threadCpuMs()-cpu;
                if(shots)shots->consider(gray);
                log.row()<<gray.id<<','<<gray.timestamp_ns<<','<<capture_wall<<','<<capture_cpu<<'\n';captured++;}
            if(shots)shots->finish();
            log.finish();writeCameraReport(input->profile(),output+"/camera.json");
            {std::ofstream mode(output+"/capture_mode.json");mode<<"{\"calibration_capture\":"<<(shots?"true":"false")<<",\"saved_images\":"<<(shots?shots->saved():0)<<",\"interval_frames\":"<<calibration_every<<",\"complete_slam_test\":false,\"claim\":\"Calibration capture includes periodic SD image writes; use a separate run without shots for FPS benchmarking\"}\n";if(!mode)throw std::runtime_error("Camera capture mode report failed");}
            if(captured)writeGrayPgm(gray,output+"/last_frame.pgm");
            std::cout<<"CAPTURE_ONLY_COMPLETED frames="<<captured<<" wall_ms="<<elapsed(start)<<" calibration_shots="<<(shots?shots->saved():0)<<" SLAM_NOT_RUN\n";return 0;
        }
        if(camera_preview){
            if(camera_path.empty()||hdmi_path.empty()||replay||!raw_path.empty()||!fb_path.empty()||!import_path.empty()||!load_path.empty()||!save_path.empty()||!oracle_path.empty()||!calibration.empty()||skip||serial||sync_ui||(!uio_path.empty()&&uio_path!=hdmi_path))
                throw std::runtime_error("Camera preview requires a camera and one paired HDMI UIO; no calibration/map/SLAM/replay options");
            if(fs::exists(output))throw std::runtime_error("Output directory exists");fs::create_directories(output);
            auto input=v4l2Camera(camera_path,target_fps,camera_config);
            LiveOrb hardware(hdmi_path,poll_pause_us,false);auto screen=hardware.hdmiDisplay();
            auto buffers=std::make_shared<GrayBufferPool>();Dashboard dashboard;
            CsvLog log(output+"/preview.csv","frame_index,timestamp_ns,focus_score,capture_ms,capture_cpu_ms,render_ms,present_ms,total_ms,queue_latency_ms",log_rows,log_keep);
            std::unique_ptr<CalibrationRecorder> shots;if(calibration_shots)shots=std::make_unique<CalibrationRecorder>(output+"/calibration-frames",calibration_shots,calibration_every);
            struct PreviewPacket {GrayFrame gray;Clock::time_point start;double capture_ms=0,capture_cpu_ms=0;};
            unsigned submitted=0,presented=0;GrayFrame last;auto start=Clock::now(),last_present=start;Timings view;view.preview=true;view.physical=true;view.target_fps=target_fps;
            AsyncStage<PreviewPacket> renderer([&](PreviewPacket &&packet){
                auto &g=packet.gray;Frame frame;frame.id=g.id;frame.timestamp_ns=g.timestamp_ns;
                Status status;status.mapping=false;status.frame=g.id;status.timestamp_ns=g.timestamp_ns;
                view.capture_ms=packet.capture_ms;view.focus_score=cameraFocusScore(g);view.fps=presented*1000./elapsed(start);
                auto stage=Clock::now();dashboard.draw(&g,frame,SceneSnapshot{},status,view);double render_ms=elapsed(stage);
                stage=Clock::now();screen->present(dashboard,g.id);double present_ms=elapsed(stage);
                auto finished=Clock::now();view.total_ms=std::chrono::duration<double,std::milli>(finished-last_present).count();last_present=finished;view.present_ms=present_ms;presented++;
                log.row()<<g.id<<','<<g.timestamp_ns<<','<<view.focus_score<<','<<packet.capture_ms<<','<<packet.capture_cpu_ms<<','<<render_ms<<','<<present_ms<<','<<view.total_ms<<','<<elapsed(packet.start)<<'\n';
                if(presented%30==0)std::cout<<"PREVIEW FRAME "<<g.id<<" focus="<<view.focus_score<<" fps="<<presented*1000./elapsed(start)<<" SLAM_OFF\n";
                if(snapshot){buffers->release(std::move(last.pixels));last=std::move(g);}else buffers->release(std::move(g.pixels));
            },true);
            bool capture_pinned=preferCpu(0);
            std::signal(SIGINT,interrupt);std::signal(SIGTERM,interrupt);
            unsigned preview_limit=limit?limit:(calibration_shots?calibration_shots*calibration_every:0);
            while(!stopped&&(!preview_limit||submitted<preview_limit)){
                PreviewPacket packet;packet.start=Clock::now();double cpu=threadCpuMs();packet.gray.pixels=buffers->acquire();
                if(!input->next(packet.gray)){buffers->release(std::move(packet.gray.pixels));break;}
                packet.capture_ms=elapsed(packet.start);packet.capture_cpu_ms=threadCpuMs()-cpu;
                if(shots)shots->consider(packet.gray);
                renderer.submit(std::move(packet));submitted++;if(readControlKey()=='q')break;
            }
            renderer.finish();if(presented!=submitted)throw std::runtime_error("Preview render queue did not drain");
            if(shots)shots->finish();log.finish();screen->report(output+"/display.json");writeCameraReport(input->profile(),output+"/camera.json");
            if(hardware.profile().frames)throw std::runtime_error("Preview must not extract ORB or run SLAM");
            if(snapshot&&presented){writeGrayPgm(last,output+"/last_frame.pgm");dashboard.savePpm(output+"/dashboard.ppm");}
            double rss=0;
#if defined(__linux__)
            rusage usage{};if(!getrusage(RUSAGE_SELF,&usage))rss=double(usage.ru_maxrss)/1024;
#endif
            std::ofstream report(output+"/preview.json");report<<std::setprecision(12)<<"{\"mode\":\"uncalibrated_camera_focus_preview\",\"processed\":"<<presented<<",\"submitted\":"<<submitted<<",\"fps\":"<<presented*1000./elapsed(start)<<",\"slam_run\":false,\"pose_valid\":false,\"orb_extraction_frames\":0,\"saved_images\":"<<(shots?shots->saved():0)<<",\"gray_pool_reserved_bytes\":"<<buffers->reservedBytes()<<",\"peak_rss_mib\":"<<rss<<",\"cpu_affinity\":"<<(capture_pinned&&renderer.pinned()?"true":"false")<<",\"claim\":\"Focus guide only; score varies with scene, light and noise. No calibration or SLAM pose acceptance. Optional image writes affect throughput.\"}\n";
            if(!report)throw std::runtime_error("Preview report write failed");
            std::cout<<"PREVIEW_COMPLETED frames="<<presented<<" SLAM_NOT_RUN\n";return 0;
        }
        if(!replay&&camera_path.empty()&&raw_path.empty()){usage();return 2;}
        if((!camera_path.empty()&&!raw_path.empty())||(replay&&!camera_path.empty())||(replay&&!uio_path.empty())||(!replay&&uio_path.empty())||(!load_path.empty()&&!import_path.empty()))throw std::runtime_error("Incompatible input/backend/map options");
        if((!hdmi_path.empty()&&!fb_path.empty())||(!replay&&!hdmi_path.empty()&&hdmi_path!=uio_path))throw std::runtime_error("HDMI must share the one ORB UIO; choose one display backend");
        if(replay&&!oracle_path.empty())throw std::runtime_error("Golden byte verification requires physical extraction");
        if(!replay&&calibration.empty())throw std::runtime_error("Live input requires an explicit camera calibration CSV");
        if(!replay&&skip)throw std::runtime_error("--skip is only defined for feature replay");
        if(zslam::fs::exists(output))throw std::runtime_error("Output directory exists; choose a new run directory");zslam::fs::create_directories(output);
        Camera camera=calibration.empty()?Camera{}:readCamera(calibration,!camera_path.empty());
        if(!camera_path.empty())camera=croppedCamera(camera,camera_config.width,camera_config.height);
        if(!calibration.empty())fs::copy_file(calibration,output+"/calibration_source.csv");
        {std::ofstream calibrated(output+"/calibration_orb.csv");calibrated<<std::setprecision(17)<<"width,height,fx,fy,cx,cy,d0,d1,d2,d3,d4\n"<<camera.width<<','<<camera.height<<','<<camera.fx<<','<<camera.fy<<','<<camera.cx<<','<<camera.cy;for(double d:camera.d)calibrated<<','<<d;calibrated<<'\n';if(!calibrated)throw std::runtime_error("Calibration evidence write failed");}
        Slam slam(camera,config);
        if(!load_path.empty())slam.load(load_path);if(!import_path.empty())slam.importHandoff(import_path);
        std::unique_ptr<Replay> source;std::unique_ptr<CameraSource> capture;std::unique_ptr<LiveOrb> orb;std::unique_ptr<DisplaySink> display;
        if(replay)source=std::make_unique<Replay>(replay_path,camera);
        if(!camera_path.empty())capture=v4l2Camera(camera_path,target_fps,camera_config);else if(!raw_path.empty())capture=rawCamera(raw_path);
        if(!replay||!hdmi_path.empty())orb=std::make_unique<LiveOrb>(replay?hdmi_path:uio_path,poll_pause_us,decode_cache);
        if(!oracle_path.empty())orb->verifyGolden(oracle_path);
        if(!hdmi_path.empty())display=orb->hdmiDisplay();else if(!fb_path.empty())display=framebufferDisplay(fb_path);
        auto gray_buffers=!replay&&!serial&&!fresh_gray?std::make_shared<GrayBufferPool>():nullptr;
        TrajectoryWriter trajectory(output+"/trajectory.csv",log_rows,log_keep);
        CsvLog telemetry(output+"/timing.csv","frame_index,timestamp_ns,capture_ms,orb_ms,slam_ms,render_ms,present_ms,total_ms,deadline_miss,dropped,input_wait_ms,latency_ms,match_ms,pose_ms,recovery_pose_ms,recovery_attempted,capture_cpu_ms,orb_cpu_ms,slam_cpu_ms,render_cpu_ms,present_cpu_ms,scene_ms,scene_cpu_ms,ui_image_cpu_ms,ui_geometry_cpu_ms,ui_labels_cpu_ms,ui_trajectory_hits,ui_trajectory_misses,retrieval_builds,retrieval_queries,retrieval_build_cpu_ms,retrieval_query_cpu_ms",log_rows,log_keep);
        struct RenderPacket {
            GrayFrame gray;Frame frame;SceneSnapshot scene;Status status;Timings timing;
            double input_wait_ms=0,capture_cpu_ms=0,orb_cpu_ms=0,slam_cpu_ms=0,scene_ms=0,scene_cpu_ms=0;
            Clock::time_point capture_start;
        };
        Dashboard dashboard(trajectory_cache);Timings timing;timing.physical=!replay;timing.recorded=!raw_path.empty();timing.target_fps=target_fps;
        const Timings base_timing=timing;
        GrayFrame gray;Frame frame;Status status;unsigned submitted=0,processed=0,valid=0;uint64_t dropped=0,misses=0;
        auto run_start=Clock::now(),last_present=run_start;RenderPacket last_snapshot;
        auto render_frame=[&](RenderPacket &&packet){
            auto stage=Clock::now();double cpu_start=threadCpuMs(),render_ms=0,present_ms=0,render_cpu_ms=0,present_cpu_ms=0;
            Timings view=packet.timing;view.fps=processed?processed*1000./elapsed(run_start):0;view.total_ms=timing.total_ms;view.deadline_misses=misses;
            if(display){dashboard.draw(capture?&packet.gray:nullptr,packet.frame,packet.scene,packet.status,view);render_ms=elapsed(stage);render_cpu_ms=threadCpuMs()-cpu_start;
                stage=Clock::now();cpu_start=threadCpuMs();display->present(dashboard,packet.frame.id);present_ms=elapsed(stage);present_cpu_ms=threadCpuMs()-cpu_start;}
            auto finished=Clock::now();double total=std::chrono::duration<double,std::milli>(finished-last_present).count();last_present=finished;
            bool miss=total>1000./target_fps;misses+=miss;dropped+=packet.status.dropped;processed++;valid+=packet.status.pose_valid;
            timing=view;timing.render_ms=render_ms;timing.present_ms=present_ms;timing.total_ms=total;timing.fps=processed*1000./elapsed(run_start);timing.deadline_misses=misses;
            const auto &s=packet.status;const auto &f=packet.frame;
            const auto &draw_profile=dashboard.lastProfile();
            auto &log=telemetry.row();log<<f.id<<','<<f.timestamp_ns<<','<<view.capture_ms<<','<<view.orb_ms<<','<<view.slam_ms<<','<<render_ms<<','<<present_ms<<','<<total<<','<<miss<<','<<s.dropped<<','<<packet.input_wait_ms<<','<<elapsed(packet.capture_start)<<','<<s.match_ms<<','<<s.pose_ms<<','<<s.recovery_pose_ms<<','<<s.recovery_attempted<<','<<packet.capture_cpu_ms<<','<<packet.orb_cpu_ms<<','<<packet.slam_cpu_ms<<','<<render_cpu_ms<<','<<present_cpu_ms<<','<<packet.scene_ms<<','<<packet.scene_cpu_ms<<','<<draw_profile.image_cpu_ms<<','<<draw_profile.geometry_cpu_ms<<','<<draw_profile.labels_cpu_ms<<','<<draw_profile.trajectory_hits<<','<<draw_profile.trajectory_misses<<','<<s.retrieval_builds<<','<<s.retrieval_queries<<','<<s.retrieval_build_cpu_ms<<','<<s.retrieval_query_cpu_ms<<'\n';
            if(!log)throw std::runtime_error("Timing log write failed");
            if(processed%30==0)std::cout<<"FRAME "<<f.id<<" "<<stateName(s.state)<<" inliers="<<s.inliers<<" points="<<s.points<<" core_ms="<<view.slam_ms<<" processing_fps="<<timing.fps<<'\n';
            if(snapshot&&!display){if(gray_buffers)gray_buffers->release(std::move(last_snapshot.gray.pixels));last_snapshot=std::move(packet);}
            else if(gray_buffers)gray_buffers->release(std::move(packet.gray.pixels));
        };
        std::signal(SIGINT,interrupt);std::signal(SIGTERM,interrupt);
        std::unique_ptr<FramePipeline> pipeline;
        std::unique_ptr<AsyncStage<RenderPacket>> renderer;
        bool consumer_pinned=false,workers_pinned=false,renderer_pinned=false;
        const unsigned capture_cpu=display&&!serial&&!sync_ui?0:1;
        if(!replay&&!serial)pipeline=std::make_unique<FramePipeline>(*capture,[&](const GrayFrame &g){return orb->extract(g,camera);},limit,true,capture_cpu,gray_buffers);
        if(display&&!serial&&!sync_ui)renderer=std::make_unique<AsyncStage<RenderPacket>>(render_frame,true);
        // Create workers before narrowing the main thread's inherited CPU mask.
        if(!serial)consumer_pinned=preferCpu(0);
        while(!stopped&&(!limit||submitted<limit)){
            auto begin=Clock::now(),capture_start=begin;double capture_ms=0,orb_ms=0,input_wait_ms=0,capture_cpu_ms=0,orb_cpu_ms=0;
            if(replay){if(!source->next(frame))break;if(frame.id<skip)continue;if(capture&&!capture->next(gray))throw std::runtime_error("GRAY replay ended before feature replay");}
            else if(pipeline){PipelineFrame packet;if(!pipeline->next(packet))break;input_wait_ms=elapsed(begin);
                gray=std::move(packet.gray);frame=std::move(packet.features);capture_ms=packet.capture_ms;orb_ms=packet.orb_ms;capture_cpu_ms=packet.capture_cpu_ms;orb_cpu_ms=packet.orb_cpu_ms;capture_start=packet.capture_start;}
            else {auto start=Clock::now();double cpu_start=threadCpuMs();if(!capture->next(gray))break;capture_ms=elapsed(start);capture_cpu_ms=threadCpuMs()-cpu_start;
                start=Clock::now();cpu_start=threadCpuMs();frame=orb->extract(gray,camera);orb_ms=elapsed(start);orb_cpu_ms=threadCpuMs()-cpu_start;}
            int key=readControlKey();if(key=='q')break;if(key=='m')slam.setMapping(true);if(key=='l')slam.setMapping(false);if(key=='r')slam.reset();
            if(key=='s')slam.save(output+"/map-"+std::to_string(frame.id)+".zmap");
            auto stage=Clock::now();double cpu_start=threadCpuMs();status=slam.process(frame);double slam_ms=elapsed(stage),slam_cpu_ms=threadCpuMs()-cpu_start;trajectory.append(status);
            RenderPacket packet;packet.gray=std::move(gray);packet.frame=std::move(frame);packet.status=status;packet.timing=base_timing;
            packet.timing.capture_ms=capture_ms;packet.timing.orb_ms=orb_ms;packet.timing.slam_ms=slam_ms;packet.capture_start=capture_start;
            packet.input_wait_ms=input_wait_ms;packet.capture_cpu_ms=capture_cpu_ms;packet.orb_cpu_ms=orb_cpu_ms;packet.slam_cpu_ms=slam_cpu_ms;
            if(display||snapshot){stage=Clock::now();cpu_start=threadCpuMs();packet.scene=SceneSnapshot(slam);packet.scene_ms=elapsed(stage);packet.scene_cpu_ms=threadCpuMs()-cpu_start;}
            if(renderer)renderer->submit(std::move(packet));else render_frame(std::move(packet));submitted++;
        }
        if(pipeline)workers_pinned=pipeline->workersPinned();pipeline.reset();
        if(renderer){renderer->finish();renderer_pinned=renderer->pinned();}
        if(processed!=submitted)throw std::runtime_error("Render pipeline did not drain every submitted frame");
        if(display)display->report(output+"/display.json");
        if(!camera_path.empty())writeCameraReport(capture->profile(),output+"/camera.json");
        trajectory.finish();telemetry.finish();
        double run_wall_ms=elapsed(run_start);timing.fps=processed&&run_wall_ms>0?processed*1000./run_wall_ms:0;
        if(snapshot&&processed){if(!display)dashboard.draw(capture?&last_snapshot.gray:nullptr,last_snapshot.frame,last_snapshot.scene,last_snapshot.status,timing);dashboard.savePpm(output+"/dashboard.ppm");}
        if(!save_path.empty())slam.save(save_path);
        double rss=0;
        OrbCpuProfile orb_profile=orb?orb->profile():OrbCpuProfile{};
#if defined(__linux__)
        rusage usage{};if(!getrusage(RUSAGE_SELF,&usage))rss=double(usage.ru_maxrss)/1024;
#endif
        std::ofstream report(output+"/run.json");
        report<<std::setprecision(12)<<"{\n"
          <<"  \"mode\": \""<<(replay?"golden_feature_replay":"physical_orb")<<"\",\n"
          <<"  \"input\": \""<<(!raw_path.empty()?"recorded_gray8":(replay?"feature_replay":"camera"))<<"\",\n"
          <<"  \"pipeline\": "<<(!replay&&!serial?"true":"false")<<",\n"
          <<"  \"render_pipeline\": "<<(renderer?"true":"false")<<",\n"
          <<"  \"relocalization_interval\": "<<config.relocalization_interval<<",\n"
          <<"  \"precise_retrieval_invalidation\": "<<(config.precise_retrieval_invalidation?"true":"false")<<",\n"
          <<"  \"orb_poll_pause_us\": "<<poll_pause_us<<",\n"
          <<"  \"orb_profile_frames\": "<<orb_profile.frames<<",\n  \"orb_engine_cpu_ms\": "<<orb_profile.engine_ms<<",\n"
          <<"  \"orb_verify_cpu_ms\": "<<orb_profile.verify_ms<<",\n  \"orb_decode_cpu_ms\": "<<orb_profile.decode_ms<<",\n"
          <<"  \"decode_cache_hits\": "<<orb_profile.cache_hits<<",\n  \"decode_cache_misses\": "<<orb_profile.cache_misses<<",\n  \"decode_cache_reserved_bytes\": "<<orb_profile.cache_bytes<<",\n"
          <<"  \"capture_cpu_requested\": "<<capture_cpu<<",\n"
          <<"  \"gray_pool_reserved_bytes\": "<<(gray_buffers?gray_buffers->reservedBytes():0)<<",\n"
          <<"  \"trajectory_cache_reserved_bytes\": "<<dashboard.trajectoryCacheBytes()<<",\n"
          <<"  \"log_segment_rows\": "<<log_rows<<",\n  \"log_retained_segments\": "<<(log_rows?log_keep:0)<<",\n"
          <<"  \"cpu_affinity_applied\": "<<(consumer_pinned&&(replay||serial||workers_pinned)&&(!renderer||renderer_pinned)?"true":"false")<<",\n"
          <<"  \"golden_verified_frames\": "<<(!oracle_path.empty()?processed:0)<<",\n"
          <<"  \"processed\": "<<processed<<",\n  \"valid\": "<<valid
          <<",\n  \"points\": "<<status.points<<",\n  \"keyframes\": "<<status.keyframes
          <<",\n  \"processing_fps\": "<<timing.fps<<",\n  \"deadline_misses\": "<<misses
          <<",\n  \"dropped_capture_frames\": "<<dropped<<",\n  \"core_reserved_bytes\": "<<slam.reservedBytes()
          <<",\n  \"peak_rss_mib\": "<<(rss>0?std::to_string(rss):"null")
          <<",\n  \"target_fps\": "<<target_fps<<",\n  \"hardware_acceptance\": \"NOT_VERIFIED\",\n"
          <<"  \"claim\": \"Run wall includes drained render queue and final scanout acknowledgment; total_ms is new-content submission interval; concurrent stages overlap; throughput does not establish pose quality or every deadline\"\n}\n";
        if(!report)throw std::runtime_error("Run report write failed");std::cout<<"COMPLETED frames="<<processed<<" valid="<<valid<<" output="<<output<<'\n';return 0;
    }catch(const std::exception &error){std::cerr<<"STOPPED: "<<error.what()<<'\n';return 1;}
}
