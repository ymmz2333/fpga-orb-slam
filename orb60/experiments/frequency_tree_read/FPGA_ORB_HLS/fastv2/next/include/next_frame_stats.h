#ifndef NEXT_FRAME_STATS_H
#define NEXT_FRAME_STATS_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define NEXT_FRAME_STATS_MAX 1000u
typedef struct {
    uint64_t total, minimum, maximum, p95, p99;
    uint32_t count;
} NextFrameStats;
/**
 * @brief Summarize per-frame ticks with nearest-rank P95/P99, outside processing.
 * @param samples Unmodified input ticks; count must be in [1,1000].
 * @param count Actual completed frames, not requested iterations.
 * @param scratch Caller-owned count-word sorting space, disjoint from inputs/output.
 * @param result Summary, unchanged on invalid arguments or total overflow.
 * @return Zero on success, -1 invalid argument, -2 uint64 sum overflow.
 * @note Average is total/count; conversion requires actual clock frequency. No I/O.
 */
int next_frame_stats(const uint64_t* samples, uint32_t count,
                     uint64_t* scratch, NextFrameStats* result);
#ifdef __cplusplus
}
#endif
#endif
