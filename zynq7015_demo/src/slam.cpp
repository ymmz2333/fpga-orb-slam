#include "zslam/slam.hpp"
#include "zslam/formats.hpp"
#include "zslam/profiling.hpp"
#include "zslam/motion.hpp"
#include <chrono>
#include <cstring>
#include <stdexcept>
#if defined(__ARM_NEON)
#include <arm_neon.h>
#endif

namespace zslam {
namespace {
using Clock=std::chrono::steady_clock;
double ms(Clock::time_point start){return std::chrono::duration<double,std::milli>(Clock::now()-start).count();}
struct Match {unsigned a,b,d;};
bool ratio(unsigned best,unsigned second){return best<=64&&best*5<second*4;}
#if defined(__GNUC__)
__attribute__((always_inline))
#endif
inline unsigned descriptorDistance(const Descriptor &a,const Descriptor &b){
#if defined(__ARM_NEON)
    uint8x16_t x=vcntq_u8(veorq_u8(vld1q_u8(a.data()),vld1q_u8(b.data()))),y=vcntq_u8(veorq_u8(vld1q_u8(a.data()+16),vld1q_u8(b.data()+16)));
    uint16x8_t s=vpaddlq_u8(vaddq_u8(x,y));uint32x4_t t=vpaddlq_u16(s);
    uint32x2_t u=vadd_u32(vget_low_u32(t),vget_high_u32(t));return vget_lane_u32(vpadd_u32(u,u),0);
#else
    unsigned n=0;for(unsigned i=0;i<32;i+=4){uint32_t x,y;std::memcpy(&x,a.data()+i,4);std::memcpy(&y,b.data()+i,4);n+=static_cast<unsigned>(__builtin_popcount(x^y));}return n;
#endif
}
}
unsigned hamming(const Descriptor &a,const Descriptor &b){return descriptorDistance(a,b);}
const char *stateName(State s){switch(s){case State::Waiting:return "WAITING";case State::Initializing:return "INITIALIZING";case State::Tracking:return "TRACKING";case State::Lost:return "LOST";case State::Relocalized:return "RELOCALIZED";}return "INVALID";}
Slam::Slam(Camera c,Config config):camera_(c),config_(config){
    if(!config.relocalization_interval||config.relocalization_interval>30)throw std::runtime_error("Invalid bounded recovery interval");
    if(config.max_points<80||config.max_points>50000||config.max_keyframes<4||config.max_keyframes>handoff_max_keyframes||config.max_trajectory<2||config.max_trajectory>100000||config.minimum_tracking<8||config.minimum_tracking>1000||!config.keyframe_interval||config.local_ba_iterations>5||!std::isfinite(config.match_radius_px)||config.match_radius_px<1||config.match_radius_px>128||!std::isfinite(config.mapping_budget_ms)||config.mapping_budget_ms<0||config.mapping_budget_ms>20)throw std::runtime_error("Invalid bounded SLAM configuration");
    if(c.width!=960||c.height!=720||c.fx<=0||c.fy<=0)throw std::runtime_error("ORB contract requires 960x720 calibration");
    map_.resize(config.max_points);keys_.reserve(config.max_keyframes);trajectory_.reserve(config.max_trajectory);associations_.reserve(max_features);
    if(config.cached_retrieval_build)retrieval_hashes_.reserve(config.max_points);
}
bool Slam::alive(Ref r)const{return r.slot<map_.size()&&map_[r.slot].active&&map_[r.slot].generation==r.generation;}
Ref Slam::addPoint(V3 xyz,const Descriptor &desc,uint64_t frame){
    if(!config_.precise_retrieval_invalidation)retrieval_valid_=false;
    unsigned slot=~0u;uint64_t oldest=~uint64_t(0);
    for(unsigned i=0;i<map_.size();i++)if(!map_[i].active){slot=i;break;}
    else if(!map_[i].fixed&&map_[i].last_seen+90<frame&&map_[i].last_seen<oldest){oldest=map_[i].last_seen;slot=i;}
    if(slot==~0u)return {};
    // The index contains active descriptors and slots, not insertion attempts.
    // Preserve it if capacity prevents an insertion without changing the map.
    retrieval_valid_=false;
    auto &p=map_[slot];unsigned generation=p.generation+1;p=Landmark{};p.active=true;p.xyz=xyz;p.descriptor=desc;p.generation=generation;p.id=next_point_++;p.last_seen=frame;p.seen=1;return {slot,generation};
}
void Slam::observe(Ref r,Keyframe &k,unsigned feature){
    if(!alive(r)||feature>=k.features.size())return;auto &p=map_[r.slot];k.refs[feature]=r;
    for(unsigned i=0;i<p.sight_count;i++)if(p.sights[i].key==k.id)return;
    if(p.sight_count==p.sights.size()){std::move(p.sights.begin()+1,p.sights.end(),p.sights.begin());p.sight_count--;}
    p.sights[p.sight_count++]={k.id,feature};
}
void Slam::updateDescriptor(Ref ref){
    if(!alive(ref)||map_[ref.slot].fixed)return;auto &point=map_[ref.slot];
    std::array<const Descriptor*,8> choices{};unsigned count=0;
    for(unsigned i=0;i<point.sight_count;i++){
        const auto &sight=point.sights[i];auto key=std::find_if(keys_.begin(),keys_.end(),[&](const Keyframe &k){return k.id==sight.key;});
        if(key!=keys_.end()&&sight.feature<key->features.size())choices[count++]=&key->features[sight.feature].descriptor;
    }
    if(count<2)return;unsigned best=257,selected=0;
    for(unsigned i=0;i<count;i++){
        std::array<unsigned,8> distances{};unsigned n=0;
        for(unsigned j=0;j<count;j++)if(i!=j)distances[n++]=descriptorDistance(*choices[i],*choices[j]);
        std::sort(distances.begin(),distances.begin()+n);unsigned median=distances[n/2];
        if(median<=best){best=median;selected=i;}
    }
    if(!config_.precise_retrieval_invalidation||point.descriptor!=*choices[selected]){
        point.descriptor=*choices[selected];retrieval_valid_=false;
    }
}
unsigned Slam::addKeyframe(const Frame &f,Pose pose,std::vector<Ref> refs,bool anchor){
    if(keys_.size()==config_.max_keyframes){
        auto it=std::find_if(keys_.begin(),keys_.end()-2,[](const Keyframe &k){return !k.anchor;});
        if(it==keys_.end()-2)return ~0u;uint64_t removed=it->id;
        for(auto &p:map_){unsigned n=0;for(unsigned i=0;i<p.sight_count;i++)if(p.sights[i].key!=removed)p.sights[n++]=p.sights[i];p.sight_count=n;}
        keys_.erase(it);
    }
    Keyframe key;key.id=next_key_++;key.frame=f.id;key.tcw=pose;key.features=f.features;key.refs=std::move(refs);key.refs.resize(f.features.size());key.anchor=anchor;
    keys_.push_back(std::move(key));auto &stored=keys_.back();for(unsigned i=0;i<stored.refs.size();i++)observe(stored.refs[i],stored,i);
    frames_since_key_=0;return static_cast<unsigned>(keys_.size()-1);
}
std::vector<std::pair<unsigned,unsigned>> Slam::matchFrames(const std::vector<Feature> &a,const std::vector<Feature> &b,double radius)const{
    SpatialBins bins;if(radius>0)bins.build(static_cast<unsigned>(b.size()),[&](unsigned j){return b[j].uv;});
    std::vector<Match> candidates;for(unsigned i=0;i<a.size();i++){
        unsigned best=257,second=257,which=0;
        auto consider=[&](unsigned j){if(std::abs(static_cast<int>(a[i].level)-static_cast<int>(b[j].level))>1)return;
            unsigned d=descriptorDistance(a[i].descriptor,b[j].descriptor);if(d<best){second=best;best=d;which=j;}else if(d<second)second=d;};
        if(radius<=0){for(unsigned j=0;j<b.size();j++)consider(j);}
        else {
            // Coordinates inside these image bins are bounded. Squared distance
            // avoids a libm hypot call for every possible keyframe pair.
            bins.visit(a[i].uv,radius,[&](unsigned j){
                double dx=a[i].uv.x-b[j].uv.x,dy=a[i].uv.y-b[j].uv.y;
                if(dx*dx+dy*dy<=radius*radius)consider(j);
            });
        }
        if(ratio(best,second))candidates.push_back({i,which,best});
    }
    std::sort(candidates.begin(),candidates.end(),[](const Match &x,const Match &y){return x.d!=y.d?x.d<y.d:(x.b!=y.b?x.b<y.b:x.a<y.a);});
    std::vector<bool> used(b.size());std::vector<std::pair<unsigned,unsigned>> result;
    for(const auto &m:candidates)if(!used[m.b]){used[m.b]=true;result.emplace_back(m.a,m.b);}return result;
}
std::vector<Observation> Slam::matchMap(const Frame &f,Pose prediction,bool global,Status *profile)const{
    // Projected landmarks enter fixed spatial bins; tracking compares local descriptors only.
    // A landmark includes observation history. Scanning that sparse structure
    // per feature evicts the Cortex-A9 cache; pack just active descriptors once.
    // Multi-table descriptor retrieval for recovery. Exact 256-bit distances,
    // ratio filtering and geometric RANSAC still decide the returned matches.
    // Approximate retrieval can miss neighbors; it never creates a valid pose.
    constexpr unsigned tables=16,bits=10,buckets=1u<<bits;
    auto hash=[&](const Descriptor &d,unsigned table){unsigned result=0;
        for(unsigned k=0;k<bits;k++){unsigned bit=retrieval_bits_[table*bits+k];result|=unsigned((d[bit/8]>>(bit%8))&1)<<k;}return result;};
    const bool multiview=config_.fixed_map_multiview&&!config_.mapping;
    if(retrieval_multiview_!=multiview)retrieval_valid_=false;
    if((global||multiview)&&!retrieval_valid_){
        const double build_start=profile?threadCpuMs():0;
        retrieval_descriptors_.clear();retrieval_slots_.clear();
        retrieval_offsets_.resize(map_.size()+1);
        for(unsigned j=0;j<map_.size();j++){
            retrieval_offsets_[j]=static_cast<unsigned>(retrieval_descriptors_.size());
            if(!map_[j].active)continue;
            retrieval_descriptors_.push_back(map_[j].descriptor);retrieval_slots_.push_back(j);
            if(multiview&&map_[j].fixed)for(unsigned v=0;v<map_[j].sight_count;v++){
                const auto &s=map_[j].sights[v];
                auto key=std::find_if(keys_.begin(),keys_.end(),[&](const Keyframe &k){return k.id==s.key;});
                if(key==keys_.end()||s.feature>=key->features.size()||!alive(key->refs[s.feature])||key->refs[s.feature].slot!=j)continue;
                const auto &d=key->features[s.feature].descriptor;
                if(std::find(retrieval_descriptors_.begin()+retrieval_offsets_[j],retrieval_descriptors_.end(),d)!=retrieval_descriptors_.end())continue;
                retrieval_descriptors_.push_back(d);retrieval_slots_.push_back(j);
            }
        }
        retrieval_offsets_[map_.size()]=static_cast<unsigned>(retrieval_descriptors_.size());
        std::array<unsigned,256> ones{},order{};
        for(unsigned bit=0;bit<256;bit++)order[bit]=bit;
        if(config_.cached_retrieval_build){
            for(const auto &d:retrieval_descriptors_)for(unsigned byte=0;byte<32;byte++)
                for(unsigned bit=0;bit<8;bit++)ones[byte*8+bit]+=(d[byte]>>bit)&1;
        }else for(unsigned bit=0;bit<256;bit++)for(const auto &d:retrieval_descriptors_)ones[bit]+=(d[bit/8]>>(bit%8))&1;
        std::sort(order.begin(),order.end(),[&](unsigned a,unsigned b){
            auto score=[&](unsigned bit){return std::abs(2*static_cast<int>(ones[bit])-static_cast<int>(retrieval_descriptors_.size()));};
            return score(a)!=score(b)?score(a)<score(b):a<b;});
        for(unsigned t=0;t<tables;t++)for(unsigned k=0;k<bits;k++)retrieval_bits_[t*bits+k]=order[(t*17+k*23)%128];
        retrieval_heads_.assign(tables*(buckets+1),0);retrieval_links_.resize(tables*retrieval_descriptors_.size());
        if(config_.cached_retrieval_build)retrieval_hashes_.resize(retrieval_descriptors_.size());
        for(unsigned t=0;t<tables;t++){
            unsigned *offsets=retrieval_heads_.data()+t*(buckets+1);
            for(unsigned j=0;j<retrieval_descriptors_.size();j++){
                unsigned code=hash(retrieval_descriptors_[j],t);offsets[code+1]++;
                if(config_.cached_retrieval_build)retrieval_hashes_[j]=static_cast<uint16_t>(code);
            }
            for(unsigned bucket=1;bucket<=buckets;bucket++)offsets[bucket]+=offsets[bucket-1];
            std::copy(offsets,offsets+buckets,retrieval_cursor_.begin());
            for(unsigned j=0;j<retrieval_descriptors_.size();j++){
                unsigned code=config_.cached_retrieval_build?retrieval_hashes_[j]:hash(retrieval_descriptors_[j],t);
                retrieval_links_[t*retrieval_descriptors_.size()+retrieval_cursor_[code]++]=j;
            }
        }
        retrieval_valid_=true;retrieval_multiview_=multiview;
        if(profile){profile->retrieval_builds++;profile->retrieval_build_cpu_ms+=threadCpuMs()-build_start;}
    }
    const double query_start=global&&profile?threadCpuMs():0;
    std::vector<unsigned> visited(global?retrieval_descriptors_.size():0);
    if(!global){tracking_projected_.resize(map_.size());tracking_bins_.build(static_cast<unsigned>(map_.size()),[&](unsigned i){
        if(!map_[i].active)return V2{-1,-1};V3 p=prediction.apply(map_[i].xyz);if(p.z<=1e-6)return V2{-1,-1};
        return tracking_projected_[i]=camera_.project(p);
    });}
    std::vector<Match> candidates;
    for(unsigned i=0;i<f.features.size();i++){
        unsigned best=257,second=257,which=0;const auto &feature=f.features[i];
        auto consider=[&](unsigned j){
            unsigned d=257;
            if(multiview)for(unsigned view=retrieval_offsets_[j];view<retrieval_offsets_[j+1];view++)d=std::min(d,descriptorDistance(feature.descriptor,retrieval_descriptors_[view]));
            else d=descriptorDistance(feature.descriptor,map_[j].descriptor);
            if(d<best){second=best;best=d;which=j;}else if(d<second)second=d;
        };
        if(global){for(unsigned t=0;t<tables;t++){
            unsigned code=hash(feature.descriptor,t);
            // Exact buckets from every table; one-bit probes from four diverse
            // tables. Ignore very common buckets, which carry little identity.
            for(unsigned neighbor=0;neighbor<=(t%4==0?bits:0u);neighbor++){
                unsigned bucket=code^(neighbor==0?0:1u<<(neighbor-1));
                unsigned begin=retrieval_heads_[t*(buckets+1)+bucket],end=retrieval_heads_[t*(buckets+1)+bucket+1];
                if(end-begin>std::max(32u,static_cast<unsigned>(retrieval_descriptors_.size()/32)))continue;
                for(unsigned entry=begin;entry<end;entry++){
                    unsigned j=retrieval_links_[t*retrieval_descriptors_.size()+entry];
                    if(visited[j]==i+1)continue;visited[j]=i+1;unsigned d=descriptorDistance(feature.descriptor,retrieval_descriptors_[j]);
                    unsigned slot=retrieval_slots_[j];
                    // Two observations of one landmark are not competitors in
                    // the ratio test, whose second choice is another landmark.
                    if(multiview&&slot==which)best=std::min(best,d);
                    else if(d<best){second=best;best=d;which=slot;}else if(d<second)second=d;
                }
            }
        }}
        else {double radius=config_.match_radius_px;
            tracking_bins_.visit(feature.uv,radius,[&](unsigned j){
                double px=tracking_projected_[j].x-feature.uv.x,py=tracking_projected_[j].y-feature.uv.y;if(px*px+py*py<=radius*radius)consider(j);
            });
        }
        if(ratio(best,second))candidates.push_back({i,which,best});
    }
    std::sort(candidates.begin(),candidates.end(),[](const Match &a,const Match &b){return a.d!=b.d?a.d<b.d:(a.b!=b.b?a.b<b.b:a.a<b.a);});
    std::vector<bool> used(map_.size());std::vector<Observation> result;
    for(const auto &m:candidates)if(!used[m.b]){used[m.b]=true;result.push_back({map_[m.b].xyz,f.features[m.a].uv,m.a,m.b});}
    if(global&&profile){profile->retrieval_queries++;profile->retrieval_query_cpu_ms+=threadCpuMs()-query_start;}
    return result;
}
bool Slam::recover(const Frame &f,Pose &pose,std::vector<Observation> &obs,std::vector<unsigned> &keep,Status &status)const{
    auto start=Clock::now();obs=matchMap(f,pose,true,&status);status.match_ms+=ms(start);
    status.recovery_matches=static_cast<unsigned>(obs.size());
    if(obs.size()<config_.minimum_tracking)return false;
    start=Clock::now();bool okay=robustPose(camera_,obs,pose,keep,config_.minimum_tracking,static_cast<unsigned>(f.id)+1729);
    status.recovery_pose_ms=ms(start);status.recovery_inliers=static_cast<unsigned>(keep.size());return okay;
}
void Slam::appendTrajectory(const Status &s){if(trajectory_.size()==config_.max_trajectory)trajectory_.erase(trajectory_.begin());trajectory_.push_back({s.frame,s.timestamp_ns,s.pose_valid?s.tcw.center():V3{},s.pose_valid});}
Status Slam::process(Frame f){
    if(!f.timestamp_ns||f.features.size()>max_features||(have_identity_&&(f.id<=last_frame_||f.timestamp_ns<=last_timestamp_)))throw std::runtime_error("Non-monotonic frame identity or invalid frame size");
    for(const auto &feature:f.features)if(feature.level>=8||!std::isfinite(feature.uv.x)||!std::isfinite(feature.uv.y)||!std::isfinite(feature.raw.x)||!std::isfinite(feature.raw.y))throw std::runtime_error("Invalid feature geometry");
    Status status;status.frame=f.id;status.timestamp_ns=f.timestamp_ns;status.features=static_cast<unsigned>(f.features.size());status.mapping=config_.mapping;
    if(have_identity_)status.dropped=f.id-last_frame_-1;last_frame_=f.id;last_timestamp_=f.timestamp_ns;have_identity_=true;
    auto start=Clock::now();associations_.assign(f.features.size(),Ref{});
    bool has_map=std::any_of(map_.begin(),map_.end(),[](const Landmark &p){return p.active;});
    if(!has_map){
        status.state=State::Initializing;
        if(!config_.mapping){status.state=State::Waiting;}
        else if(seed_.features.empty()){if(f.features.size()>=60)seed_=f;}
        else {
            auto matches=matchFrames(seed_.features,f.features);status.matches=static_cast<unsigned>(matches.size());std::vector<V2>a,b;
            for(auto m:matches){a.push_back(seed_.features[m.first].uv);b.push_back(f.features[m.second].uv);}
            Pose second;std::vector<unsigned> accepted;std::vector<V3> xyz;
            if(initializeTwoViews(camera_,a,b,second,accepted,xyz,static_cast<unsigned>(f.id)+1729)){
                std::vector<Ref> first(seed_.features.size()),last(f.features.size());
                for(unsigned i=0;i<accepted.size();i++){auto m=matches[accepted[i]];Ref r=addPoint(xyz[i],seed_.features[m.first].descriptor,f.id);first[m.first]=last[m.second]=r;}
                addKeyframe(seed_,Pose{},std::move(first),true);addKeyframe(f,second,last,true);associations_=std::move(last);current_=second;previous_=Pose{};valid_=true;have_previous_=false;current_pose_timestamp_=f.timestamp_ns;previous_pose_timestamp_=0;
                status.state=State::Tracking;status.pose_valid=true;status.tcw=current_;status.inliers=static_cast<unsigned>(accepted.size());status.new_points=status.inliers;seed_=Frame{};
            }else if(f.features.size()>=60&&(matches.size()<60||f.features.size()>seed_.features.size()*2||f.id-seed_.id>90))seed_=f;
        }
    }else {
        Pose estimate=current_;
        if(valid_&&have_previous_){
            if(!config_.time_aware_motion){estimate=(current_*previous_.inverse())*current_;status.prediction_ratio=1;}
            else if(previous_pose_timestamp_&&current_pose_timestamp_>previous_pose_timestamp_&&f.timestamp_ns>current_pose_timestamp_){
                uint64_t history=current_pose_timestamp_-previous_pose_timestamp_,horizon=f.timestamp_ns-current_pose_timestamp_;
                double ratio=double(horizon)/double(history);Pose extrapolated;
                // Do not extrapolate stale/unbounded velocity across long gaps.
                if(history<=250000000&&horizon<=250000000&&scaleRigidMotion(current_*previous_.inverse(),ratio,extrapolated)){
                    estimate=extrapolated*current_;status.prediction_ratio=ratio;
                }
            }
        }
        auto stage=Clock::now();auto obs=valid_?matchMap(f,estimate,false):std::vector<Observation>{};std::vector<unsigned> keep;status.match_ms=ms(stage);
        status.local_matches=static_cast<unsigned>(obs.size());
        stage=Clock::now();
        bool tracked=valid_&&optimizePose(camera_,obs,estimate,keep,config_.minimum_tracking);
        status.local_inliers=static_cast<unsigned>(keep.size());
        status.pose_ms=ms(stage);
        if(!tracked){
            estimate=current_;
            if(recovery_failures_<3||!recovery_wait_){
                status.recovery_attempted=true;tracked=recover(f,estimate,obs,keep,status);
                if(!tracked){recovery_failures_=std::min(3u,recovery_failures_+1);recovery_wait_=config_.relocalization_interval-1;}
            }else recovery_wait_--;
            status.state=tracked?State::Relocalized:State::Lost;have_previous_=false;
        }
        else status.state=State::Tracking;
        status.matches=static_cast<unsigned>(obs.size());status.inliers=static_cast<unsigned>(keep.size());status.pose_valid=tracked;
        if(tracked){recovery_failures_=recovery_wait_=0;previous_=current_;previous_pose_timestamp_=current_pose_timestamp_;current_=estimate;current_pose_timestamp_=f.timestamp_ns;have_previous_=valid_&&status.state==State::Tracking;valid_=true;status.tcw=current_;
            for(unsigned i:keep){auto &p=map_[obs[i].landmark];p.last_seen=f.id;p.seen++;associations_[obs[i].feature]={obs[i].landmark,p.generation};}
            frames_since_key_++;
        }else valid_=false;
    }
    status.track_ms=ms(start);
    unsigned reference_support=0;if(!keys_.empty())for(Ref r:keys_.back().refs)if(alive(r))reference_support++;
    bool needs_key=frames_since_key_>=config_.keyframe_interval||(frames_since_key_>=2&&status.inliers*2<reference_support);
    if(status.pose_valid&&config_.mapping&&needs_key){auto begin=Clock::now();mapFrame(f,status);status.map_ms=ms(begin);status.tcw=current_;}
    for(const auto &p:map_)if(p.active)status.points++;status.keyframes=static_cast<unsigned>(keys_.size());appendTrajectory(status);return status;
}
void Slam::mapFrame(const Frame &f,Status &status){
    if(keys_.empty())return;const auto &reference=keys_.back();
    double baseline=norm(current_.center()-reference.tcw.center());if(baseline<1e-5)return;
    auto matches=matchFrames(reference.features,f.features,config_.match_radius_px*3);unsigned old_index=static_cast<unsigned>(keys_.size()-1);
    unsigned new_index=addKeyframe(f,current_,associations_);if(new_index==~0u)return;
    // Insertion may remove an old keyframe; find the previous newest by stable frame identity.
    old_index=new_index-1;auto &old=keys_[old_index];auto &now=keys_[new_index];
    for(auto m:matches){if(status.new_points>=config_.max_new_points)break;
        if(alive(old.refs[m.first])){V3 q=now.tcw.apply(map_[old.refs[m.first].slot].xyz);if(!alive(now.refs[m.second])&&q.z>1e-6&&distance(camera_.project(q),now.features[m.second].uv)<4)observe(old.refs[m.first],now,m.second);continue;}
        if(alive(now.refs[m.second]))continue;V3 point;
        if(triangulate(camera_,old.tcw,now.tcw,old.features[m.first].uv,now.features[m.second].uv,point,1.0)){
            Ref r=addPoint(point,now.features[m.second].descriptor,f.id);if(alive(r)){observe(r,old,m.first);observe(r,now,m.second);associations_[m.second]=r;status.new_points++;}}
    }
    for(Ref ref:now.refs)updateDescriptor(ref);
    bundleAdjust(config_.mapping_budget_ms);current_=keys_.back().tcw;have_previous_=false;
}
void Slam::bundleAdjust(double budget_ms){
    if(budget_ms<=0)return;auto started=Clock::now();
    unsigned begin=keys_.size()>5?static_cast<unsigned>(keys_.size()-5):0;
    for(unsigned iteration=0;iteration<config_.local_ba_iterations;iteration++){
        for(unsigned k=begin;k<keys_.size();k++)if(!keys_[k].anchor){if(ms(started)>=budget_ms)return;auto &key=keys_[k];std::vector<Observation> obs;
            unsigned stride=1+static_cast<unsigned>(key.refs.size()/160);
            for(unsigned i=0;i<key.refs.size();i+=stride)if(alive(key.refs[i]))obs.push_back({map_[key.refs[i].slot].xyz,key.features[i].uv,i,key.refs[i].slot});
            std::vector<unsigned> keep;Pose trial=key.tcw;if(optimizePose(camera_,obs,trial,keep,config_.minimum_tracking,1))key.tcw=trial;}
        unsigned optimized=0;
        for(unsigned visited=0;visited<map_.size();visited++){if(ms(started)>=budget_ms||optimized>=128)return;auto &point=map_[ba_point_cursor_++%map_.size()];if(point.active&&!point.fixed&&point.sight_count>=2){optimized++;
            double h[9]={},b[3]={},cost=0;unsigned used=0;V3 original=point.xyz;
            for(unsigned n=0;n<point.sight_count;n++){const auto &s=point.sights[n];auto it=std::find_if(keys_.begin(),keys_.end(),[&](const Keyframe &k){return k.id==s.key;});
                if(it==keys_.end()||it->frame<keys_[begin].frame||s.feature>=it->features.size())continue;V3 q=it->tcw.apply(point.xyz);if(q.z<=1e-6)continue;
                V2 uv=camera_.project(q),observed=it->features[s.feature].uv;double residual[2]={observed.x-uv.x,observed.y-uv.y},error=std::hypot(residual[0],residual[1]);if(error>8)continue;
                double j[2][3]={},p[2][3]={{camera_.fx/q.z,0,-camera_.fx*q.x/(q.z*q.z)},{0,camera_.fy/q.z,-camera_.fy*q.y/(q.z*q.z)}};
                for(int r=0;r<2;r++)for(int c=0;c<3;c++)for(int k=0;k<3;k++)j[r][c]+=p[r][k]*it->tcw.r(k,c);
                double w=error<3?1.:3/error;for(int r=0;r<3;r++){for(int k=0;k<2;k++)b[r]+=w*j[k][r]*residual[k];for(int c=0;c<3;c++)for(int k=0;k<2;k++)h[r*3+c]+=w*j[k][r]*j[k][c];}cost+=error*error;used++;
            }
            if(used<2)continue;for(int i=0;i<3;i++)h[3*i+i]+=1e-5;double delta[3]={};if(!solve(h,b,delta,3))continue;
            V3 trial=original+V3{delta[0],delta[1],delta[2]};if(!finite(trial)||norm(trial-original)>.1*std::max(1.,norm(original)))continue;
            double next=0;unsigned tested=0;bool positive=true;
            for(unsigned n=0;n<point.sight_count;n++){const auto &s=point.sights[n];auto it=std::find_if(keys_.begin(),keys_.end(),[&](const Keyframe &k){return k.id==s.key;});if(it==keys_.end()||it->frame<keys_[begin].frame||s.feature>=it->features.size())continue;
                V3 q=it->tcw.apply(trial);double old_error=distance(camera_.project(it->tcw.apply(original)),it->features[s.feature].uv);if(old_error>8)continue;
                if(q.z<=1e-6){positive=false;break;}double e=distance(camera_.project(q),it->features[s.feature].uv);next+=e*e;tested++;}
            if(positive&&tested==used&&next<cost)point.xyz=trial;
        }}
    }
}
std::vector<PointView> Slam::points()const{std::vector<PointView> result;result.reserve(map_.size());for(const auto &p:map_)if(p.active)result.push_back({p.xyz,p.id,p.seen});return result;}
std::size_t Slam::reservedBytes()const{std::size_t n=map_.capacity()*sizeof(Landmark)+trajectory_.capacity()*sizeof(TrackSample)+keys_.capacity()*sizeof(Keyframe);
    n+=retrieval_descriptors_.capacity()*sizeof(Descriptor)+(retrieval_slots_.capacity()+retrieval_heads_.capacity()+retrieval_links_.capacity())*sizeof(unsigned);
    n+=retrieval_offsets_.capacity()*sizeof(unsigned);
    n+=tracking_bins_.reservedBytes()+tracking_projected_.capacity()*sizeof(V2);
    n+=retrieval_hashes_.capacity()*sizeof(uint16_t)+sizeof(retrieval_cursor_);
    for(const auto &k:keys_)n+=k.features.capacity()*sizeof(Feature)+k.refs.capacity()*sizeof(Ref);return n;}
void Slam::resetTracking(){valid_=have_previous_=false;previous_pose_timestamp_=current_pose_timestamp_=0;recovery_failures_=recovery_wait_=0;trajectory_.clear();}
void Slam::reset(){for(auto &p:map_){p.active=false;p.fixed=false;p.generation++;p.sight_count=0;}retrieval_valid_=false;keys_.clear();seed_=Frame{};resetTracking();have_identity_=false;current_=previous_=Pose{};frames_since_key_=0;}
} // namespace zslam
