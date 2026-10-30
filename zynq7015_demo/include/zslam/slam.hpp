#pragma once
#include "math.hpp"
#include "spatial_bins.hpp"
#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace zslam {
constexpr unsigned max_features=1000;
// Fixed-map handoff bounds; independent of the PL feature budget per frame.
constexpr unsigned handoff_max_points=30000,handoff_max_keyframes=1024;
using Descriptor=std::array<uint8_t,32>;
unsigned hamming(const Descriptor&,const Descriptor&);
struct Feature {V2 raw,uv;Descriptor descriptor{};uint32_t level=0,score=0;};
struct Frame {uint64_t id=0,timestamp_ns=0;std::vector<Feature> features;};
class RecordDecodeCache;
Frame decodeRecords(const uint8_t*,std::size_t,uint64_t,uint64_t,const Camera&,RecordDecodeCache *cache=nullptr);
enum class State {Waiting,Initializing,Tracking,Lost,Relocalized};
const char *stateName(State);
struct Config {
    unsigned max_points=12000,max_keyframes=64,max_trajectory=4096;
    unsigned minimum_tracking=20,keyframe_interval=12,local_ba_iterations=2,max_new_points=80;
    unsigned relocalization_interval=3;
    double match_radius_px=24,mapping_budget_ms=4;
    bool mapping=true,precise_retrieval_invalidation=false;
    bool time_aware_motion=true,cached_retrieval_build=true;
};
struct Ref {unsigned slot=~0u,generation=0;};
struct PointView {V3 xyz;uint64_t id=0;unsigned observations=0;};
struct Status {
    State state=State::Waiting;bool pose_valid=false,mapping=true,recovery_attempted=false;
    Pose tcw;unsigned features=0,matches=0,inliers=0,points=0,keyframes=0,new_points=0;
    double track_ms=0,map_ms=0,match_ms=0,pose_ms=0,recovery_pose_ms=0;uint64_t frame=0,timestamp_ns=0,dropped=0;
    unsigned retrieval_builds=0,retrieval_queries=0;
    double retrieval_build_cpu_ms=0,retrieval_query_cpu_ms=0;
    unsigned local_matches=0,local_inliers=0,recovery_matches=0,recovery_inliers=0;
    double prediction_ratio=0;
};
struct TrackSample {uint64_t frame=0,timestamp_ns=0;V3 center;bool valid=false;};
class Slam {
public:
    explicit Slam(Camera camera={},Config config={});
    Status process(Frame frame);
    void setMapping(bool enabled){config_.mapping=enabled;}
    bool mapping()const{return config_.mapping;}
    void reset();
    void resetTracking(); // Preserve a fixed map when requesting relocalization.
    void save(const std::string&)const;
    void load(const std::string&);
    void importHandoff(const std::string&);
    std::vector<PointView> points()const;
    const std::vector<TrackSample>& trajectory()const{return trajectory_;}
    const Camera &camera()const{return camera_;}
    std::size_t reservedBytes()const;
private:
    friend struct RetrievalTestAccess;
    struct Sight {uint64_t key=0;unsigned feature=0;};
    struct Landmark {
        V3 xyz;Descriptor descriptor{};uint64_t id=0,last_seen=0;unsigned generation=1,seen=0;
        bool active=false,fixed=false;std::array<Sight,8> sights{};unsigned sight_count=0;
    };
    struct Keyframe {uint64_t id=0,frame=0;Pose tcw;std::vector<Feature> features;std::vector<Ref> refs;bool anchor=false;};
    Camera camera_;Config config_;std::vector<Landmark> map_;std::vector<Keyframe> keys_;
    std::vector<TrackSample> trajectory_;Frame seed_;Pose previous_,current_;bool valid_=false,have_previous_=false;
    uint64_t last_frame_=0,last_timestamp_=0,next_point_=1,next_key_=1;bool have_identity_=false;unsigned frames_since_key_=0,ba_point_cursor_=0;
    uint64_t previous_pose_timestamp_=0,current_pose_timestamp_=0;
    unsigned recovery_failures_=0,recovery_wait_=0;
    std::vector<Ref> associations_;
    mutable bool retrieval_valid_=false;
    mutable std::vector<Descriptor> retrieval_descriptors_;
    mutable std::vector<unsigned> retrieval_slots_,retrieval_heads_,retrieval_links_;
    mutable std::array<unsigned,160> retrieval_bits_{};
    mutable std::vector<uint16_t> retrieval_hashes_;
    mutable std::array<unsigned,1024> retrieval_cursor_{};
    mutable SpatialBins tracking_bins_;
    mutable std::vector<V2> tracking_projected_;
    bool alive(Ref)const;
    Ref addPoint(V3,const Descriptor&,uint64_t);
    void observe(Ref,Keyframe&,unsigned);
    void updateDescriptor(Ref);
    unsigned addKeyframe(const Frame&,Pose,std::vector<Ref>,bool anchor=false);
    std::vector<std::pair<unsigned,unsigned>> matchFrames(const std::vector<Feature>&,const std::vector<Feature>&,double radius=0)const;
    std::vector<Observation> matchMap(const Frame&,Pose,bool global,Status *profile=nullptr)const;
    bool recover(const Frame&,Pose&,std::vector<Observation>&,std::vector<unsigned>&,Status&)const;
    void mapFrame(const Frame&,Status&);
    void bundleAdjust(double budget_ms);
    void appendTrajectory(const Status&);
};
} // namespace zslam
