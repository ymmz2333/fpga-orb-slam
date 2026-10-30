/* GPL-3.0-or-later: versioned 4PPC implementation of the retained AXI top. */
#include "front4_stream.hpp"
#include "layer4_images.hpp"
#if ORB60_LAYER_IO_OVERLAP
#include "layer4_io.hpp"
#endif

void fork_layer4_quads(hls::stream<uint32_t>& input,hls::stream<uint32_t>& fast,
    hls::stream<uint32_t>& gaussian,hls::stream<uint32_t>& resize,int width,int height) {
#pragma HLS INLINE off
    for(int y=0;y<height;++y) {
ForkLayerQuads:
        for(int x=0;x<width;x+=4) {
#pragma HLS PIPELINE II=1
            const uint32_t quad=input.read();fast.write(quad);gaussian.write(quad);resize.write(quad);
        }
    }
}

void layer4_dataflow(const uint64_t* image,uint64_t* blurred,uint64_t* resized,
    uint64_t* selected,uint64_t* result,const fastv2_profile::Profile& p,
    int level,int high,int low,int dual,int capacity,int dw,int dh,hls::stream<uint64_t>& completion) {
#pragma HLS INLINE off
    hls::stream<uint64_t> words,candidates,horizontal,blur_words,resize_words;
    hls::stream<uint32_t> quads,fast_raw,gaussian_raw,resize_raw;
    hls::stream<CandidateQuad> candidate_quads;
    hls::stream<PixelQuad> blur_quads,resize_quads;
    hls::stream<uint8_t> fast_done,blur_done,resize_done;
#pragma HLS STREAM variable=words depth=128
#pragma HLS STREAM variable=quads depth=64
#pragma HLS STREAM variable=fast_raw depth=64
#pragma HLS STREAM variable=gaussian_raw depth=64
#pragma HLS STREAM variable=resize_raw depth=64
#pragma HLS STREAM variable=horizontal depth=64
#pragma HLS STREAM variable=candidate_quads depth=64
#pragma HLS STREAM variable=candidates depth=128
#pragma HLS STREAM variable=blur_quads depth=64
#pragma HLS STREAM variable=resize_quads depth=64
#pragma HLS STREAM variable=blur_words depth=64
#pragma HLS STREAM variable=resize_words depth=64
#pragma HLS STREAM variable=fast_done depth=2
#pragma HLS STREAM variable=blur_done depth=2
#pragma HLS STREAM variable=resize_done depth=2
#pragma HLS AGGREGATE variable=candidate_quads compact=bit
#pragma HLS AGGREGATE variable=blur_quads compact=bit
#pragma HLS AGGREGATE variable=resize_quads compact=bit
#pragma HLS BIND_STORAGE variable=words type=fifo impl=bram
#pragma HLS BIND_STORAGE variable=candidate_quads type=fifo impl=bram
#pragma HLS BIND_STORAGE variable=horizontal type=fifo impl=bram
#if ORB60_LAYER_BRAM_FIFOS
#pragma HLS BIND_STORAGE variable=quads type=fifo impl=bram
#pragma HLS BIND_STORAGE variable=fast_raw type=fifo impl=bram
#pragma HLS BIND_STORAGE variable=gaussian_raw type=fifo impl=bram
#pragma HLS BIND_STORAGE variable=resize_raw type=fifo impl=bram
#pragma HLS BIND_STORAGE variable=candidates type=fifo impl=bram
#pragma HLS BIND_STORAGE variable=blur_quads type=fifo impl=bram
#pragma HLS BIND_STORAGE variable=resize_quads type=fifo impl=bram
#pragma HLS BIND_STORAGE variable=blur_words type=fifo impl=bram
#pragma HLS BIND_STORAGE variable=resize_words type=fifo impl=bram
#endif
#pragma HLS DATAFLOW
#if ORB60_LAYER_IO_OVERLAP
    layer4_read_dataflow(image,words,p.width*p.height);
#else
    read_front2_words(image,words,p.width*p.height);
#endif
    unpack_front4_words(words,quads,p.width,p.height);
    fork_layer4_quads(quads,fast_raw,gaussian_raw,resize_raw,p.width,p.height);
    scan_front4_quads(fast_raw,candidate_quads,p,high,low,dual);
    serialize_front4_quads(candidate_quads,candidates);
    consume_and_select(candidates,selected,result,p,high,dual,capacity,fast_done);
    gaussian4_horizontal(gaussian_raw,horizontal,p.width,p.height);
    gaussian4_vertical(horizontal,blur_quads,p.width,p.height);
    layer_pack_quads<0>(blur_quads,blur_words,p.width,p.height);
#if ORB60_LAYER_IO_OVERLAP
    layer4_write_dataflow<0>(blur_words,blurred,p.width*p.height,blur_done);
#else
    layer_write_words<0>(blur_words,blurred,p.width*p.height,blur_done);
#endif
    resize4_quads(resize_raw,resize_quads,level,p.width,p.height,dw,dh);
    layer_pack_quads<1>(resize_quads,resize_words,dw,dh);
#if ORB60_LAYER_IO_OVERLAP
    layer4_write_dataflow<1>(resize_words,resized,dw*dh,resize_done);
#else
    layer_write_words<1>(resize_words,resized,dw*dh,resize_done);
#endif
    count_layer2_cycles(fast_done,blur_done,resize_done,completion);
#ifndef __SYNTHESIS__
    assert(words.empty() && quads.empty() && fast_raw.empty() && gaussian_raw.empty() && resize_raw.empty());
    assert(horizontal.empty() && candidate_quads.empty() && candidates.empty() && blur_quads.empty() && resize_quads.empty());
    assert(blur_words.empty() && resize_words.empty() && fast_done.empty() && blur_done.empty() && resize_done.empty());
#endif
}
