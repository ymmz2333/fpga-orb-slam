/* GPL-3.0-or-later: authored planner, not yet enabled in board firmware. */
#include "next_cache_plan.h"
#include "backend_tables.h"
#include <string.h>

/** @copydoc next_cache_envelope_init */
int next_cache_envelope_init(NextCacheEnvelope* envelope) {
    int row,bin,sample;
    if (!envelope) return -1;
    memset(envelope,0,sizeof(*envelope));
    for (row=0;row<NEXT_CACHE_OFFSET_ROWS;++row) {
        envelope->minimum[row]=127; envelope->maximum[row]=-127;
    }
    for (bin=0;bin<32;++bin) for (sample=0;sample<512;++sample) {
        const int x=kNextBriefOffsets[bin][sample][0], y=kNextBriefOffsets[bin][sample][1];
        if (x < -NEXT_CACHE_OFFSET_RADIUS || x > NEXT_CACHE_OFFSET_RADIUS ||
            y < -NEXT_CACHE_OFFSET_RADIUS || y > NEXT_CACHE_OFFSET_RADIUS) return -1;
        row=y+NEXT_CACHE_OFFSET_RADIUS;
        if (x<envelope->minimum[row]) envelope->minimum[row]=(int16_t)x;
        if (x>envelope->maximum[row]) envelope->maximum[row]=(int16_t)x;
    }
    envelope->ready=UINT32_C(0x43414348);
    return 0;
}

/** @brief Mark all cache lines touched by an already bounded inclusive byte span. */
static void next_cache_mark(NextCachePlan* plan,int plane,uint32_t first,uint32_t last) {
    uint32_t line;
    for (line=first/NEXT_CACHE_LINE;line<=last/NEXT_CACHE_LINE;++line) {
        uint32_t* word=&plan->bits[plane][line/32u];
        const uint32_t bit=UINT32_C(1)<<(line%32u);
        if (!(*word&bit)) { *word|=bit; ++plan->marked[plane]; }
    }
}

/** @copydoc next_cache_plan_build */
int next_cache_plan_build(NextCachePlan* plan,const NextCacheEnvelope* envelope,
                         uintptr_t raw_base,size_t raw_owned,uintptr_t blur_base,size_t blur_owned,
                         int width,int height,const NextPoint* points,int count,int require_full) {
    uint32_t pixels,rounded; int index,row;
    if (!plan) return -1;
    memset(plan,0,sizeof(*plan)); plan->mode=NEXT_CACHE_FULL;
    if (require_full || !envelope || envelope->ready!=UINT32_C(0x43414348) ||
        !raw_base || !blur_base || (raw_base%NEXT_CACHE_LINE) || (blur_base%NEXT_CACHE_LINE) ||
        width<33 || width>960 || height<33 || height>720 || count<0 || count>256 ||
        (count && !points)) return NEXT_CACHE_FULL;
    pixels=(uint32_t)width*(uint32_t)height;
    rounded=(pixels+NEXT_CACHE_LINE-1u)&~(uint32_t)(NEXT_CACHE_LINE-1u);
    if (raw_owned<rounded || blur_owned<rounded || raw_owned>UINTPTR_MAX-raw_base ||
        blur_owned>UINTPTR_MAX-blur_base ||
        (raw_base<blur_base+blur_owned && blur_base<raw_base+raw_owned)) return NEXT_CACHE_FULL;
    plan->bases[0]=raw_base; plan->bases[1]=blur_base;
    plan->lines=rounded/NEXT_CACHE_LINE;
    for (index=0;index<count;++index) {
        int x,y;
        if (points[index].x<0 || points[index].x>=width-32 ||
            points[index].y<0 || points[index].y>=height-32) goto fallback;
        x=points[index].x+16; y=points[index].y+16;
        for (row=-15;row<=15;++row) {
            const int u=kNextUmax[row<0?-row:row];
            const uint32_t center=(uint32_t)((y+row)*width+x);
            next_cache_mark(plan,0,center-(uint32_t)u,center+(uint32_t)u);
        }
        for (row=0;row<NEXT_CACHE_OFFSET_ROWS;++row) {
            const int minimum=envelope->minimum[row], maximum=envelope->maximum[row];
            const int sample_y=y+row-NEXT_CACHE_OFFSET_RADIUS;
            uint32_t center;
            if (minimum>maximum) continue;
            if (minimum < -NEXT_CACHE_OFFSET_RADIUS || maximum > NEXT_CACHE_OFFSET_RADIUS ||
                sample_y<0 || sample_y>=height || x+minimum<0 || x+maximum>=width) goto fallback;
            center=(uint32_t)(sample_y*width+x);
            next_cache_mark(plan,1,(uint32_t)((int)center+minimum),(uint32_t)((int)center+maximum));
        }
    }
    plan->mode=NEXT_CACHE_SPARSE;
    return NEXT_CACHE_SPARSE;
fallback:
    /* No sparse calls have occurred. Remove the complete partial plan before returning. */
    memset(plan,0,sizeof(*plan)); plan->mode=NEXT_CACHE_FULL;
    return NEXT_CACHE_FULL;
}

/** @brief Test one bounded bitmap cache-line membership. */
static int next_cache_has(const NextCachePlan* plan,int plane,uint32_t line) {
    return (plan->bits[plane][line/32u]&(UINT32_C(1)<<(line%32u)))!=0;
}

/** @copydoc next_cache_plan_emit */
int next_cache_plan_emit(const NextCachePlan* plan,NextCacheRange range,void* context) {
    int plane,calls=0;
    if (!plan || !range || plan->mode!=NEXT_CACHE_SPARSE || plan->lines>NEXT_CACHE_MAX_LINES) return -1;
    for (plane=0;plane<2;++plane) {
        uint32_t line=0;
        while (line<plan->lines) {
            uint32_t begin;
            if (!next_cache_has(plan,plane,line)) { ++line; continue; }
            begin=line++;
            while (line<plan->lines && next_cache_has(plan,plane,line)) ++line;
            range(context,plane,plan->bases[plane]+(uintptr_t)begin*NEXT_CACHE_LINE,
                  (line-begin)*NEXT_CACHE_LINE);
            ++calls;
        }
    }
    return calls;
}
