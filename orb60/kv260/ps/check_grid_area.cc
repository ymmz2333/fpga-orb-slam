#include "Frame.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <vector>
std::vector<size_t> kv_grid_candidate(const ORB_SLAM3::Frame&,const float&,const float&,const float&,int,int,bool);
uint32_t kv_grid_rng=7015260;
uint32_t next(){kv_grid_rng^=kv_grid_rng<<13;kv_grid_rng^=kv_grid_rng>>17;kv_grid_rng^=kv_grid_rng<<5;return kv_grid_rng;}
volatile size_t kv_grid_sink=0;
int main(){try {
    using ORB_SLAM3::Frame;Frame::mnMinX=0;Frame::mnMinY=0;Frame::mnMaxX=960;Frame::mnMaxY=720;
    Frame::mfGridElementWidthInv=float(FRAME_GRID_COLS)/960;Frame::mfGridElementHeightInv=float(FRAME_GRID_ROWS)/720;
    unsigned checked=0;
    for(bool stereo:{false,true})for(int n:{0,1,280,1000}) {
        Frame f;f.N=n;f.Nleft=stereo?n:-1;f.mvKeys.resize(n);f.mvKeysUn.resize(n);f.mvKeysRight.resize(n);
        for(auto* v:{&f.mvKeys,&f.mvKeysUn,&f.mvKeysRight})for(auto& k:*v){k.pt.x=float(int(next()%8000)-160)/8;k.pt.y=float(int(next()%6080)-160)/8;k.octave=int(next()%8);}
        std::vector<bool> assigned[2];
        for(int side=0;side<2;++side) {
            assigned[side].resize(n,false);const auto& keys=stereo?(side?f.mvKeysRight:f.mvKeys):f.mvKeysUn;
            for(int i=0;i<n;++i){const auto& k=keys[i];int ix=int(std::round(k.pt.x*Frame::mfGridElementWidthInv)),iy=int(std::round(k.pt.y*Frame::mfGridElementHeightInv));
                if(ix<0||iy<0||ix>=FRAME_GRID_COLS||iy>=FRAME_GRID_ROWS)continue;
                (side?f.mGridRight[ix][iy]:f.mGrid[ix][iy]).push_back(size_t(i));assigned[side][i]=true;
            }
        }
        for(unsigned q=0;q<4096;++q) {
            const float x=float(int(next()%8800)-400)/8,y=float(int(next()%6880)-400)/8;
            const float radii[]={0,1,5,15,30,120,2000};const float r=radii[q%7];const int levels[]={-1,0,1,3,7};
            const int min=levels[next()%5],max=levels[next()%5];const bool right=next()%2;
            auto old=f.GetFeaturesInArea(x,y,r,min,max,right);auto result=kv_grid_candidate(f,x,y,r,min,max,right);
            if(old!=result)return 3;
            const auto& keys=stereo?(right?f.mvKeysRight:f.mvKeys):f.mvKeysUn;std::vector<size_t> golden;
            for(int i=0;i<n;++i){const auto& k=keys[i];if(assigned[right][i]&&std::fabs(k.pt.x-x)<r&&std::fabs(k.pt.y-y)<r&&k.octave>=min&&(max<0||k.octave<=max))golden.push_back(size_t(i));}
            std::sort(result.begin(),result.end());if(result!=golden)return 4;++checked;
        }
    }
    Frame f;f.N=1000;f.Nleft=-1;f.mvKeysUn.resize(1000);
    for(int i=0;i<1000;++i){auto& k=f.mvKeysUn[i];k.pt.x=20+next()%920;k.pt.y=20+next()%680;k.octave=next()%8;f.mGrid[int(std::round(k.pt.x*Frame::mfGridElementWidthInv))][int(std::round(k.pt.y*Frame::mfGridElementHeightInv))].push_back(i);}
    auto bench=[&](bool fast){const auto start=std::chrono::steady_clock::now();size_t sum=0;
        for(unsigned i=0;i<30000;++i){float x=float(20+i%920),y=float(20+(i*11)%680),r=float(5+(i%4)*10);auto result=fast?kv_grid_candidate(f,x,y,r,0,7,false):f.GetFeaturesInArea(x,y,r,0,7,false);sum+=result.size();}
        kv_grid_sink+=sum;return std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();};
    double old[3],fast[3];for(int i=0;i<3;++i){old[i]=bench(false);fast[i]=bench(true);}std::sort(old,old+3);std::sort(fast,fast+3);
    std::cout<<"{\"status\":\"EXACT_GRID_AREA_PASS\",\"cases\":"<<checked<<",\"reference_seconds\":"<<old[1]<<",\"candidate_seconds\":"<<fast[1]<<",\"scope\":\"Exact indices/order and independent all-point selection, not full FPS\"}\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
