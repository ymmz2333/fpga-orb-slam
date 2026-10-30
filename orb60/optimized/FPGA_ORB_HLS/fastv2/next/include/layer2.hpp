#pragma once
#include <cstdint>
#ifndef ORB60_LAYER_PPC
#define ORB60_LAYER_PPC 2
#endif
#if ORB60_LAYER_PPC != 2 && ORB60_LAYER_PPC != 4
#error "ORB60 layer PPC must be 2 or 4"
#endif

namespace orb60 {
constexpr int kLayerPpc=ORB60_LAYER_PPC;
constexpr uint32_t kLayerVersion = ORB60_LAYER_PPC==4 ? UINT32_C(0x00600003) : UINT32_C(0x00600001);
/** Counters describe this layer; dataflow_cycles excludes final statistics write.
 * AXI byte counts describe issued payload, including final 64-bit padding.
 * Version 0x600003 counts source/blur quads and variable-width Resize packets in
 * the legacy *_pairs fields. Resize has one packet per source quad/active row.
 * Host functional execution has no cycle model and produces dataflow_cycles=1.
 */
struct LayerStats {
    uint32_t version, status, level, width, height;
    uint32_t input_read_bytes, blur_write_bytes, resize_write_bytes;
    uint32_t image_pairs, blur_pairs, resize_pairs, dataflow_cycles, flags;
    uint32_t reserved[3];
};
static_assert(sizeof(LayerStats) == 64, "LayerStats ABI is 64 bytes");
}

/** One shared DDR read, exact FAST/Gaussian/Resize outputs, four AXI masters.
 * At level 7 resize output is untouched. Invalid arguments touch only summary
 * and statistics. Selected-capacity failure still produces the legal images.
 * The Point and Result byte layouts and ordering remain unchanged.
 */
extern "C" int fastv2_layer2_hls(const uint64_t* image, uint64_t* blurred,
    uint64_t* resized, uint64_t* selected, uint64_t* result, uint64_t* stats,
    int level, int budget, int high_threshold, int low_threshold,
    int dual_threshold, int selected_capacity);
