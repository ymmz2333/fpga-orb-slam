/* GPL-3.0-or-later: exact R11 A32 orientation and rotated BRIEF semantics. */
#pragma once
#include <cstdint>
#include "descriptor_memory.hpp"
namespace orb60 {
constexpr uint32_t kDescriptorVersion=UINT32_C(0x00600002);
/** Payload counts include aligned patch words. cycles excludes final stats write.
 * Host execution has no cycle model and reports 1 for accepted transactions.
 */
struct DescriptorStats {
    uint32_t version,status,level,requested,completed,frame_offset;
    uint32_t raw_read_bytes,blur_read_bytes,point_read_bytes,feature_write_bytes;
    uint32_t dataflow_cycles,flags,reserved[4];
};
static_assert(sizeof(DescriptorStats)==64,"DescriptorStats ABI");
}
/** Append original 64-byte features at frame_offset in the supplied capacity.
 * Per-layer count <=256, whole-frame capacity <=1000. status -1: bad controls;
 * -2: invalid point/sample. Preserve records completed before the first bad point;
 * drain all channels after failure. Inputs/output/stats must have disjoint ownership.
 */
extern "C" int fastv2_descriptor_hls(DescriptorReadPort raw,DescriptorReadPort blurred,
    const uint64_t* points,uint64_t* features,uint64_t* stats,int width,int height,
    int count,int level,int frame_offset,int capacity);
#if !defined(__SYNTHESIS__) && !defined(FASTV2_HLS_CSIM)
uint32_t orb60_descriptor_angle_q16(int32_t m10,int32_t m01);
int orb60_descriptor_quantize(uint32_t angle);
#endif
