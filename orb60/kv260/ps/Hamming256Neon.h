// PS SIMD only. Same exact256-bit Hamming distance as retained ORBmatcher.
#pragma once
#include <cstdint>
#if !defined(__ARM_NEON)
#error Actual ARM NEON target required; no software fallback in this candidate.
#endif
#include <arm_neon.h>
namespace KvMatch {
inline unsigned distance(const uint8_t* a,const uint8_t* b) {
    const auto x=vcntq_u8(veorq_u8(vld1q_u8(a),vld1q_u8(b)));
    const auto y=vcntq_u8(veorq_u8(vld1q_u8(a+16),vld1q_u8(b+16)));
    const auto s=vpaddlq_u8(vaddq_u8(x,y));const auto t=vpaddlq_u16(s);
    const auto u=vadd_u32(vget_low_u32(t),vget_high_u32(t));
    return vget_lane_u32(vpadd_u32(u,u),0);
}
}
