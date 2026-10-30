/* Included only by NEXT_BOARD_PROFILE builds, after the PS timer definition. */
#include "board_profile_contract.h"
#include "next_backend_profile.h"
#include "next_frame_stats.h"
static NextBackendProfile profile_stages;
static uint32_t profile_count, profile_reads;
static uint64_t profile_previous[5], profile_samples[1000], profile_scratch[1000];
/** @brief Access private aligned DDR; never overlaps PL workspaces or schema-5 mailbox. */
static volatile uint32_t* profile_words(void) {
    return (volatile uint32_t*)(UINTPTR)NEXT_PROFILE_DDR;
}
/** @brief Store a raw PS uint64 tick count as low/high words for XSCT. */
static void profile_put(volatile uint32_t* words,uint32_t offset,uint64_t ticks) {
    words[offset]=(uint32_t)ticks; words[offset+1]=(uint32_t)(ticks>>32);
}
/** @brief Count instrumentation reads and use the real BSP global timer on ARM. */
static uint64_t profile_clock(void* context) {
    (void)context; ++profile_reads; return now_ticks();
}
/** @brief Sum eight per-level intervals; no kernel-internal timing is inferred. */
static uint64_t profile_sum(const uint64_t values[8]) {
    uint64_t total=0; int level;
    for (level=0;level<8;++level) total+=values[level];
    return total;
}
/** @brief Clear only the header; stale records remain excluded by committed count. */
static void profile_initialize(void) {
    volatile uint32_t* words=profile_words(); uint32_t i;
    profile_count=profile_reads=0;
    for (i=0;i<NEXT_PROFILE_HEADER_WORDS;++i) words[i]=0;
    words[PH_MAGIC]=NEXT_PROFILE_MAGIC; words[PH_SCHEMA]=NEXT_PROFILE_SCHEMA;
    words[PH_CAPACITY]=NEXT_PROFILE_MAX_FRAMES; words[PH_TIMER_HZ]=(uint32_t)COUNTS_PER_SECOND;
    words[PH_RECORD_WORDS]=NEXT_PROFILE_FRAME_WORDS; words[PH_HEADER_WORDS]=NEXT_PROFILE_HEADER_WORDS;
    words[PH_RECORD_ADDRESS]=NEXT_PROFILE_DDR+NEXT_PROFILE_HEADER_WORDS*4;
    words[PH_READS_PER_FEATURE]=4;
    Xil_DCacheFlushRange(NEXT_PROFILE_DDR,NEXT_PROFILE_HEADER_WORDS*4);
    words[PH_STATUS]=NEXT_RUNNING;
    Xil_DCacheFlushRange(NEXT_PROFILE_DDR,NEXT_PROFILE_HEADER_WORDS*4);
}
/**
 * @brief Reset feature profiling and snapshot aggregate stages before frame timing.
 * @param backend Existing per-level backend accumulators.
 * @param stages Existing preparation/cache/wait accumulators.
 * @param config Existing register-configuration accumulator; all remain unchanged.
 */
static void profile_begin(const uint64_t backend[8],const uint64_t stages[3][8],uint64_t config) {
    profile_reads=0;
    (void)next_backend_profile_configure(&profile_stages,profile_clock,0);
    profile_previous[0]=profile_sum(backend); profile_previous[1]=profile_sum(stages[0]);
    profile_previous[2]=profile_sum(stages[1]); profile_previous[3]=profile_sum(stages[2]);
    profile_previous[4]=config;
}
/**
 * @brief Record one successful frame after its timed interval, excluding publication.
 * @return Zero on consistent accounting; -1 means no record committed.
 * @note Calibration includes loop/read cost, never deducted from feature stages.
 */
