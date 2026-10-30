// Explicit stopped-service recovery. Uses the production checksum/import/roundtrip
// store, never the synthetic protocol test server or a fabricated mapping session.
#include "zslam/demo_store.hpp"
#include <iostream>
int main(int argc,char **argv){try{
    if(argc!=5)throw std::runtime_error("Usage: zynq-map-install STORE CAMERA BUNDLE EXPECTED_VERSION (demo must be stopped)");
    if(zslam::fs::exists("/run/orb-demo.lock"))throw std::runtime_error("Stop the camera demo before offline installation");
    const std::string folder=argv[3],expected=argv[4];
    demo::MapStore store(argv[1],argv[2]);
    auto manifest=demo::readFile(folder+"/manifest.txt",4096);
    if(demo::sha256(manifest)!=expected)throw std::runtime_error("Expected manifest version differs");
    store.begin(manifest);
    for(const auto &entry:store.manifest().files){auto body=demo::bytes(entry.first+"\n");auto data=demo::readFile(folder+"/"+entry.first);body.insert(body.end(),data.begin(),data.end());store.file(body);}
    auto version=store.prepare();store.publish(version);
    if(store.current()!=expected)throw std::runtime_error("Published version readback differs");
    std::cout<<"MAP_INSTALL_VERIFIED "<<version<<'\n';return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
