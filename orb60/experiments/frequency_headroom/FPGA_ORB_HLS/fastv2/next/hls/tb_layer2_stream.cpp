#include "fastv2.hpp"
#include "layer2.hpp"
#include "layer2_cases.hpp"
#include "layer2_vectors.inc"
#include "image_test_reference.hpp"
#include <cstring>

static bool run_case(int index) {
    using namespace next_image_test;
    const FrontCase& test=kLayer2Cases[index];
    const auto& p=fastv2_profile::kProfiles[test.level];
    const auto raw=front_case_pixels(test);
    const auto image=pack(raw,false);
    const bool valid=test.budget_delta==0;
    const auto blur_ref=pack(valid ? gaussian(raw,test.level) : std::vector<uint8_t>(),true);
    const auto resize_ref=pack(valid && test.level<7 ? resize(raw,test.level) : std::vector<uint8_t>(),true);
    std::vector<uint64_t> blurred(kPortWords,kPoison), resized(kPortWords,kPoison);
    std::vector<uint64_t> points(2000), expected_points(2000);
    std::memset(points.data(),0xa5,16000); std::memset(expected_points.data(),0xa5,16000);
    const auto& reference=kFrontExpectedSummary[index];
    if (reference.status==fastv2::kOk) std::memcpy(expected_points.data(),kFrontExpectedPoints[index],reference.selected_count*16);
    uint64_t summary_words[8]={}, stats_words[8]={};
    const int status=fastv2_layer2_hls(image.data(),blurred.data(),resized.data(),points.data(),
        summary_words,stats_words,test.level,p.budget+test.budget_delta,test.high,test.low,test.dual,test.capacity);
    orb60::LayerStats counters; std::memcpy(&counters,stats_words,64);
    const uint32_t dw=valid && test.level<7 ? kWidths[test.level+1] : 0;
    const uint32_t dh=valid && test.level<7 ? kHeights[test.level+1] : 0;
    bool stats_ok=counters.version==orb60::kLayerVersion && counters.status==uint32_t(reference.status)
        && counters.level==uint32_t(test.level) && counters.width==uint32_t(valid ? p.width : 0)
        && counters.height==uint32_t(valid ? p.height : 0)
        && counters.input_read_bytes==uint32_t(valid ? (p.width*p.height+7)/8*8 : 0)
        && counters.blur_write_bytes==counters.input_read_bytes
        && counters.resize_write_bytes==uint32_t((dw*dh+7)/8*8)
        && counters.image_pairs==uint32_t(valid ? (p.width+orb60::kLayerPpc-1)/orb60::kLayerPpc*p.height : 0)
        && counters.blur_pairs==counters.image_pairs && counters.resize_pairs==uint32_t((orb60::kLayerPpc==4?(p.width+3)/4:(dw+1)/2)*dh)
        && counters.flags==uint32_t(valid ? orb60::kLayerPpc|(test.level<7 ? 1 : 0) : 0)
        && counters.reserved[0]==0 && counters.reserved[1]==0 && counters.reserved[2]==0
        && (valid ? counters.dataflow_cycles>=1 && counters.dataflow_cycles<4000000 : counters.dataflow_cycles==0);
    const bool fast_ok=status==reference.status && std::memcmp(summary_words,&reference,64)==0
        && points==expected_points;
    const bool blur_ok=blurred==blur_ref, resize_ok=resized==resize_ref;
    if (!fast_ok || !blur_ok || !resize_ok || !stats_ok) {
        std::cerr<<"LAYER2_CASE_FAIL case="<<index<<" fast="<<fast_ok<<" blur="<<blur_ok
            <<" resize="<<resize_ok<<" stats="<<stats_ok<<" cycles="<<counters.dataflow_cycles<<'\n';
        if (!blur_ok) for (size_t i=0;i<kPortWords;++i) if(blurred[i]!=blur_ref[i]) {
            std::cerr<<"LAYER2_BLUR_FIRST_DIFF word="<<i<<" actual="<<blurred[i]<<" expected="<<blur_ref[i]<<'\n'; break;
        }
        if (!resize_ok) for (size_t i=0;i<kPortWords;++i) if(resized[i]!=resize_ref[i]) {
            std::cerr<<"LAYER2_RESIZE_FIRST_DIFF word="<<i<<" actual="<<resized[i]<<" expected="<<resize_ref[i]<<'\n'; break;
        }
        return false;
    }
    std::cout<<"LAYER2_CASE_PASS case="<<index<<" level="<<test.level<<" cycles="<<counters.dataflow_cycles<<'\n';
    return true;
}

static bool invalid_level(int level) {
    using namespace next_image_test;
    std::vector<uint64_t> image(kPortWords,kPoison),blur=image,resized=image;
    std::vector<uint64_t> selected(2000,kPoison), expected=selected;
    uint64_t summary[8]={},stats[8]={};
    const int status=fastv2_layer2_hls(image.data(),blur.data(),resized.data(),selected.data(),summary,stats,
        level,217,20,7,1,1000);
    fastv2::Result wanted={}; wanted.version=fastv2::kResultVersion; wanted.status=fastv2::kInvalidArgument;
    orb60::LayerStats counters; std::memcpy(&counters,stats,64);
    return status==fastv2::kInvalidArgument && std::memcmp(summary,&wanted,64)==0 && blur==image && resized==image
        && selected==expected && counters.version==orb60::kLayerVersion && counters.status==1
        && counters.level==uint32_t(level) && counters.input_read_bytes==0 && counters.dataflow_cycles==0;
}

int main() {
    bool pass=true;
    for (int i=0;i<kLayer2CaseCount;++i) if(!run_case(i)) pass=false;
    if(!invalid_level(-1) || !invalid_level(8)) pass=false;
    if(!pass) return 1;
    std::cout<<"LAYER2_STREAM_PASS cases="<<kLayer2CaseCount+2<<'\n';
    return 0;
}
