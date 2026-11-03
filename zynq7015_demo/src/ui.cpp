#include "zslam/ui.hpp"
#include "zslam/profiling.hpp"
#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <limits>
#if defined(__ARM_NEON)
#include <arm_neon.h>
#endif

namespace zslam {
namespace {
constexpr uint16_t bg=0x0862,panel=0x10c4,white=0xef9e,muted=0x8c72,green=0x4f31,cyan=0x2e9f,red=0xf9a7,yellow=0xfe88;
void fillPixels(uint16_t *p,std::size_t count,uint16_t value){
#if defined(__ARM_NEON)
    uint16x8_t v=vdupq_n_u16(value);
    while(count>=32){vst1q_u16(p,v);vst1q_u16(p+8,v);vst1q_u16(p+16,v);vst1q_u16(p+24,v);p+=32;count-=32;}
    while(count>=8){vst1q_u16(p,v);p+=8;count-=8;}
#endif
    std::fill(p,p+count,value);
}
#if defined(__ARM_NEON)
uint16x8_t gray565(uint8x8_t gray){
    // g<<8 supplies red; shift-right inserts fill green, then blue.
    // Preserve exactly the same R5/G6/B5 bits as the scalar palette.
    uint16x8_t high=vshll_n_u8(gray,8);
    return vsriq_n_u16(vsriq_n_u16(high,high,5),high,11);
}
#endif
// Five columns, seven rows; all UI labels are ASCII to avoid fonts/Qt/OpenGL.
std::array<unsigned char,5> glyph(char c){
    switch(c){
    case 'A':return {126,9,9,9,126};case 'B':return {127,73,73,73,54};case 'C':return {62,65,65,65,34};case 'D':return {127,65,65,34,28};
    case 'E':return {127,73,73,73,65};case 'F':return {127,9,9,9,1};case 'G':return {62,65,73,73,122};case 'H':return {127,8,8,8,127};
    case 'I':return {65,65,127,65,65};case 'J':return {32,64,65,63,1};case 'K':return {127,8,20,34,65};case 'L':return {127,64,64,64,64};
    case 'M':return {127,2,12,2,127};case 'N':return {127,4,8,16,127};case 'O':return {62,65,65,65,62};case 'P':return {127,9,9,9,6};
    case 'Q':return {62,65,81,33,94};case 'R':return {127,9,25,41,70};case 'S':return {38,73,73,73,50};case 'T':return {1,1,127,1,1};
    case 'U':return {63,64,64,64,63};case 'V':return {31,32,64,32,31};case 'W':return {63,64,56,64,63};case 'X':return {99,20,8,20,99};
    case 'Y':return {7,8,112,8,7};case 'Z':return {97,81,73,69,67};case '0':return {62,81,73,69,62};case '1':return {0,66,127,64,0};
    case '2':return {98,81,73,73,70};case '3':return {34,65,73,73,54};case '4':return {24,20,18,127,16};case '5':return {39,69,69,69,57};
    case '6':return {60,74,73,73,48};case '7':return {1,113,9,5,3};case '8':return {54,73,73,73,54};case '9':return {6,73,73,41,30};
    case '.':return {0,96,96,0,0};case ':':return {0,54,54,0,0};case '-':return {8,8,8,8,8};case '/':return {96,16,8,4,3};
    case '[':return {0,127,65,65,0};case ']':return {0,65,65,127,0};case '+':return {8,8,62,8,8};case '%':return {99,19,8,100,99};
    default:return {};}
}
std::string format(const char *label,double value,const char *unit=""){char s[128];std::snprintf(s,sizeof(s),"%s %.2f %s",label,value,unit);return s;}
}
Dashboard::Dashboard(bool trajectory_cache):pixels(static_cast<std::size_t>(width)*height,bg),trajectory_pixels_(trajectory_cache?trajectory_slots_:0){}
void Dashboard::pixel(int x,int y,uint16_t color){if(x>=0&&y>=0&&static_cast<unsigned>(x)<width&&static_cast<unsigned>(y)<height)pixels[static_cast<std::size_t>(y)*width+static_cast<unsigned>(x)]=color;}
void Dashboard::rect(int x,int y,int w,int h,uint16_t color){
    int left=std::max(0,x),right=std::min(static_cast<int>(width),x+w);
    if(left>=right)return;
    for(int yy=std::max(0,y);yy<std::min(static_cast<int>(height),y+h);yy++){
        auto row=pixels.data()+static_cast<std::size_t>(yy)*width;
        fillPixels(row+left,static_cast<std::size_t>(right-left),color);
    }
}
void Dashboard::line(int x0,int y0,int x1,int y1,uint16_t color){
    if(x0==x1&&y0==y1){pixel(x0,y0,color);return;}
    const bool inside=x0>=0&&y0>=0&&x1>=0&&y1>=0&&x0<static_cast<int>(width)&&x1<static_cast<int>(width)&&y0<static_cast<int>(height)&&y1<static_cast<int>(height);
    if(!inside){
    // Clip the line before Bresenham so out-of-view map points cannot cause long loops.
    double x=x0,y=y0,dx=double(x1)-x0,dy=double(y1)-y0,t0=0,t1=1;
    auto clip=[&](double p,double q){if(p==0)return q>=0;double r=q/p;if(p<0)t0=std::max(t0,r);else t1=std::min(t1,r);return t0<=t1;};
    if(!clip(-dx,x)||!clip(dx,double(width)-1-x)||!clip(-dy,y)||!clip(dy,double(height)-1-y))return;
    x0=static_cast<int>(std::lround(x+t0*dx));y0=static_cast<int>(std::lround(y+t0*dy));x1=static_cast<int>(std::lround(x+t1*dx));y1=static_cast<int>(std::lround(y+t1*dy));
    }
    int ax=std::abs(x1-x0),sx=x0<x1?1:-1,ay=-std::abs(y1-y0),sy=y0<y1?1:-1,e=ax+ay;
    for(;;){pixel(x0,y0,color);if(x0==x1&&y0==y1)break;int twice=2*e;if(twice>=ay){e+=ay;x0+=sx;}if(twice<=ax){e+=ax;y0+=sy;}}
}
void Dashboard::text(int x,int y,const std::string &value,uint16_t color,int scale){for(char ch:value){if(ch>='a'&&ch<='z')ch=static_cast<char>(ch-'a'+'A');auto g=glyph(ch);for(int c=0;c<5;c++)for(int r=0;r<7;r++)if(g[c]&(1u<<r))rect(x+c*scale,y+r*scale,scale,scale,color);x+=6*scale;}}
void Dashboard::draw(const GrayFrame *gray,const Frame &frame,const Slam &slam,const Status &s,const Timings &timing){
    draw(gray,frame,SceneSnapshot(slam),s,timing);
}
void Dashboard::draw(const GrayFrame *gray,const Frame &frame,const SceneSnapshot &scene,const Status &s,const Timings &timing){
    if(timing.preview&&(s.pose_valid||s.points||s.keyframes||!frame.features.empty()||!scene.points.empty()||!scene.trajectory.empty()))throw std::runtime_error("Uncalibrated preview cannot show features, map or pose");
    double profile_start=threadCpuMs();
    profile_.trajectory_hits=profile_.trajectory_misses=0;
    profile_.background_builds=profile_.background_hits=0;
    if(!initialized_||preview_mode_!=timing.preview){
        rect(0,0,1280,64,panel);text(24,17,"ZYNQ / SPATIAL",white,3);
        rect(16,80,736,576,panel);rect(768,80,496,576,panel);
        text(32,94,timing.preview?"CAMERA / FOCUS":"CAMERA / FPGA ORB",muted,2);text(784,94,timing.preview?"FOCUS CHECK / NO SLAM":"3D MAP + CAMERA TRAJECTORY",muted,2);
        initialized_=true;preview_mode_=timing.preview;
    }
    rect(412,12,844,44,panel);
    text(420,20,timing.preview?"FOCUS PREVIEW":(s.mapping?"LIVE MAPPING":"LOCALIZATION"),cyan,2);
    text(750,24,timing.preview?"CAMERA ONLY / NO POSE":(timing.recorded?"RECORDING / RELATIVE SCALE":(timing.physical?"LIVE / RELATIVE SCALE":"REPLAY / RELATIVE SCALE")),muted,1);
    text(1020,20,timing.preview?"UNCALIBRATED":stateName(s.state),s.pose_valid?green:yellow,2);
    double image_start=threadCpuMs();profile_.labels_cpu_ms=image_start-profile_start;
    const int ix=32,iy=124,iw=704,ih=528;
    if(gray&&gray->width==960&&gray->height==720&&gray->pixels.size()==960*720){
        std::array<uint16_t,256> palette;std::array<unsigned,iw> columns;
        for(unsigned v=0;v<256;v++)palette[v]=static_cast<uint16_t>(((v>>3)<<11)|((v>>2)<<5)|(v>>3));
        for(int x=0;x<iw;x++)columns[x]=static_cast<unsigned>(x*960/iw);
        for(int y=0;y<ih;y++){
            const uint8_t *source=gray->pixels.data()+static_cast<std::size_t>(y*720/ih)*960;
            uint16_t *row=pixels.data()+static_cast<std::size_t>(iy+y)*width+ix;
#if defined(__ARM_NEON)
            // Exact 15/11 nearest-neighbor ratio: 30 input -> 22 output pixels.
            // The final load includes two unused bytes of the following row;
            // the last sampled row is 718, so every load stays inside the frame.
            // vld4 reads one32-byte group into deinterleaved registers. Map
            // source byte i to register-table index (i%4)*8+i/4. This avoids
            // GCC7 spilling the loop-built four-register table through stack.
            static const uint8_t indices[3][8]={{0,8,16,1,9,17,2,10},{18,3,11,27,4,12,28,5},{13,29,6,14,30,7,255,255}};
            for(unsigned block=0;block<32;block++){
                const uint8_t *p=source+block*30;uint8x8x4_t table=vld4_u8(p);
                uint16x8_t a=gray565(vtbl4_u8(table,vld1_u8(indices[0]))),b=gray565(vtbl4_u8(table,vld1_u8(indices[1]))),c=gray565(vtbl4_u8(table,vld1_u8(indices[2])));
                uint16_t *out=row+block*22;vst1q_u16(out,a);vst1q_u16(out+8,b);vst1_u16(out+16,vget_low_u16(c));
                out[20]=vgetq_lane_u16(c,4);out[21]=vgetq_lane_u16(c,5);
            }
#else
            for(int x=0;x<iw;x++)row[x]=palette[source[columns[x]]];
#endif
        }
    }else {rect(ix,iy,iw,ih,0x0842);text(ix+130,iy+220,"FEATURE REPLAY",muted,3);text(ix+130,iy+254,"GRAY INPUT NOT ATTACHED",muted,2);}
    for(const auto &f:frame.features){int x=ix+static_cast<int>(f.raw.x*iw/960),y=iy+static_cast<int>(f.raw.y*ih/720);rect(x-1,y-1,3,3,green);}
    double geometry_start=threadCpuMs();profile_.image_cpu_ms=geometry_start-image_start;
    // Reuse only the static cloud projection. Compare every geometry/color
    // input exactly so mapping, reset and a different loaded map invalidate it.
    // The camera pose is fresh each frame. Reuse a trajectory projection only
    // for the identical sample and identical cloud-derived viewing transform.
    const auto &cloud=scene.points;bool same_cloud=cloud_valid_&&cloud.size()==cloud_cache_.size();
    if(same_cloud)for(std::size_t i=0;i<cloud.size();i++){
        const auto &a=cloud[i],&b=cloud_cache_[i];
        if(a.id!=b.id||a.xyz.x!=b.xyz.x||a.xyz.y!=b.xyz.y||a.xyz.z!=b.xyz.z||
           (dense_environment_.empty()&&(a.observations>5)!=(b.observations>5))){same_cloud=false;break;}
    }
    if(!same_cloud){
        if(++projection_generation_==0){for(auto &entry:trajectory_pixels_)entry.generation=0;projection_generation_=1;}
        V3 center{};for(const auto &p:cloud)center=center+p.xyz;if(!cloud.empty())center=center/static_cast<double>(cloud.size());
        std::vector<double> radii;for(const auto &p:cloud)radii.push_back(norm(p.xyz-center));radius_=3;
        if(!radii.empty()){auto mid=radii.begin()+static_cast<std::ptrdiff_t>(radii.size()*8/10);std::nth_element(radii.begin(),mid,radii.end());radius_=std::max(.5,*mid*1.6);}
        eye_=center+V3{radius_*1.1,-radius_*.8,-radius_*1.7};forward_=unit(center-eye_);right_=unit(cross(forward_,{0,-1,0}));up_=cross(right_,forward_);
    }
    auto project=[&](V3 p,int &x,int &y){V3 q=p-eye_;double z=dot(q,forward_);if(z<radius_*.05)return false;double xx=1016+420*dot(q,right_)/z,yy=345-420*dot(q,up_)/z;
        if(!std::isfinite(xx)||!std::isfinite(yy)||xx<780||xx>1250||yy<124||yy>525)return false;x=static_cast<int>(xx);y=static_cast<int>(yy);return true;};
    if(!same_cloud){
        constexpr unsigned w=471,h=402;
        cloud_background_.assign(w*h,panel);profile_.background_builds=1;
        unsigned stride=static_cast<unsigned>(std::max<std::size_t>(1,cloud.size()/5000));
        if(dense_environment_.empty()){
            for(unsigned i=0;i<cloud.size();i+=stride){int x,y;if(project(cloud[i].xyz,x,y))cloud_background_[unsigned(y-124)*w+unsigned(x-780)]=cloud[i].observations>5?cyan:muted;}
        }else {
            // Static environment projects once. Sparse geometry still defines
            // this view and all localization inputs; dense points never reach SLAM.
            std::vector<double> depth(w*h,std::numeric_limits<double>::infinity());
            for(const auto &p:dense_environment_){V3 v{p.x,p.y,p.z};int x,y;if(!project(v,x,y))continue;
                unsigned at=unsigned(y-124)*w+unsigned(x-780);double z=dot(v-eye_,forward_);
                if(z<depth[at]){depth[at]=z;cloud_background_[at]=uint16_t((p.r>>3)<<11|(p.g>>2)<<5|(p.b>>3));}}
        }
        cloud_cache_=cloud;cloud_valid_=true;
    }else profile_.background_hits=1;
    // A contiguous row copy is also the eraser for the previous live overlays.
    // This preserves exact RGB565 pixels and avoids per-point bounds checks.
    for(unsigned y=0;y<402;y++)std::copy_n(cloud_background_.data()+y*471,471,pixels.data()+(y+124)*width+780);
    const auto &trajectory=scene.trajectory;int old_x=0,old_y=0;bool previous=false;
    for(const auto &p:trajectory){int x=0,y=0;bool visible=false;
        if(!trajectory_pixels_.empty()){
            auto &entry=trajectory_pixels_[p.frame&(trajectory_slots_-1)];
            if(entry.generation==projection_generation_&&entry.frame==p.frame&&entry.stamp==p.timestamp_ns&&entry.valid==p.valid&&entry.center.x==p.center.x&&entry.center.y==p.center.y&&entry.center.z==p.center.z){profile_.trajectory_hits++;}
            else {
                profile_.trajectory_misses++;entry.generation=projection_generation_;entry.frame=p.frame;entry.stamp=p.timestamp_ns;entry.center=p.center;entry.valid=p.valid;
                entry.visible=p.valid&&project(p.center,entry.x,entry.y);
            }
            x=entry.x;y=entry.y;visible=entry.visible;
        }else {profile_.trajectory_misses++;visible=p.valid&&project(p.center,x,y);}
        if(visible){if(previous)line(old_x,old_y,x,y,green);old_x=x;old_y=y;previous=true;}else previous=false;
    }
    if(s.pose_valid){Pose twc=s.tcw.inverse();V3 origin=twc.t;std::array<V3,4> corners={{{-.18,-.12,.3},{.18,-.12,.3},{.18,.12,.3},{-.18,.12,.3}}};int ox,oy;
        if(project(origin,ox,oy))for(unsigned i=0;i<4;i++){int ax,ay,bx,by;V3 a=origin+twc.r*(corners[i]*radius_*.15),b=origin+twc.r*(corners[(i+1)%4]*radius_*.15);if(project(a,ax,ay)){line(ox,oy,ax,ay,yellow);if(project(b,bx,by))line(ax,ay,bx,by,yellow);}}}
    double labels_start=threadCpuMs();profile_.geometry_cpu_ms=labels_start-geometry_start;
    rect(784,540,464,100,bg);
    if(timing.preview){
        text(800,180,"CENTRE FOCUS SCORE",muted,2);text(800,215,format("",timing.focus_score),white,3);
        text(800,290,"ADJUST DISTANCE / FOCUS",cyan,2);text(800,330,"SHARP EDGES / FULL BOARD",muted,2);
        text(800,390,"HIGHER SCORE IS A GUIDE",muted,2);text(800,425,"CALIBRATE AFTER FOCUS",yellow,2);
        text(800,550,"FRAME "+std::to_string(frame.id),white,2);text(800,577,"SLAM DISABLED",yellow,2);text(800,606,"NO MAP / NO POSE",muted,2);
    }else {
        text(800,550,"LANDMARKS "+std::to_string(s.points)+"   KF "+std::to_string(s.keyframes),white,2);
        text(800,577,"FEATURES "+std::to_string(s.features)+"   INLIERS "+std::to_string(s.inliers),green,2);
        text(800,606,format("CORE MEMORY",double(scene.reserved_bytes)/(1024*1024),"MIB"),muted,2);
    }
    rect(16,672,1248,40,panel);text(28,684,format("FPS",timing.fps),timing.fps>=timing.target_fps?green:yellow,2);
    text(205,684,format(timing.preview?"CAP":"ORB",timing.preview?timing.capture_ms:timing.orb_ms,"MS"),muted,2);text(425,684,format(timing.preview?"SCREEN":"SLAM",timing.preview?timing.present_ms:timing.slam_ms,"MS"),muted,2);
    text(660,684,format("TOTAL",timing.total_ms,"MS"),muted,2);text(940,684,timing.preview?"Q QUIT / NO MAP OR POSE":"M MAP  L LOC  S SAVE  Q QUIT",white,1);
    profile_.labels_cpu_ms+=threadCpuMs()-labels_start;
}
void Dashboard::savePpm(const std::string &path)const{std::ofstream file(path,std::ios::binary);if(!file)throw std::runtime_error("Cannot create UI image");file<<"P6\n"<<width<<' '<<height<<"\n255\n";
    for(uint16_t p:pixels){unsigned char rgb[3]={static_cast<unsigned char>(((p>>11)&31)*255/31),static_cast<unsigned char>(((p>>5)&63)*255/63),static_cast<unsigned char>((p&31)*255/31)};file.write(reinterpret_cast<const char*>(rgb),3);}if(!file)throw std::runtime_error("UI image write failed");}
} // namespace zslam
