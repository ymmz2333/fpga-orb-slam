#include "ORBextractor.h"
#include "FeatureIO.h"
#include "reference.h"
#include <opencv2/imgcodecs.hpp>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <map>
#include <stdexcept>
#include <cmath>
#include <cstring>
#include <memory>
#include <algorithm>
using ORB_SLAM3::ORBextractor;
#ifndef ORB_CANDIDATE_LAPPING_UPPER
#define ORB_CANDIDATE_LAPPING_UPPER 1000
#endif
static void check(bool value,const std::string& message) { if(!value) throw std::runtime_error(message); }
static bool sameKey(const cv::KeyPoint& a,const cv::KeyPoint& b) {
    return a.pt==b.pt && a.octave==b.octave && a.angle==b.angle && a.size==b.size &&
           a.response==b.response && a.class_id==b.class_id;
}
int main(int argc,char** argv) try {
    std::map<std::string,std::string> args;
    for(int i=1;i<argc;i+=2) { check(i+1<argc,"Expected --option value pairs"); check(args.emplace(argv[i],argv[i+1]).second,"Duplicate option"); }
    const std::vector<std::string> allowed={"--config","--dataset","--timestamps","--output","--probe","--stride"};
    for(const auto& a:args) check(std::find(allowed.begin(),allowed.end(),a.first)!=allowed.end(),"Unknown option "+a.first);
    for(const auto& name:{"--config","--dataset","--timestamps","--output"}) check(args.count(name),std::string("Missing ")+name);
    cv::FileStorage yaml(args["--config"],cv::FileStorage::READ); check(yaml.isOpened(),"Cannot read configuration");
    auto integer=[&](const char* key,int fallback) { return yaml[key].empty()?fallback:int(yaml[key]); };
    int n=integer("ORBextractor.nFeatures",1000),levels=integer("ORBextractor.nLevels",8);
    float scale=float(yaml["ORBextractor.scaleFactor"]);
    int fast=integer("ORBextractor.iniThFAST",20),low=integer("ORBextractor.minThFAST",7);
    check(integer("Design.initialization_multiplier",5)==5,"Accepted inject ABI requires initialization multiplier 5");
    std::vector<int> thresholds;
    cv::FileNode node=yaml["Design.probe_thresholds"];
    if(node.empty()) thresholds={10,15,20,25}; else for(auto it=node.begin();it!=node.end();++it)thresholds.push_back(int(*it));
    check(!thresholds.empty(),"No FAST probe thresholds");
    int stride=args.count("--stride")?std::stoi(args["--stride"]):100;
    check(n>0 && levels>0 && scale>1 && stride>0,"Invalid feature configuration");
    ORBextractor::DesignOptions options;
    options.fixed_fast=integer("Design.fixed_fast",0); options.grid=integer("Design.grid",0);
    options.skip_blur=integer("Design.skip_blur",0); options.box2=integer("Design.box2",0);
    options.angle_bins=integer("Design.angle_bins",0); options.mean_rounding=integer("Design.mean_rounding",0);
    check(!options.box2 || (levels==2 && scale==2.0f),"P2 requires two levels and scale factor 2");
    bool native=!options.fixed_fast&&!options.grid&&!options.skip_blur&&!options.box2&&!options.angle_bins;
    const std::string out=args["--output"];
    ORB_SLAM3::FeatureIO::Configure("dump",out);
    std::ofstream layerlog(out+"/layers.csv"),audit(out+"/descriptor_audit.csv"),probe;
    check(bool(layerlog)&&bool(audit),"Cannot create CSV outputs");
    layerlog<<"frame_index,timestamp_ns,role,level,width,height,budget,candidates,selected,cell_side,cell_cols,cell_rows,empty_cells,shortfall\n";
    audit<<"frame_index,timestamp_ns,role,key_index,level,hamming_same_keypoint,native_byte_equal\n";
    bool probing=args.count("--probe") && args["--probe"]=="1";
    if(probing) { probe.open(out+"/fast_probe.csv"); probe<<"frame_index,timestamp_ns,role,threshold,candidates,budget,cell_side,cell_cols,cell_rows,empty_cells,selected,shortfall\n"; }
    std::unique_ptr<ORBextractor> extractors[2];
    for(int role=0;role<2;++role) { extractors[role].reset(new ORBextractor(n*(role?5:1),scale,levels,fast,low)); extractors[role]->design=options; }
    std::ifstream input(args["--timestamps"]); check(bool(input),"Cannot open timestamps");
    uint64_t ns; size_t frame=0;
    while(input>>ns) {
        cv::Mat image=cv::imread(args["--dataset"]+"/mav0/cam0/data/"+std::to_string(ns)+".png",cv::IMREAD_GRAYSCALE);
        check(!image.empty(),"Image missing at "+std::to_string(ns));
        for(int role=0;role<2;++role) {
            auto& extractor=*extractors[role];
            if(probing) {
                for(int threshold:thresholds) {
                    auto r=extractor.DesignProbeLevel0(image,threshold);
                    probe<<frame<<','<<ns<<','<<role<<','<<threshold<<','<<r.candidates<<','<<r.budget<<','<<r.cell_side<<','<<r.cell_cols<<','<<r.cell_rows<<','<<r.empty_cells<<','<<r.selected<<','<<r.shortfall<<'\n';
                }
                continue;
            }
            // Frame's MONOCULAR constructor calls ExtractORB(0, imGray, 0, 1000).
            // This interval changes ordered output even without stereo; match it
            // exactly so ordered matching/initialization receives native arrays.
            std::vector<cv::KeyPoint> keys; cv::Mat descriptors; std::vector<int> overlap{0,ORB_CANDIDATE_LAPPING_UPPER};
            int mono=extractor(image,cv::Mat(),keys,descriptors,overlap);
            check(descriptors.rows==int(keys.size()) && (keys.empty()||descriptors.cols==32),"Descriptor cardinality mismatch");
            std::string roleName=role?"initialization":"normal",file=std::to_string(ns);
            bool audited=frame%stride==0;
            ORB_SLAM3::FeatureIO::SavePacket(out+"/"+roleName+"/"+file+".orb",audited?out+"/memory/"+roleName+"/"+file+".bin":"",ns,role,image.cols,image.rows,&extractor,mono,keys,descriptors);
            for(const auto& r:extractor.designLayers) {
                layerlog<<frame<<','<<ns<<','<<role<<','<<r.level<<','<<r.width<<','<<r.height<<','<<r.budget<<','<<r.candidates<<','<<r.selected<<','<<r.cell_side<<','<<r.cell_cols<<','<<r.cell_rows<<','<<r.empty_cells<<','<<r.shortfall<<'\n';
                if(options.grid) check(r.selected<=r.budget,"Grid exceeded budget");
            }
            for(const auto& key:keys) {
                check(key.octave>=0 && key.octave<levels && key.angle>=0 && key.angle<360,"Invalid keypoint metadata");
                if(options.angle_bins) { float index=key.angle/(360.f/options.angle_bins); check(std::abs(index-std::round(index))<1e-5,"Angle is not a bin centre"); }
            }
            if(audited) {
                if(native) {
                    std::vector<cv::KeyPoint> originalKeys; cv::Mat originalDescriptors;
                    int originalMono=originalExtract(image,n*(role?5:1),scale,levels,fast,low,originalKeys,originalDescriptors);
                    check(originalMono==mono && originalKeys.size()==keys.size(),"V0/native reference count mismatch");
                    for(size_t k=0;k<keys.size();++k) check(sameKey(keys[k],originalKeys[k]),"V0/native reference keypoint mismatch");
                    check(keys.empty()||cv::countNonZero(descriptors!=originalDescriptors)==0,"V0/native reference descriptor mismatch");
                }
                for(int level=0;level<levels;++level) {
                    std::vector<cv::KeyPoint> local; std::vector<size_t> indices;
                    for(size_t k=0;k<keys.size();++k) if(keys[k].octave==level) {
                        auto key=keys[k]; key.pt.x=std::round(key.pt.x/extractor.GetScaleFactors()[level]); key.pt.y=std::round(key.pt.y/extractor.GetScaleFactors()[level]);
                        local.push_back(key); indices.push_back(k);
                    }
                    if(local.empty()) continue;
                    cv::Mat ref; originalDescribeAt(extractor.mvImagePyramid[level],local,ref);
                    for(size_t k=0;k<indices.size();++k) {
                        int distance=int(cv::norm(descriptors.row(int(indices[k])),ref.row(int(k)),cv::NORM_HAMMING));
                        if(!options.angle_bins&&!options.skip_blur) check(distance==0,"Unchanged descriptor component differs from original");
                        audit<<frame<<','<<ns<<','<<role<<','<<indices[k]<<','<<level<<','<<distance<<','<<(native?1:0)<<'\n';
                    }
                }
            }
        }
        ++frame;
        if(frame%100==0) { layerlog.flush(); audit.flush(); if(probing)probe.flush(); std::cout<<"CANDIDATE_PROGRESS frames="<<frame<<std::endl; }
    }
    check(input.eof() && frame>0,"Invalid or empty timestamps");
    std::cout<<"CANDIDATE_PASS frames="<<frame<<" roles=2 probe="<<probing<<std::endl;
    return 0;
} catch(const std::exception& e) { std::cerr<<"CANDIDATE_FAILED "<<e.what()<<std::endl; return 2; }
