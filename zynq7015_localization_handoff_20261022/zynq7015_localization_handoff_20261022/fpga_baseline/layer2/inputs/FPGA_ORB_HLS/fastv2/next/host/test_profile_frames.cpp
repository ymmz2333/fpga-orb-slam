/* Host-only timing-contract/overhead experiment; never an ARM/FPGA FPS result. */
#include "next_backend_profile.h"
#include "next_frame_stats.h"
#include "golden.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>
/** @brief Reject failures in Release builds as well. */
static void require(bool valid,const char* message) {
    if (!valid) throw std::runtime_error(message);
}
/** @brief Read monotonic host nanoseconds, not ARM cycles. */
static uint64_t now_ns() {
    return uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count());
}
/** @brief Count profile reads and supply the same real host clock to every stage. */
static uint64_t host_clock(void* context) {
    ++*static_cast<uint64_t*>(context);
    return now_ns();
}
/** @brief Check percentile ranks, small/tied/zero samples and overflow rejection. */
static void test_stats() {
    std::array<uint64_t,1000> samples{},scratch{};
    for (uint32_t i=0;i<1000;++i) samples[i]=1000-i;
    const auto before=samples;
    NextFrameStats result{};
    require(next_frame_stats(samples.data(),1000,scratch.data(),&result)==0 &&
        result.count==1000 && result.total==500500 && result.minimum==1 &&
        result.maximum==1000 && result.p95==950 && result.p99==990 && samples==before,
        "1000-frame nearest-rank statistics mismatch");
    for (uint32_t count : {1u,2u,3u,100u}) {
        samples.fill(7);
        require(next_frame_stats(samples.data(),count,scratch.data(),&result)==0 &&
            result.total==count*7u && result.minimum==7 && result.maximum==7 &&
            result.p95==7 && result.p99==7,"Small/tied statistics mismatch");
    }
    samples.fill(0);
    require(next_frame_stats(samples.data(),100,scratch.data(),&result)==0 && result.p99==0,
        "Zero tick statistics mismatch");
    const auto rejected=result;
    require(next_frame_stats(nullptr,1,scratch.data(),&result)==-1 &&
        next_frame_stats(samples.data(),0,scratch.data(),&result)==-1 &&
        next_frame_stats(samples.data(),1001,scratch.data(),&result)==-1 &&
        next_frame_stats(samples.data(),1,nullptr,&result)==-1 &&
        next_frame_stats(samples.data(),1,scratch.data(),nullptr)==-1,"Invalid arguments accepted");
    samples[0]=UINT64_MAX; samples[1]=1;
    require(next_frame_stats(samples.data(),2,scratch.data(),&result)==-2 &&
        result.total==rejected.total && result.count==rejected.count &&
        result.minimum==rejected.minimum && result.maximum==rejected.maximum &&
        result.p95==rejected.p95 && result.p99==rejected.p99,"Rejected result mutated");
    require(next_frame_stats(samples.data(),1,scratch.data(),&result)==0 &&
        result.total==UINT64_MAX && result.p95==UINT64_MAX,"Max tick comparator failed");
}
struct Layer {
    int width,height;
    std::vector<uint8_t> raw,blur;
    std::array<NextPoint,16> points{};
    std::array<NextFeature,16> expected{};
};
/**
 * @brief Precompute changing inputs and independent CPU records outside timing.
 * @param pattern Constant/ramp/checker/noise pattern, in [0,5].
 * @param level Fixed pyramid layer, in [0,7].
 * @return Input buffers, selected synthetic points and CPU-oracle records.
 */
static Layer make_layer(int pattern,int level) {
    const int widths[]={960,800,667,556,463,386,322,268};
    const int heights[]={720,600,500,417,347,289,241,201};
    Layer layer; layer.width=widths[level]; layer.height=heights[level];
    orb_golden::Image image(layer.width,layer.height);
    uint32_t seed=UINT32_C(0x523132)+uint32_t(level);
    for (int y=0;y<layer.height;++y) for (int x=0;x<layer.width;++x) {
        uint8_t value=0;
        switch (pattern) {
        case 1: value=255; break;
        case 2: value=uint8_t(x*3+y/7); break;
        case 3: value=uint8_t(y*5+x/11); break;
        case 4: value=((x/3+y/5)&1)?255:0; break;
        case 5: seed=seed*UINT32_C(1664525)+UINT32_C(1013904223); value=uint8_t(seed>>24); break;
        default: break;
        }
        image.at(x,y)=value;
    }
    const auto blurred=orb_golden::gaussian7(image);
    layer.raw=image.pixels; layer.blur=blurred.pixels;
    for (int index=0;index<16;++index) {
        auto& point=layer.points[index];
        point={8+(index*37+level*11+pattern*13)%(layer.width-48),
            8+(index*53+level*7+pattern*17)%(layer.height-48),index*13,index};
        const auto feature=orb_golden::describe(image,blurred,
            {point.x+16,point.y+16,point.score,point.tile},level,32);
        auto& expected=layer.expected[index];
        expected.x=feature.point.x; expected.y=feature.point.y; expected.score=feature.point.score;
        expected.level=feature.level; expected.bin=feature.bin; expected.m10=feature.m10;
        expected.m01=feature.m01; expected.angle_q16=feature.angle_q16;
        for (int word=0;word<8;++word) for (int lane=0;lane<4;++lane)
            expected.descriptor[word]|=uint32_t(feature.descriptor[word*4+lane])<<(lane*8);
    }
    return layer;
}
/** @brief Report mean/percentiles in host nanoseconds, without hardware FPS claims. */
static void print_stats(const char* mode,const std::array<uint64_t,100>& samples) {
    std::array<uint64_t,100> scratch{};
    NextFrameStats stats{};
    require(next_frame_stats(samples.data(),100,scratch.data(),&stats)==0,"Frame stats failed");
    std::cout << "HOST_BACKEND_STATS mode=" << mode << " frames=" << stats.count
        << " mean_ns=" << double(stats.total)/stats.count << " min_ns=" << stats.minimum
        << " max_ns=" << stats.maximum << " p95_ns=" << stats.p95 << " p99_ns=" << stats.p99 << '\n';
}
/**
 * @brief Compare 100 alternating A/B host frames and record instrumentation cost.
 * @return Zero for independent-CPU outputs, real-clock accounting and statistics.
 * @note Excludes input/oracle setup/comparison. No speed threshold: deltas may be noise.
 */
