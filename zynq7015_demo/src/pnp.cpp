#include "zslam/math.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
// Small BSD P3P subset, compiled in this translation unit without OpenCV runtime.
#include "../vendor/opencv_p3p/polynom_solver.cpp"
#include "../vendor/opencv_p3p/p3p.cpp"

namespace zslam {
bool robustPose(const Camera &c,const std::vector<Observation> &obs,Pose &pose,
                std::vector<unsigned> &inliers,unsigned minimum,unsigned seed){
    inliers.clear();if(obs.size()<std::max(4u,minimum))return false;
    p3p solver(c.fx,c.fy,c.cx,c.cy);Pose best_pose;std::vector<unsigned> best;
    auto random=[&](){seed=1664525u*seed+1013904223u;return seed;};
    unsigned trials=128;
    for(unsigned trial=0;trial<trials;trial++){
        unsigned a=random()%obs.size(),b,cindex;
        do{b=random()%obs.size();}while(b==a);
        do{cindex=random()%obs.size();}while(cindex==a||cindex==b);
        const auto &x=obs[a],&y=obs[b],&z=obs[cindex];
        V3 ab=y.xyz-x.xyz,ac=z.xyz-x.xyz,area=cross(ab,ac);
        if(dot(area,area)<=1e-10*dot(ab,ab)*dot(ac,ac))continue;
        double rotations[4][3][3]={},translations[4][3]={};
        int n=solver.solve(rotations,translations,
            x.uv.x,x.uv.y,x.xyz.x,x.xyz.y,x.xyz.z,
            y.uv.x,y.uv.y,y.xyz.x,y.xyz.y,y.xyz.z,
            z.uv.x,z.uv.y,z.xyz.x,z.xyz.y,z.xyz.z,0,0,0,0,0,false);
        for(int solution=0;solution<n;solution++){
            Pose hypothesis;
            for(int r=0;r<3;r++){for(int col=0;col<3;col++)hypothesis.r(r,col)=rotations[solution][r][col];hypothesis.t[r]=translations[solution][r];}
            if(!rigid(hypothesis))continue;
            std::vector<unsigned> keep;keep.reserve(obs.size());
            for(unsigned i=0;i<obs.size();i++){
                V3 q=hypothesis.apply(obs[i].xyz);
                // Homogeneous pixel error avoids one division and sqrt per test.
                double dx=c.fx*q.x+(c.cx-obs[i].uv.x)*q.z;
                double dy=c.fy*q.y+(c.cy-obs[i].uv.y)*q.z;
                if(q.z>1e-6&&dx*dx+dy*dy<=16*q.z*q.z)keep.push_back(i);
                if(keep.size()+obs.size()-i-1<=best.size())break;
            }
            if(keep.size()>best.size()){
                best=std::move(keep);best_pose=hypothesis;
                double fraction=double(best.size())/obs.size(),failure=1-fraction*fraction*fraction;
                if(failure<1)trials=std::min(trials,static_cast<unsigned>(std::max(16.,std::ceil(std::log(.001)/std::log(std::max(1e-12,failure))))));
            }
        }
    }
    if(best.size()<minimum||best.size()*10<obs.size()*3)return false;
    std::vector<Observation> support;support.reserve(best.size());for(unsigned i:best)support.push_back(obs[i]);
    std::vector<unsigned> refined;Pose result=best_pose;
    if(!optimizePose(c,support,result,refined,minimum,10))return false;
    for(unsigned i=0;i<obs.size();i++){V3 q=result.apply(obs[i].xyz);if(q.z<=1e-6)continue;
        V2 uv=c.project(q);double dx=uv.x-obs[i].uv.x,dy=uv.y-obs[i].uv.y;
        if(dx*dx+dy*dy<=16)inliers.push_back(i);}
    if(inliers.size()<minimum||inliers.size()*10<obs.size()*3){inliers.clear();return false;}
    pose=result;return true;
}
} // namespace zslam
