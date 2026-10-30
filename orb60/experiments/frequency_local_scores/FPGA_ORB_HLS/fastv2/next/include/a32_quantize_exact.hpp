#ifndef ORB60_A32_QUANTIZE_EXACT_HPP
#define ORB60_A32_QUANTIZE_EXACT_HPP
#include <cstdint>

// Preserve the old six-step search for every uint32_t input, including wrap.
// In the non-clamped domain q=floor(rounded/16384) is at most1439.
// 1457*45=65536+29, and the reciprocal error cannot cross the next integer:
// remainder<=44 and q*29<=41731, so floor(q*1457/65536)=floor(q/45).
inline int orb60_quantize_a32_exact(uint32_t angle) {
#pragma HLS INLINE
    const uint32_t rounded=angle+368640u;
    const uint32_t q=(rounded>>14)&2047u;
    const uint32_t product=q*1457u;
    return rounded>=23592960u ? 0 : int(product>>16);
}
#endif
