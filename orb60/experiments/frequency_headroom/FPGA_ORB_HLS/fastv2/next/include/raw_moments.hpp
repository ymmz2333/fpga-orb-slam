/* GPL-3.0-or-later: exact circular moments from aligned 64-bit DDR beats. */
#pragma once
#include "descriptor_widths.hpp"
#include "descriptor_rom.hpp"

#ifndef ORB60_DESCRIPTOR_MOMENT_FUSION
#define ORB60_DESCRIPTOR_MOMENT_FUSION 0
#endif
#if ORB60_DESCRIPTOR_MOMENT_FUSION < 0 || ORB60_DESCRIPTOR_MOMENT_FUSION > 2
#error Unsupported raw moment fusion mode
#endif
#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
#include <ap_int.h>
typedef ap_int<6> RawMomentCoordinate;
typedef ap_int<12> RawMomentPositiveSum;
typedef ap_int<18> RawMomentProduct;
#else
typedef int32_t RawMomentCoordinate;
typedef int32_t RawMomentPositiveSum;
typedef int32_t RawMomentProduct;
#endif

struct RawWordMoments {RawMomentProduct m10,m01;};

inline RawWordMoments raw_word_moments(uint64_t beat,int word,int alignment,int row) {
#pragma HLS INLINE
    const RawMomentCoordinate base=word*8-alignment-15;
    const RawMomentCoordinate v=row-15;
    const int extent=orb60_descriptor_rom::kUmax[row<15?15-row:row-15];
    uint16_t sums[8],ranks[8];
#pragma HLS ARRAY_PARTITION variable=sums complete
#pragma HLS ARRAY_PARTITION variable=ranks complete
    for(int lane=0;lane<8;++lane) {
#pragma HLS UNROLL
        const int u=int(base)+lane;
        const uint8_t pixel=u>=-extent && u<=extent?uint8_t(beat>>(lane*8)):uint8_t(0);
        sums[lane]=pixel;ranks[lane]=uint16_t(lane)*pixel;
    }
    const RawMomentPositiveSum sum=((sums[0]+sums[1])+(sums[2]+sums[3]))+
        ((sums[4]+sums[5])+(sums[6]+sums[7]));
    const uint16_t rank=((ranks[0]+ranks[1])+(ranks[2]+ranks[3]))+
        ((ranks[4]+ranks[5])+(ranks[6]+ranks[7]));
    // base in [-22,17], v in [-15,15], sum <=2040, rank <=7140.
    // One variable multiply per axis, instead of eight pixel multipliers.
    RawMomentProduct mx=base*sum,my=v*sum;
#if ORB60_DESCRIPTOR_MOMENT_FUSION == 2
#pragma HLS BIND_OP variable=mx op=mul impl=dsp latency=2
#pragma HLS BIND_OP variable=my op=mul impl=dsp latency=2
#endif
    return {RawMomentProduct(mx+rank),my};
}
