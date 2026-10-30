#include "next_frame_stats.h"
#include <stdlib.h>
#include <string.h>
/** @brief Compare unsigned ticks for qsort without subtraction overflow. */
static int next_compare_ticks(const void* lhs, const void* rhs) {
    const uint64_t a=*(const uint64_t*)lhs, b=*(const uint64_t*)rhs;
    return (a>b)-(a<b);
}
/** @copydetails next_frame_stats.h::next_frame_stats */
int next_frame_stats(const uint64_t* samples, uint32_t count,
                     uint64_t* scratch, NextFrameStats* result) {
    uint32_t i;
    NextFrameStats summary={0};
    if (!samples || !scratch || !result || !count || count>NEXT_FRAME_STATS_MAX) return -1;
    for (i=0; i<count; ++i) {
        if (UINT64_MAX-summary.total<samples[i]) return -2;
        summary.total+=samples[i];
    }
    memcpy(scratch,samples,count*sizeof(*samples));
    qsort(scratch,count,sizeof(*scratch),next_compare_ticks);
    summary.count=count; summary.minimum=scratch[0]; summary.maximum=scratch[count-1];
    summary.p95=scratch[(count*95u+99u)/100u-1u];
    summary.p99=scratch[(count*99u+99u)/100u-1u];
    *result=summary;
    return 0;
}
