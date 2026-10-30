#define ORB60_LAYER_TOP 1
#define ORB60_FRONT2_TOP 1
#include "fastv2_hls.cpp"
#include "layer2.hpp"
#include "next_block_stream.hpp"
#include "layer2_axis_rom.hpp"

namespace {
#include "layer2_images.hpp"

void fork_layer2_pairs(hls::stream<uint16_t>& input, hls::stream<uint16_t>& fast,
    hls::stream<uint16_t>& gaussian, hls::stream<uint16_t>& resize, int width, int height) {
#pragma HLS INLINE off
    for (int y=0; y<height; ++y) {
    ForkLayerPairs:
        for (int x=0; x<width; x+=2) {
#pragma HLS PIPELINE II=1
            const uint16_t pair=input.read();
            fast.write(pair); gaussian.write(pair); resize.write(pair);
        }
    }
}

/** Clock-loop instrumentation; C execution only checks completion/token balance. */
void count_layer2_cycles(hls::stream<uint8_t>& fast_done, hls::stream<uint8_t>& blur_done,
    hls::stream<uint8_t>& resize_done, hls::stream<uint64_t>& completion) {
#pragma HLS INLINE off
    bool seen_fast=false, seen_blur=false, seen_resize=false;
    uint8_t fast_status=0, token=0;
    uint32_t cycles=0;
CountLayerCycles:
    for (;;) {
#pragma HLS PIPELINE II=1
        if (!seen_fast && fast_done.read_nb(fast_status)) seen_fast=true;
        if (!seen_blur && blur_done.read_nb(token)) seen_blur=true;
        if (!seen_resize && resize_done.read_nb(token)) seen_resize=true;
        ++cycles;
        if (seen_fast && seen_blur && seen_resize) break;
    }
    completion.write((uint64_t(cycles)<<32)|uint64_t(fast_status));
}

#if ORB60_LAYER_PPC == 4
#include "layer4_dataflow.hpp"
#else
void layer2_dataflow(const uint64_t* image, uint64_t* blurred, uint64_t* resized,
    uint64_t* selected, uint64_t* result, const fastv2_profile::Profile& p,
    int level, int high, int low, int dual, int capacity, int dw, int dh,
    hls::stream<uint64_t>& completion) {
#pragma HLS INLINE off
    hls::stream<uint64_t> words, candidates, blur_words, resize_words;
    hls::stream<uint16_t> pairs, fast_raw, gaussian_raw, resize_raw, blur_pairs, resize_pairs;
    hls::stream<uint32_t> horizontal;
    hls::stream<CandidatePair2> candidate_pairs;
    hls::stream<uint8_t> fast_done, blur_done, resize_done;
#pragma HLS STREAM variable=words depth=128
#pragma HLS STREAM variable=pairs depth=64
#pragma HLS STREAM variable=fast_raw depth=64
#pragma HLS STREAM variable=gaussian_raw depth=64
#pragma HLS STREAM variable=resize_raw depth=64
#pragma HLS STREAM variable=horizontal depth=64
#pragma HLS STREAM variable=blur_pairs depth=64
#pragma HLS STREAM variable=resize_pairs depth=64
#pragma HLS STREAM variable=candidate_pairs depth=64
#pragma HLS STREAM variable=candidates depth=128
#pragma HLS STREAM variable=blur_words depth=64
#pragma HLS STREAM variable=resize_words depth=64
#pragma HLS STREAM variable=fast_done depth=2
#pragma HLS STREAM variable=blur_done depth=2
#pragma HLS STREAM variable=resize_done depth=2
#pragma HLS AGGREGATE variable=candidate_pairs compact=bit
#pragma HLS BIND_STORAGE variable=words type=fifo impl=bram
#pragma HLS BIND_STORAGE variable=candidate_pairs type=fifo impl=bram
#pragma HLS DATAFLOW
    read_front2_words(image, words, p.width*p.height);
    unpack_front2_words(words, pairs, p.width, p.height);
    fork_layer2_pairs(pairs, fast_raw, gaussian_raw, resize_raw, p.width, p.height);
    scan_front2_pairs(fast_raw, candidate_pairs, p, fastv2_segment::kPairRunOffsets[level], high, low, dual);
    serialize_front2_pairs(candidate_pairs, candidates);
    consume_and_select(candidates, selected, result, p, high, dual, capacity, fast_done);
    gaussian2_horizontal(gaussian_raw, horizontal, p.width, p.height);
    gaussian2_vertical(horizontal, blur_pairs, p.width, p.height);
    layer_pack_pairs<0>(blur_pairs, blur_words, p.width, p.height);
    layer_write_words<0>(blur_words, blurred, p.width*p.height, blur_done);
    resize2_pairs(resize_raw, resize_pairs, level, p.width, p.height, dw, dh);
    layer_pack_pairs<1>(resize_pairs, resize_words, dw, dh);
    layer_write_words<1>(resize_words, resized, dw*dh, resize_done);
    count_layer2_cycles(fast_done, blur_done, resize_done, completion);
#ifndef __SYNTHESIS__
    assert(words.empty() && pairs.empty() && fast_raw.empty() && gaussian_raw.empty() && resize_raw.empty());
    assert(horizontal.empty() && blur_pairs.empty() && resize_pairs.empty() && candidate_pairs.empty());
    assert(candidates.empty() && blur_words.empty() && resize_words.empty());
    assert(fast_done.empty() && blur_done.empty() && resize_done.empty());
#endif
}

#endif
void write_layer2_stats(uint64_t* destination, const orb60::LayerStats& s) {
#pragma HLS INLINE
    uint64_t words[8];
    words[0]=field_pair(s.version,s.status); words[1]=field_pair(s.level,s.width);
    words[2]=field_pair(s.height,s.input_read_bytes); words[3]=field_pair(s.blur_write_bytes,s.resize_write_bytes);
    words[4]=field_pair(s.image_pairs,s.blur_pairs); words[5]=field_pair(s.resize_pairs,s.dataflow_cycles);
    words[6]=field_pair(s.flags,s.reserved[0]); words[7]=field_pair(s.reserved[1],s.reserved[2]);
    std::memcpy(destination,words,sizeof(words));
}
}

