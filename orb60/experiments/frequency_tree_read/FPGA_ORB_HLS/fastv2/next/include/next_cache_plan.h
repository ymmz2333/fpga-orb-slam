/* GPL-3.0-or-later: conservative cache ownership planner for the exact A32 backend. */
#ifndef NEXT_CACHE_PLAN_H
#define NEXT_CACHE_PLAN_H
#include "next_backend.h"
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
enum { NEXT_CACHE_LINE=32, NEXT_CACHE_MAX_LINES=960*720/32,
       NEXT_CACHE_BITMAP_WORDS=(NEXT_CACHE_MAX_LINES+31)/32,
       NEXT_CACHE_OFFSET_RADIUS=31, NEXT_CACHE_OFFSET_ROWS=63,
       NEXT_CACHE_SPARSE=0, NEXT_CACHE_FULL=1 };
/** Caller-owned, immutable after initialization; row spans cover every A32 bin. */
typedef struct {
    int16_t minimum[NEXT_CACHE_OFFSET_ROWS], maximum[NEXT_CACHE_OFFSET_ROWS];
    uint32_t ready;
} NextCacheEnvelope;
/** One reusable two-plane plan; inactive/FULL plans must never emit sparse calls. */
typedef struct {
    uint32_t bits[2][NEXT_CACHE_BITMAP_WORDS];
    uintptr_t bases[2];
    uint32_t lines, marked[2];
    int mode;
} NextCachePlan;
/** Callback replaces cache operations in host tests; it is never a DMA writer. */
typedef void (*NextCacheRange)(void* context,int plane,uintptr_t address,uint32_t bytes);
/**
 * @brief Build a fixed row envelope from all 32 generated A32 offset bins.
 * @param envelope Caller-owned state; no image, points or hardware are read.
 * @return Zero on a bounded ROM, -1 otherwise with ready cleared.
 * @note Initialize once outside frame timing. No runtime angle is guessed from stale pixels.
 */
int next_cache_envelope_init(NextCacheEnvelope* envelope);
/**
 * @brief Plan exact raw moment rows and conservative all-bin BRIEF row spans.
 * @param plan Caller-owned reusable bitmap; reset even after a previous nonempty frame.
 * @param envelope Initialized immutable ROM envelope.
 * @param raw_base,blur_base Aligned, disjoint allocated image-plane base addresses.
 * @param raw_owned,blur_owned Owned byte extents, including rounding space/guards.
 * @param width,height Legal row-major layer dimensions, 33..960 by 33..720.
 * @param points Already coherent selected-point records, effective coordinates.
 * @param count Selected count, 0..256; null points is allowed only for zero.
 * @param require_full Nonzero for full-image verification/guard scans.
 * @return SPARSE=0, FULL=1 (caller retains existing full maintenance), -1 for null plan.
 * @note Never reads image memory or a DMA-owned point list. Caller must first observe
 *       DMA completion and invalidate points/summary. Any unsafe geometry, alignment,
 *       overlap, allocation, point or all-bin edge sample invalidates the entire plan.
 */
int next_cache_plan_build(NextCachePlan* plan,const NextCacheEnvelope* envelope,
                         uintptr_t raw_base,size_t raw_owned,uintptr_t blur_base,size_t blur_owned,
                         int width,int height,const NextPoint* points,int count,int require_full);
/**
 * @brief Emit sorted, merged, disjoint cache-line ranges only from a complete sparse plan.
 * @param plan Successful immutable sparse plan; reused only after emission ends.
 * @param range Callback receives plane 0=raw or 1=blur, address and aligned byte count.
 * @param context Caller-owned callback context; callback must not modify the plan.
 * @return Number of ranges, or -1 for invalid/FULL plan or missing callback.
 * @note The caller owns barriers and BSP operations. This module never accesses hardware.
 */
int next_cache_plan_emit(const NextCachePlan* plan,NextCacheRange range,void* context);
#ifdef __cplusplus
}
#endif
#endif