static int profile_record(uint64_t processing,uint64_t wall,uint32_t candidates,uint32_t selected,
                           const uint64_t backend[8],const uint64_t stages[3][8],uint64_t config) {
    volatile uint32_t* record; uint32_t i; uint64_t begin;
    if (profile_count>=NEXT_PROFILE_MAX_FRAMES || selected>2048 ||
        profile_stages.completed_features!=selected || profile_reads!=selected*4u || processing>wall)
        return -1;
    record=profile_words()+NEXT_PROFILE_HEADER_WORDS+profile_count*NEXT_PROFILE_FRAME_WORDS;
    for (i=0;i<NEXT_PROFILE_FRAME_WORDS;++i) record[i]=0;
    profile_put(record,PF_PROCESS,processing); profile_put(record,PF_WALL,wall);
    profile_put(record,PF_VERIFY,wall-processing);
    profile_put(record,PF_MOMENTS,profile_stages.moment_ticks);
    profile_put(record,PF_CORDIC,profile_stages.cordic_ticks); profile_put(record,PF_BRIEF,profile_stages.brief_ticks);
    profile_put(record,PF_BACKEND,profile_sum(backend)-profile_previous[0]);
    profile_put(record,PF_PREP,profile_sum(stages[0])-profile_previous[1]);
    profile_put(record,PF_CACHE,profile_sum(stages[1])-profile_previous[2]);
    profile_put(record,PF_WAIT,profile_sum(stages[2])-profile_previous[3]);
    profile_put(record,PF_CONFIG,config-profile_previous[4]);
    record[PF_CANDIDATES]=candidates; record[PF_SELECTED]=selected;
    record[PF_FEATURES]=profile_stages.completed_features; record[PF_CLOCK_READS]=profile_reads;
    record[PF_INDEX]=profile_count;
    begin=now_ticks();
    for (i=0;i<selected*4u;++i) (void)now_ticks();
    profile_put(record,PF_CLOCK_CALIBRATION,now_ticks()-begin);
    ++profile_count;
    return 0;
}
/**
 * @brief Publish all successful records and percentile payload before terminal status.
 * @param status Exact PASS/FAIL or COMPLETE_UNVERIFIED, identical to the main mailbox.
 * @return Zero on valid statistics; -1 on internal count/overflow error.
 * @note Failure publishes only complete frames; no snapshot is promised while RUNNING.
 */
static int profile_finish(uint32_t status) {
    volatile uint32_t* words=profile_words(); NextFrameStats stats; uint32_t i;
    int error=0;
    (void)next_backend_profile_configure(0,0,0);
    words[PH_MODE]=mailbox()[MB_MODE]; words[PH_SCHEDULE]=mailbox()[MB_SCHEDULE];
    words[PH_COUNT]=profile_count; words[PH_ERROR]=mailbox()[MB_ERROR];
    words[PH_FAILING_FRAME]=mailbox()[MB_FAILING_ITERATION];
    if (profile_count) {
        for (i=0;i<profile_count;++i) {
            const volatile uint32_t* r=words+NEXT_PROFILE_HEADER_WORDS+i*NEXT_PROFILE_FRAME_WORDS;
            profile_samples[i]=(uint64_t)r[PF_PROCESS]|((uint64_t)r[PF_PROCESS+1]<<32);
        }
        if (next_frame_stats(profile_samples,profile_count,profile_scratch,&stats)) error=-1;
        else { profile_put(words,PH_PROCESS_P95,stats.p95); profile_put(words,PH_PROCESS_P99,stats.p99); }
        for (i=0;i<profile_count;++i) {
            const volatile uint32_t* r=words+NEXT_PROFILE_HEADER_WORDS+i*NEXT_PROFILE_FRAME_WORDS;
            profile_samples[i]=(uint64_t)r[PF_WALL]|((uint64_t)r[PF_WALL+1]<<32);
        }
        if (next_frame_stats(profile_samples,profile_count,profile_scratch,&stats)) error=-1;
        else { profile_put(words,PH_WALL_P95,stats.p95); profile_put(words,PH_WALL_P99,stats.p99); }
    }
    if (status!=NEXT_FAIL && (!profile_count || profile_count!=mailbox()[MB_COMPLETED])) error=-1;
    Xil_DCacheFlushRange(NEXT_PROFILE_DDR,(NEXT_PROFILE_HEADER_WORDS+profile_count*NEXT_PROFILE_FRAME_WORDS)*4);
    words[PH_STATUS]=error?(uint32_t)NEXT_FAIL:status;
    Xil_DCacheFlushRange(NEXT_PROFILE_DDR,NEXT_PROFILE_HEADER_WORDS*4);
    return error;
}
