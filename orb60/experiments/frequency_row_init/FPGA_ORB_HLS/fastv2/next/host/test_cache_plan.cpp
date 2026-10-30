/* GPL-3.0-or-later: independent CPU oracle and stale-view cache coverage tests. */
#include "next_cache_plan.h"
#include "golden.hpp"
#include "constants.hpp"
#include <algorithm>
#include <array>
#include <climits>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <utility>
#include <vector>

namespace {
constexpr size_t full=960u*720u, guard=32;
constexpr uintptr_t raw_base=0x02400000u, blur_base=0x02a00000u;

/** @brief Enforce assertions also in optimized Release builds. */
void require(bool value,const char* message) {
    if (!value) throw std::runtime_error(message);
}

/** @brief Independent runtime rotations; do not consult generated PS offset tables. */
std::vector<std::pair<int,int>> rotated_union() {
    bool used[63][63]{};
    std::vector<std::pair<int,int>> result;
    for (int bin=0;bin<32;++bin) for (int sample=0;sample<512;++sample) {
        const int x=orb_golden::pattern[2*sample],y=orb_golden::pattern[2*sample+1];
        const int64_t co=orb_golden::trig32[bin][0],si=orb_golden::trig32[bin][1];
        const int dx=int(orb_golden::round_even(x*co-y*si,INT64_C(1)<<30));
        const int dy=int(orb_golden::round_even(x*si+y*co,INT64_C(1)<<30));
        require(dx>=-31 && dx<=31 && dy>=-31 && dy<=31,"Independent offset exceeds bound");
        if (!used[dy+31][dx+31]) {used[dy+31][dx+31]=true;result.emplace_back(dx,dy);}
    }
    return result;
}

/** Host-only DMA storage and independently poisoned CPU views; not a BSP/cache model. */
struct Views {
    std::array<std::vector<uint8_t>,2> dma,cpu;
    std::array<std::vector<bool>,2> touched;
    size_t rounded=0;
    int calls=0,last_plane=-1;
    size_t last_end=0;
    /** @brief Allocate full reusable planes, with separate physical and stale CPU storage. */
    Views():dma{std::vector<uint8_t>(full+2*guard),std::vector<uint8_t>(full+2*guard)},
            cpu(dma) {}
};

/**
 * @brief Model one invalidation by refreshing whole owned cache lines from DMA storage.
 * @param context Reusable views; assert sorted/disjoint ranges and no out-of-owner access.
 * @note There are no hardware operations, barriers, dirty writebacks or timing claims.
 */
void refresh(void* context,int plane,uintptr_t address,uint32_t bytes) {
    auto& view=*static_cast<Views*>(context);
    require(plane==0 || plane==1,"Bad plane");
    const uintptr_t base=plane==0?raw_base:blur_base;
    require(address>=base && !(address%32) && bytes && !(bytes%32),"Unaligned range");
    const size_t begin=size_t(address-base),end=begin+bytes;
    require(begin<end && end<=view.rounded,"Range leaves rounded owner");
    require(plane>=view.last_plane && (plane!=view.last_plane || begin>view.last_end),
        "Ranges not sorted/disjoint/maximally merged");
    for (size_t line=begin/32;line<end/32;++line) {
        require(!view.touched[plane][line],"Duplicate invalidation");
        view.touched[plane][line]=true;
    }
    std::copy(view.dma[plane].begin()+guard+begin,view.dma[plane].begin()+guard+end,
        view.cpu[plane].begin()+guard+begin);
    view.last_plane=plane;view.last_end=end;++view.calls;
}

/** @brief Compare every 64-byte feature field against independent v1.0 sampling. */
void compare(const NextFeature& actual,const orb_golden::Feature& expected) {
    require(actual.x==expected.point.x && actual.y==expected.point.y &&
        actual.score==expected.point.score && actual.level==expected.level &&
        actual.bin==expected.bin && actual.m10==expected.m10 && actual.m01==expected.m01 &&
        actual.angle_q16==expected.angle_q16,"Metadata/moments/angle mismatch");
    for (int word=0;word<8;++word) {
        uint32_t value=0;
        for(int byte=0;byte<4;++byte) value|=uint32_t(expected.descriptor[4*word+byte])<<(8*byte);
        require(actual.descriptor[word]==value,"BRIEF mismatch after selective refresh");
    }
}

/** @brief Reproduce six changing-input patterns without any PS-derived image oracle. */
void fill(orb_golden::Image& image,int pattern,uint32_t& seed) {
    for(int y=0;y<image.height;++y) for(int x=0;x<image.width;++x) {
        uint8_t value=0;
        if(pattern==1) value=255;
        if(pattern==2) value=uint8_t(x*3+y/7);
        if(pattern==3) value=uint8_t(y*5+x/11);
        if(pattern==4) value=((x/3+y/5)&1)?255:0;
        if(pattern==5) {seed=seed*UINT32_C(1664525)+UINT32_C(1013904223);value=uint8_t(seed>>24);}
        image.at(x,y)=value;
    }
}

/** Independent byte traffic counters, never converted into estimated FPGA/ARM FPS. */
struct Coverage {
    uint64_t features=0,planned_bytes=0,full_bytes=0,ranges=0;
    int sparse=0,fallback=0,empty=0;
    std::array<bool,32> bins{};
};

/**
 * @brief Reuse full guarded allocations and compare outputs after selectively refreshing stale views.
 * @param offsets Independent all-bin union used to assert blur coverage for every possible angle.
 * @note FULL simulates the caller's existing full invalidation, not a relaxed numerical gate.
 */
void transaction(NextCachePlan& plan,const NextCacheEnvelope& envelope,Views& view,
    const std::vector<std::pair<int,int>>& offsets,const orb_golden::Image& image,
    const orb_golden::Image& blur,const std::vector<NextPoint>& points,int level,Coverage& coverage) {
    view.rounded=(image.pixels.size()+31u)&~size_t(31);
    view.calls=0;view.last_plane=-1;view.last_end=0;
    for(int plane=0;plane<2;++plane) {
        std::fill(view.cpu[plane].begin(),view.cpu[plane].end(),uint8_t(plane?0x5a:0xa5));
        std::fill(view.dma[plane].begin(),view.dma[plane].end(),uint8_t(plane?0x96:0x69));
        const auto& pixels=plane?blur.pixels:image.pixels;
        std::copy(pixels.begin(),pixels.end(),view.dma[plane].begin()+guard);
        view.touched[plane].assign(view.rounded/32,false);
    }
    const auto stale=view.cpu, before_dma=view.dma;
    const int mode=next_cache_plan_build(&plan,&envelope,raw_base,full,blur_base,full,
        image.width,image.height,points.empty()?nullptr:points.data(),int(points.size()),0);
    require(mode==NEXT_CACHE_FULL || mode==NEXT_CACHE_SPARSE,"Unknown mode");
    if(mode==NEXT_CACHE_SPARSE) {
        const int calls=next_cache_plan_emit(&plan,refresh,&view);
        require(calls==view.calls,"Range count mismatch");
        std::vector<bool> expected_raw(view.rounded/32,false);
        for(const auto& point:points) {
            const int x=point.x+16,y=point.y+16;
            for(int row=-15;row<=15;++row) {
                const int radius=orb_golden::umax[row<0?-row:row];
                for(int u=-radius;u<=radius;++u)
                    expected_raw[size_t((y+row)*image.width+x+u)/32]=true;
            }
            for(const auto& offset:offsets) {
                const int sx=x+offset.first,sy=y+offset.second;
                require(sx>=0 && sx<image.width && sy>=0 && sy<image.height,"Sparse all-bin edge unsafe");
                require(view.touched[1][size_t(sy*image.width+sx)/32],"Missing independent BRIEF line");
            }
        }
        require(expected_raw==view.touched[0],"Raw lines differ from independent moments");
        for(int plane=0;plane<2;++plane) {
            const size_t marked=size_t(std::count(view.touched[plane].begin(),view.touched[plane].end(),true));
            require(marked==plan.marked[plane],"Bitmap count mismatch");
            coverage.planned_bytes+=marked*32;
        }
        if(points.empty()) {require(!calls && !plan.marked[0] && !plan.marked[1],"Empty reused plan");++coverage.empty;}
        else ++coverage.sparse;
    } else {
        require(next_cache_plan_emit(&plan,refresh,&view)==-1 && !view.calls,"FULL emitted partial calls");
        refresh(&view,0,raw_base,uint32_t(view.rounded));
        refresh(&view,1,blur_base,uint32_t(view.rounded));
        coverage.planned_bytes+=2*view.rounded;++coverage.fallback;
    }
    coverage.full_bytes+=2*view.rounded;coverage.ranges+=view.calls;
    for(int plane=0;plane<2;++plane) for(size_t byte=0;byte<view.cpu[plane].size();++byte) {
        const bool refreshed=byte>=guard && byte<guard+view.rounded && view.touched[plane][(byte-guard)/32];
        require(view.cpu[plane][byte]==(refreshed?view.dma[plane][byte]:stale[plane][byte]),
            "Unselected line/guard/tail changed");
    }
    const auto before_cpu=view.cpu;
    std::array<NextFeature,258> output;
    std::memset(output.data(),0xc3,sizeof(output));const auto output_before=output;
    require(next_describe(view.cpu[0].data()+guard,view.cpu[1].data()+guard,image.width,image.height,
        points.empty()?nullptr:points.data(),int(points.size()),level,output.data()+1,256)==0,"Backend status");
    for(size_t index=0;index<points.size();++index) {
        const auto& point=points[index];
        const auto expected=orb_golden::describe(image,blur,{point.x+16,point.y+16,point.score,point.tile},level,32);
        compare(output[index+1],expected);coverage.bins[size_t(expected.bin)]=true;++coverage.features;
    }
    require(!std::memcmp(output.data(),output_before.data(),sizeof(NextFeature)) &&
        !std::memcmp(output.data()+points.size()+1,output_before.data()+points.size()+1,
        (output.size()-points.size()-1)*sizeof(NextFeature)),"Output guard/tail changed");
    require(view.cpu==before_cpu && view.dma==before_dma,"Backend mutated input/owner/guard");
    std::cout<<"CACHE_CASE_PASS level="<<level<<" points="<<points.size()<<" mode="<<mode
        <<" raw_lines="<<plan.marked[0]<<" blur_lines="<<plan.marked[1]<<" ranges="<<view.calls<<'\n';
}

/** @brief Exercise whole-plan fallback including failure after partial bitmap construction. */
int fallback_tests(NextCachePlan& plan,const NextCacheEnvelope& envelope) {
    const NextPoint valid{32,32,1,0},negative{-1,0,0,0},huge{INT_MAX,INT_MAX,0,0};
    const NextPoint late[]{valid,negative};
    int tests=0;
    // Every unsafe request must clear all bitmap state and forbid any sparse callback.
    const auto check=[&](const NextCacheEnvelope* env,uintptr_t raw,size_t raw_size,
        uintptr_t blur,size_t blur_size,int w,int h,const NextPoint* pts,int n,int force) {
        std::memset(&plan,0xff,sizeof(plan));
        require(next_cache_plan_build(&plan,env,raw,raw_size,blur,blur_size,w,h,pts,n,force)==NEXT_CACHE_FULL,
            "Unsafe request did not fall back");
        require(!plan.marked[0] && !plan.marked[1] && !plan.lines,"Fallback retains partial plan");
        Views view;require(next_cache_plan_emit(&plan,refresh,&view)==-1 && !view.calls,"Fallback emits");
        for(const auto& plane:plan.bits) for(auto bits:plane) require(!bits,"Fallback bitmap not cleared");
        ++tests;
    };
    check(&envelope,raw_base,full,blur_base,full,960,720,&valid,1,1);
    check(nullptr,raw_base,full,blur_base,full,960,720,&valid,1,0);
    NextCacheEnvelope bad{};check(&bad,raw_base,full,blur_base,full,960,720,&valid,1,0);
    check(&envelope,0,full,blur_base,full,960,720,&valid,1,0);
    check(&envelope,raw_base+1,full,blur_base,full,960,720,&valid,1,0);
    check(&envelope,raw_base,full,blur_base+1,full,960,720,&valid,1,0);
    check(&envelope,raw_base,full-1,blur_base,full,960,720,&valid,1,0);
    check(&envelope,raw_base,full,blur_base,full-1,960,720,&valid,1,0);
    check(&envelope,raw_base,full,raw_base+32,full,960,720,&valid,1,0);
    check(&envelope,UINTPTR_MAX&~uintptr_t(31),full,blur_base,full,960,720,&valid,1,0);
    check(&envelope,raw_base,full,blur_base,full,960,720,nullptr,1,0);
    check(&envelope,raw_base,full,blur_base,full,960,720,&valid,-1,0);
    check(&envelope,raw_base,full,blur_base,full,960,720,&valid,257,0);
    check(&envelope,raw_base,full,blur_base,full,32,720,&valid,1,0);
    check(&envelope,raw_base,full,blur_base,full,961,720,&valid,1,0);
    check(&envelope,raw_base,full,blur_base,full,960,32,&valid,1,0);
    check(&envelope,raw_base,full,blur_base,full,960,721,&valid,1,0);
    check(&envelope,raw_base,full,blur_base,full,960,720,&negative,1,0);
    check(&envelope,raw_base,full,blur_base,full,960,720,&huge,1,0);
    check(&envelope,raw_base,full,blur_base,full,960,720,late,2,0);
    require(next_cache_plan_build(nullptr,&envelope,raw_base,full,blur_base,full,960,720,&valid,1,0)==-1,
        "Null plan accepted");++tests;
    require(next_cache_plan_emit(nullptr,refresh,nullptr)==-1 &&
        next_cache_plan_emit(&plan,nullptr,nullptr)==-1,"Null emitter accepted");++tests;
    require(next_cache_envelope_init(nullptr)==-1,"Null envelope accepted");++tests;
    return tests;
}
}