extern "C" int fastv2_layer2_hls(const uint64_t* image, uint64_t* blurred,
    uint64_t* resized, uint64_t* selected, uint64_t* result, uint64_t* stats,
    int level, int budget, int high_threshold, int low_threshold,
    int dual_threshold, int selected_capacity) {
#pragma HLS INTERFACE m_axi port=image offset=slave bundle=gmem0 depth=86400 max_read_burst_length=64 num_read_outstanding=2 max_widen_bitwidth=64
#pragma HLS INTERFACE m_axi port=selected offset=slave bundle=gmem1 depth=2000 max_write_burst_length=16 num_write_outstanding=2 max_widen_bitwidth=64
#pragma HLS INTERFACE m_axi port=result offset=slave bundle=gmem1 depth=8 max_write_burst_length=16 num_write_outstanding=2 max_widen_bitwidth=64
#pragma HLS INTERFACE m_axi port=stats offset=slave bundle=gmem1 depth=8 max_write_burst_length=16 num_write_outstanding=2 max_widen_bitwidth=64
#pragma HLS INTERFACE m_axi port=blurred offset=slave bundle=gmem2 depth=86400 max_write_burst_length=64 num_write_outstanding=2 max_widen_bitwidth=64
#pragma HLS INTERFACE m_axi port=resized offset=slave bundle=gmem3 depth=86400 max_write_burst_length=64 num_write_outstanding=2 max_widen_bitwidth=64
#pragma HLS INTERFACE s_axilite port=image bundle=control
#pragma HLS INTERFACE s_axilite port=blurred bundle=control
#pragma HLS INTERFACE s_axilite port=resized bundle=control
#pragma HLS INTERFACE s_axilite port=selected bundle=control
#pragma HLS INTERFACE s_axilite port=result bundle=control
#pragma HLS INTERFACE s_axilite port=stats bundle=control
#pragma HLS INTERFACE s_axilite port=level bundle=control
#pragma HLS INTERFACE s_axilite port=budget bundle=control
#pragma HLS INTERFACE s_axilite port=high_threshold bundle=control
#pragma HLS INTERFACE s_axilite port=low_threshold bundle=control
#pragma HLS INTERFACE s_axilite port=dual_threshold bundle=control
#pragma HLS INTERFACE s_axilite port=selected_capacity bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    orb60::LayerStats counters={};
    counters.version=orb60::kLayerVersion; counters.level=uint32_t(level);
    const bool invalid=level<0 || level>7 || high_threshold<1 || high_threshold>255 ||
        low_threshold<1 || low_threshold>high_threshold || (dual_threshold!=0 && dual_threshold!=1) || selected_capacity<0;
    if (invalid || budget!=fastv2_profile::kProfiles[level].budget) {
        Result summary; clear_result(summary); summary.status=fastv2::kInvalidArgument;
        write_summary(result,summary);
        counters.status=fastv2::kInvalidArgument; write_layer2_stats(stats,counters);
        return fastv2::kInvalidArgument;
    }
    const fastv2_profile::Profile p=fastv2_profile::kProfiles[level];
    const int dw=level<7 ? fastv2_profile::kProfiles[level+1].width : 0;
    const int dh=level<7 ? fastv2_profile::kProfiles[level+1].height : 0;
    hls::stream<uint64_t> completion;
#pragma HLS STREAM variable=completion depth=2
#if ORB60_LAYER_PPC == 4
    layer4_dataflow(image,blurred,resized,selected,result,p,level,high_threshold,
#else
    layer2_dataflow(image,blurred,resized,selected,result,p,level,high_threshold,
#endif
        low_threshold,dual_threshold,selected_capacity,dw,dh,completion);
    const uint64_t outcome=completion.read();
    const int status=uint8_t(outcome)==fastv2::kSelectedCapacityExceeded
        ? fastv2::kSelectedCapacityExceeded : uint8_t(outcome)==fastv2::kOk ? fastv2::kOk : fastv2::kInvalidArgument;
    counters.status=uint32_t(status); counters.width=uint32_t(p.width); counters.height=uint32_t(p.height);
    counters.input_read_bytes=uint32_t((p.width*p.height+7)/8*8);
    counters.blur_write_bytes=counters.input_read_bytes;
    counters.resize_write_bytes=uint32_t((dw*dh+7)/8*8);
    counters.image_pairs=uint32_t((p.width+orb60::kLayerPpc-1)/orb60::kLayerPpc*p.height); counters.blur_pairs=counters.image_pairs;
    // 4PPC Resize emits one variable-width packet per source quad on active rows.
    counters.resize_pairs=uint32_t((orb60::kLayerPpc==4?(p.width+3)/4:(dw+1)/2)*dh);
    counters.dataflow_cycles=uint32_t(outcome>>32);
    counters.flags=uint32_t(orb60::kLayerPpc|(level<7 ? 1 : 0));
    write_layer2_stats(stats,counters);
    return status;
}

#if !defined(__SYNTHESIS__) && !defined(FASTV2_HLS_CSIM)
#if ORB60_LAYER_PPC == 4
extern "C" int next_test_layer4_merge(const uint64_t* values,const uint8_t* masks,int count,uint64_t* output) {
    hls::stream<CandidateQuad> packets;hls::stream<uint64_t> tokens;int expected=0;
    for(int i=0;i<count;++i) {
        CandidateQuad packet={};packet.mask=masks[i]&15;
        for(int lane=0;lane<4;++lane) {packet.words[lane]=values[4*i+lane];expected+=(packet.mask>>lane)&1;}
        packets.write(packet);
    }
    CandidateQuad end={};end.words[0]=(UINT64_C(1)<<63)|uint64_t(unsigned(expected));packets.write(end);
    serialize_front4_quads(packets,tokens);int completed=0;
    for(;;) {const uint64_t token=tokens.read();if(token>>63) {assert(int(uint32_t(token))==completed);break;}output[completed++]=token;}
    assert(completed==expected && packets.empty() && tokens.empty());return completed;
}
extern "C" void next_test_layer4_gaussian(const uint64_t* image,uint64_t* destination,int width,int height) {
    hls::stream<uint64_t> words,horizontal,packed;hls::stream<uint32_t> raw;hls::stream<PixelQuad> blurred;
    hls::stream<uint8_t> done;
    read_front2_words(image,words,width*height);unpack_front4_words(words,raw,width,height);
    gaussian4_horizontal(raw,horizontal,width,height);gaussian4_vertical(horizontal,blurred,width,height);
    layer_pack_quads<0>(blurred,packed,width,height);layer_write_words<0>(packed,destination,width*height,done);
    assert(done.read()==1 && words.empty() && raw.empty() && horizontal.empty() && blurred.empty() && packed.empty());
}
#endif
/** Standalone arithmetic checks also detect any producer/consumer token mismatch. */
extern "C" int next_test_layer2_image(const uint64_t* image, uint64_t* destination,
    int level, int resize) {
    if (level<0 || level>(resize ? 6 : 7)) return fastv2::kInvalidArgument;
    const auto& p=fastv2_profile::kProfiles[level];
    hls::stream<uint64_t> words, packed;
    hls::stream<uint16_t> raw, result;
    hls::stream<uint32_t> horizontal;
    hls::stream<uint8_t> done;
    read_front2_words(image,words,p.width*p.height);
    unpack_front2_words(words,raw,p.width,p.height);
    int w=p.width,h=p.height;
    if (resize) {
        w=fastv2_profile::kProfiles[level+1].width; h=fastv2_profile::kProfiles[level+1].height;
        resize2_pairs(raw,result,level,p.width,p.height,w,h);
    } else {
        gaussian2_horizontal(raw,horizontal,w,h); gaussian2_vertical(horizontal,result,w,h);
    }
    layer_pack_pairs<0>(result,packed,w,h); layer_write_words<0>(packed,destination,w*h,done);
    assert(words.empty() && raw.empty() && horizontal.empty() && result.empty() && packed.empty());
    assert(done.read()==1); return fastv2::kOk;
}
#endif
