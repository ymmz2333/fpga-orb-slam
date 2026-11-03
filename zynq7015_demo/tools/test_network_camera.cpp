// Software-only socket input gate. Does not construct LiveOrb or touch PL.
#include "zslam/network_camera.hpp"
#include <iostream>
int main(int argc,char**argv){using namespace zslam;std::unique_ptr<CameraSource> camera;try{
    if(argc!=6&&argc!=7)throw std::runtime_error("PORT CALIBRATION MODE FRAMES JOURNAL [manual] required");
    bool manual=argc==7&&std::string(argv[6])=="manual";
    unsigned frames=unsigned(std::stoul(argv[4]));camera=networkCamera(unsigned(std::stoul(argv[1])),argv[2],unsigned(std::stoul(argv[3])),frames,argv[5],manual);
    GrayFrame first;camera->next(first);camera=replayPreflightCamera(std::move(camera),std::move(first));
    GrayFrame out;out.pixels.resize(demo::image_bytes);const auto* allocation=out.pixels.data();
    for(unsigned i=0;manual||i<frames;i++){
        if(!camera->next(out)){if(manual)break;throw std::runtime_error("Early finite input end");}
        if(out.id!=i||out.pixels.data()!=allocation)throw std::runtime_error("Preflight replay/frame/lease ownership mismatch");
        std::cout<<"NETWORK_FRAME "<<out.id<<' '<<out.timestamp_ns<<' '<<demo::crc32(out.pixels.data(),out.pixels.size())<<'\n'<<std::flush;
    }
    if(camera->next(out))throw std::runtime_error("Finite network frame bound exceeded");
    std::cout<<"NETWORK_CAMERA_INPUT_PASS\n";return 0;
}catch(const std::exception&e){
    std::cerr<<"NETWORK_CAMERA_FAILED: "<<e.what()<<'\n';
    if(camera){try{GrayFrame again;camera->next(again);std::cerr<<"FAULT_LATCH_MISSING\n";return 2;}
        catch(const std::exception&again){if(std::string(again.what()).find("fault is latched")==std::string::npos)return 2;std::cout<<"NETWORK_CAMERA_FAULT_LATCH_PASS\n";}}
    return 1;}}