/** @brief Bounded host-only cache-line experiment; optional archived PGM adds real selected points. */
int main(int argc,char** argv) {
    try {
        require(argc<=2,"Expected optional archived PGM only");
        NextCacheEnvelope envelope{};NextCachePlan plan{};Views view;Coverage changing,archived;
        require(next_cache_envelope_init(&envelope)==0,"Envelope initialization");
        const auto offsets=rotated_union();
        std::array<int,63> minimum,maximum;
        minimum.fill(127);maximum.fill(-127);
        for(const auto& offset:offsets) {
            const size_t row=size_t(offset.second+31);
            minimum[row]=std::min(minimum[row],offset.first);
            maximum[row]=std::max(maximum[row],offset.first);
        }
        for(size_t row=0;row<63;++row) require(envelope.minimum[row]==minimum[row] &&
            envelope.maximum[row]==maximum[row],"Generated envelope differs from independent rotation");
        const int widths[]{960,800,667,556,463,386,322,268},heights[]{720,600,500,417,347,289,241,201};
        const int counts[]{256,1,31,128,32,255};uint32_t seed=UINT32_C(0x523132);
        for(int level=0;level<8;++level) {
            orb_golden::Image image(widths[level],heights[level]);
            for(int pattern=0;pattern<6;++pattern) {
                std::cerr<<"CACHE_TRANSACTION level="<<level<<" pattern="<<pattern<<'\n';
                fill(image,pattern,seed);const auto blur=orb_golden::gaussian7(image);
                std::vector<NextPoint> points(size_t(counts[pattern]));
                for(int index=0;index<counts[pattern];++index) {
                    const int order=(pattern&1)?counts[pattern]-1-index:index;
                    points[size_t(index)]={8+(order*37+level*11+pattern*13)%(image.width-48),
                        8+(order*53+level*7+pattern*17)%(image.height-48),
                        (order*19+pattern*31)&255,index%204};
                }
                if(!pattern) {points[0]={0,0,0,0};points[1]={image.width-33,0,255,1};
                    points[2]={0,image.height-33,1,2};points[3]={image.width-33,image.height-33,254,3};}
                transaction(plan,envelope,view,offsets,image,blur,points,level,changing);
            }
            transaction(plan,envelope,view,offsets,image,orb_golden::gaussian7(image),{},level,changing);
        }
        require(changing.features==5624 && std::count(changing.bins.begin(),changing.bins.end(),true)==32 &&
            changing.empty==8 && changing.sparse==40 && changing.fallback==8,"Changing coverage incomplete");
        const int rejected=fallback_tests(plan,envelope);
        // Small legal constant-image edges need full fallback, while the numerical backend still succeeds.
        orb_golden::Image small(33,33);
        transaction(plan,envelope,view,offsets,small,orb_golden::gaussian7(small),{{0,0,0,0}},0,archived);
        int archive_layers=0;
        if(argc==2) {
            const auto result=orb_golden::extract(orb_golden::read_pgm(argv[1]),orb_golden::Config{});
            require(result.layers.size()==8,"Archive layer count");
            for(const auto& layer:result.layers) {
                std::vector<NextPoint> points;
                for(const auto& point:layer.selected) points.push_back({point.x,point.y,point.score,point.tile});
                transaction(plan,envelope,view,offsets,layer.image,layer.blurred,points,archive_layers,archived);
                ++archive_layers;
            }
            require(archived.features==281,"Archive feature count changed");
        }
        std::cout<<"CACHE_TRAFFIC changing_planned="<<changing.planned_bytes<<" changing_full="<<changing.full_bytes
            <<" archive_planned="<<archived.planned_bytes<<" archive_full="<<archived.full_bytes
            <<" archive_ranges="<<archived.ranges<<" archive_sparse="<<archived.sparse
            <<" archive_fallback="<<archived.fallback<<" performance_claim=0\n";
        std::cout<<"NEXT_CACHE_PLAN_HOST_PASS transactions=56 features=5624 bins=32 empty=8 sparse=40 fallback=8"
            <<" rejection_checks="<<rejected<<" archive_layers="<<archive_layers
            <<" independent_all_bins=1 stale_views=1 guards=1 physical_test=0\n";
        return 0;
    } catch(const std::exception& error) {
        std::cerr<<"NEXT_CACHE_PLAN_HOST_FAIL: "<<error.what()<<'\n';return 1;
    }
}
