#pragma once
#include <cstdlib>
#include <fstream>
#include <cstdint>
#include <opencv2/features2d.hpp>
#include <vector>
#include <set>
#include <algorithm>
#include <cmath>
namespace ORB_SLAM3 { namespace RelocDiagnostic {
struct Sink {
    std::ofstream stream; unsigned long frame=0;
    Sink(){const char* p=std::getenv("ORB_RELOC_DIAGNOSTICS"); if(p){stream.open(p);stream<<"frame_id,event,solver,outer_round,call_iteration,total_iteration,max_iterations,bNoMore,solver_inliers,refined_inliers,pose_inliers,matched\n";stream.flush();}}
};
inline Sink& sink(){static Sink s;return s;}
inline void frame(unsigned long n){sink().frame=n;}
inline void event(const char* stage,const void* solver,int outer,int local,int total,int maximum,int noMore,int inliers,int refined,int good,int matched){
    Sink& s=sink(); if(!s.stream.is_open())return;
    s.stream<<s.frame<<','<<stage<<','<<reinterpret_cast<uintptr_t>(solver)<<','<<outer<<','<<local<<','<<total<<','<<maximum<<','<<noMore<<','<<inliers<<','<<refined<<','<<good<<','<<matched<<'\n';s.stream.flush();
}
inline void selected(uint64_t ns,int role,int width,int height,int requested,float scaleFactor,const std::vector<float>& scales,const std::vector<cv::KeyPoint>& keys){
    static const char* path=std::getenv("ORB_SELECTED_STATS");if(!path)return;
    static std::ofstream f(path);static bool header=false;
    if(!header){f<<"timestamp_ns,role,level,width,height,native_formula_budget,selected,virtual_grid_cells,virtual_empty_cells\n";header=true;}
    std::vector<int> budgets(scales.size());float factor=1.0f/scaleFactor;
    float desired=requested*(1-factor)/(1-std::pow(factor,int(scales.size())));int used=0;
    for(size_t i=0;i+1<scales.size();++i){budgets[i]=cvRound(desired);used+=budgets[i];desired*=factor;}
    budgets.back()=std::max(0,requested-used);
    for(size_t l=0;l<budgets.size();++l){
        const int w=cvRound(width/scales[l]),h=cvRound(height/scales[l]),ew=w-32,eh=h-32,b=budgets[l];
        int side=1,cols=0,rows=0;if(b>0&&ew>0&&eh>0){side=std::max(1,int(std::sqrt(double(ew)*eh/b)));cols=std::max(1,ew/side);rows=std::max(1,eh/side);}
        size_t count=0;std::set<int> occupied;
        for(const auto& k:keys)if(k.octave==int(l)){
            ++count;if(cols&&rows){int x=cvRound(k.pt.x/scales[l])-16,y=cvRound(k.pt.y/scales[l])-16;
                x=std::max(0,std::min(cols-1,x/side));y=std::max(0,std::min(rows-1,y/side));occupied.insert(y*cols+x);}
        }
        f<<ns<<','<<role<<','<<l<<','<<w<<','<<h<<','<<b<<','<<count<<','<<cols*rows<<','<<(cols*rows-int(occupied.size()))<<'\n';
    }f.flush();
}
}}