int main() {
    try {
        test_stats();
        std::array<std::array<Layer,8>,6> layers;
        for (int pattern=0;pattern<6;++pattern) for (int level=0;level<8;++level)
            layers[pattern][level]=make_layer(pattern,level);
        std::array<std::array<NextFeature,16>,8> output{};
        std::array<uint64_t,100> ordinary{},instrumented{},moments{},cordic{},brief{},calibration{};
        uint64_t reads=0;
        NextBackendProfile profile{};
        const auto& warm=layers[0][0];
        require(next_describe(warm.raw.data(),warm.blur.data(),warm.width,warm.height,
            warm.points.data(),16,0,output[0].data(),16)==0 &&
            next_backend_profile_configure(&profile,host_clock,&reads)==0 &&
            next_describe_profiled(warm.raw.data(),warm.blur.data(),warm.width,warm.height,
            warm.points.data(),16,0,output[0].data(),16)==0,"Warmup failed");
        reads=0;
        std::cout << "HOST_BACKEND_CSV frame,pattern,order,default_ns,profile_ns,moment_ns,cordic_ns,brief_ns,clock_loop_ns\n";
        for (int frame=0;frame<100;++frame) {
            const int pattern=frame%6;
            for (int pass=0;pass<2;++pass) {
                const bool active=((pass+(frame&1))&1)!=0;
                if (active) require(next_backend_profile_configure(&profile,host_clock,&reads)==0,
                    "Real clock configure failed");
                const uint64_t start=now_ns();
                for (int level=0;level<8;++level) {
                    const auto& layer=layers[pattern][level];
                    const auto describe=active?next_describe_profiled:next_describe;
                    require(describe(layer.raw.data(),layer.blur.data(),layer.width,layer.height,
                        layer.points.data(),16,level,output[level].data(),16)==0,"Measured backend failed");
                }
                (active?instrumented:ordinary)[frame]=now_ns()-start;
                for (int level=0;level<8;++level)
                    require(std::memcmp(output[level].data(),layers[pattern][level].expected.data(),
                        sizeof(output[level]))==0,"Measured output differs from CPU oracle");
            }
            require(profile.completed_features==128 && profile.moment_ticks+profile.cordic_ticks+
                profile.brief_ticks<=instrumented[frame],"Stages inconsistent with frame interval");
            moments[frame]=profile.moment_ticks; cordic[frame]=profile.cordic_ticks; brief[frame]=profile.brief_ticks;
            uint64_t calibration_reads=0;
            const uint64_t start=now_ns();
            for (int i=0;i<512;++i) (void)host_clock(&calibration_reads);
            calibration[frame]=now_ns()-start;
            require(calibration_reads==512,"Calibration read mismatch");
            std::cout << "HOST_BACKEND_CSV " << frame << ',' << pattern << ',' << (frame&1)
                << ',' << ordinary[frame] << ',' << instrumented[frame] << ',' << moments[frame]
                << ',' << cordic[frame] << ',' << brief[frame] << ',' << calibration[frame] << '\n';
        }
        require(reads==51200,"Real per-feature clock accounting mismatch");
        require(next_backend_profile_configure(nullptr,nullptr,nullptr)==0,"Profile disable failed");
        print_stats("default",ordinary); print_stats("profile",instrumented);
        print_stats("moments",moments); print_stats("cordic_a32",cordic); print_stats("brief",brief);
        print_stats("clock_loop_512_reads",calibration);
        uint64_t ordinary_total=0,instrumented_total=0;
        for (int frame=0;frame<100;++frame) {
            ordinary_total+=ordinary[frame]; instrumented_total+=instrumented[frame];
        }
        require(ordinary_total>0,"Real clock did not advance");
        const double delta=double(instrumented_total)-double(ordinary_total);
        std::cout << "HOST_PROFILE_OVERHEAD mean_delta_ns=" << delta/100.0
            << " percent=" << delta*100.0/double(ordinary_total)
            << " clock_calibration_not_subtracted=1 arm_performance=0\n";
        std::cout << "NEXT_PROFILE_FRAMES_PASS frames=100 layers=8 variants=2 exact_features=25600 clock_reads=51200 stats_max=1000 physical_test=0\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "NEXT_PROFILE_FRAMES_FAIL: " << error.what() << '\n';
        return 1;
    }
}
