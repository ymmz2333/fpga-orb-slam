/**
 * @file board_benchmark.c
 * @brief Eight-level PL resize/FAST/Gaussian plus exact PS A32 ORB benchmark.
 * @note Fixed archived frame repeated 1..1000 times; not a video decoder/B1 serializer.
 */
#include "board_contract.h"
#ifdef NEXT_BOARD_HOST_TEST
#include "board_mock.hpp"
#else
#include "xil_cache.h"
#include "xil_io.h"
#include "xparameters.h"
#include "xtime_l.h"
extern char _end;
#define NEXT_PROGRAM_END ((UINTPTR)&_end)
#endif
#include <stddef.h>
#include <string.h>
#include "front_reference.inc"
#include "full_reference.inc"

static const int kWidths[8] = {960,800,667,556,463,386,322,268};
static const int kHeights[8] = {720,600,500,417,347,289,241,201};
static const int kBudgets[8] = {217,181,151,126,105,87,73,60};
static const uint32_t kBases[3] = {NEXT_FRONT_BASE, NEXT_RESIZE_BASE, NEXT_GAUSSIAN_BASE};
typedef char NextDdrMustFit[(NEXT_REFERENCE_BLUR + NEXT_REFERENCE_PIXELS - 1 <=
                           XPAR_PS7_DDR_0_S_AXI_HIGHADDR) ? 1 : -1];

/**
 * @brief Access the fixed, cache-line-aligned schema-5 result block.
 * @return Volatile words visible to XSCT after explicit cache publication.
 */
static volatile uint32_t* mailbox(void) { return (volatile uint32_t*)(UINTPTR)NEXT_MAILBOX; }
/**
 * @brief Read the PS global timer without converting or assuming a PL cycle count.
 * @return Monotonic ticks at the BSP's COUNTS_PER_SECOND frequency.
 */
static uint64_t now_ticks(void) { XTime ticks; XTime_GetTime(&ticks); return ticks; }
#if defined(NEXT_BOARD_PROFILE) && NEXT_BOARD_PROFILE
#include "board_profile.inc"
#ifndef NEXT_BOARD_HOST_TEST
#define next_describe next_describe_profiled
#endif
#endif
/**
 * @brief Convert bounded PS timer intervals to rounded microseconds.
 * @param ticks Average per-frame/level timer interval, not a kernel-internal counter.
 * @return Rounded microseconds, within the benchmark's timeout bounds.
 */
static uint32_t microseconds(uint64_t ticks) {
    return (uint32_t)((ticks * UINT64_C(1000000) + COUNTS_PER_SECOND / 2) / COUNTS_PER_SECOND);
}
/**
 * @brief Convert observed elapsed ticks to nominal PL-equivalent cycles.
 * @param ticks Average per-level PS interval, bounded by ten seconds.
 * @return Equivalent 100-MHz elapsed cycles including AXI/polling, not internal cycles.
 */
static uint32_t equivalent_cycles(uint64_t ticks) {
    return (uint32_t)((ticks * NEXT_FABRIC_HZ + COUNTS_PER_SECOND / 2) / COUNTS_PER_SECOND);
}
/**
 * @brief Publish payload before writing its status commit word.
 * @param status RUNNING, exact PASS, FAIL or explicitly unverified COMPLETE.
 * @note Both flushes are required so XSCT cannot observe status before payload.
 */
static void publish(uint32_t status) {
    Xil_DCacheFlushRange((INTPTR)NEXT_MAILBOX, NEXT_MAILBOX_WORDS * 4);
    mailbox()[MB_STATUS] = status;
    Xil_DCacheFlushRange((INTPTR)NEXT_MAILBOX, NEXT_MAILBOX_WORDS * 4);
}
/**
 * @brief Commit a stable error, detail and failing frame through the mailbox.
 * @param error Stable Next board error code.
 * @param detail Level/core mask or record index for diagnosis.
 * @param iteration Zero-based failing frame number.
 * @return The error code, after committing FAIL.
 */
static int fail(uint32_t error, uint32_t detail, uint32_t iteration) {
    mailbox()[MB_ERROR] = error; mailbox()[MB_DETAIL] = detail;
    mailbox()[MB_FAILING_ITERATION] = iteration; publish(NEXT_FAIL);
#if defined(NEXT_BOARD_PROFILE) && NEXT_BOARD_PROFILE
    (void)profile_finish(NEXT_FAIL);
#endif
    return (int)error;
}
/**
 * @brief Compute FNV-1a over bytes without changing the underlying buffer.
 * @param bytes Active image/feature byte stream.
 * @param count Number of active bytes, excluding padding.
 * @return Unsigned 64-bit checksum; actual outputs are also compared byte-for-byte.
 */
static uint64_t digest(const uint8_t* bytes, size_t count) {
    uint64_t hash = UINT64_C(14695981039346656037); size_t index;
    for (index = 0; index < count; ++index) hash = (hash ^ bytes[index]) * UINT64_C(1099511628211);
    return hash;
}
/**
 * @brief Poison output and an aligned 64-byte post-write guard before PL starts.
 * @param output Disjoint cache-line-aligned DDR destination.
 * @param bytes Maximum active byte count; image writes round up to eight bytes.
 * @param mode Legacy preserves the old redundant invalidate for measured A/B tests.
 * @param prep_ticks Accumulates CPU poison-fill time, excluding cache operations.
 * @param cache_ticks Accumulates cache maintenance time for this destination.
 * @note The confirmed standalone_v6_8 BSP flush writes back AND invalidates L1/L2,
 *       with a completion barrier; no CPU output access occurs until PL finishes.
 */
static void prepare_output(void* output, uint32_t bytes, uint32_t mode,
                           uint64_t* prep_ticks, uint64_t* cache_ticks) {
    const uint32_t padded = (bytes + 7u) & ~7u;
    const uint32_t flushed = (padded + 64u + 63u) & ~63u;
    uint64_t mark = now_ticks();
    memset(output, 0xA5, flushed);
    *prep_ticks += now_ticks() - mark;
    mark = now_ticks();
    Xil_DCacheFlushRange((INTPTR)output, flushed);
    if (mode == NEXT_MODE_LEGACY) Xil_DCacheInvalidateRange((INTPTR)output, flushed);
    *cache_ticks += now_ticks() - mark;
}
/**
 * @brief Give initially unknown output cache lines to PL before production timing.
 * @note Production never CPU-writes these buffers afterward; only read-only PS
 *       consumers and PL writers own them. Post-DMA invalidation is still required.
 *       Features are CPU-only and are not part of these DMA destinations.
 */
static void initialize_production_outputs(void) {
    Xil_DCacheFlushRange(NEXT_PYRAMID0, NEXT_MAX_PIXELS + 128u);
    Xil_DCacheFlushRange(NEXT_PYRAMID1, NEXT_MAX_PIXELS + 128u);
    Xil_DCacheFlushRange(NEXT_BLURRED, NEXT_MAX_PIXELS + 128u);
    Xil_DCacheFlushRange(NEXT_POINTS, 256u * sizeof(OrbPoint) + 128u);
    Xil_DCacheFlushRange(NEXT_SUMMARY, 128u);
}
/**
 * @brief Check final zero image padding and the 64-byte post-write sentinel.
 * @param output Cache-invalidated output bytes.
 * @param bytes Active output byte count.
 * @param image Nonzero when zero padding is part of the image ABI.
 * @return Nonzero only when padding and the guard are intact.
 */
static int check_guard(const uint8_t* output, uint32_t bytes, int image) {
    const uint32_t padded = (bytes + 7u) & ~7u; uint32_t index;
    if (image) for (index = bytes; index < padded; ++index) if (output[index] != 0) return 0;
    for (index = padded; index < padded + 64; ++index) if (output[index] != 0xA5) return 0;
    return 1;
}
/**
 * @brief Program exact shared image-kernel register offsets validated from HLS RTL.
 * @param base Resize or Gaussian fixed AXI-Lite base address.
 * @param source Flat packed source pixels.
 * @param destination Disjoint packed output.
 * @param level Resize source level or Gaussian current level.
 */
static void configure_image(uint32_t base, const void* source, void* destination, int level) {
    Xil_Out32(base + NEXT_SOURCE, (uint32_t)(UINTPTR)source);
    Xil_Out32(base + NEXT_DESTINATION, (uint32_t)(UINTPTR)destination);
    Xil_Out32(base + NEXT_LEVEL, (uint32_t)level);
}
/**
 * @brief Configure exact FAST/NMS/grid parameters and output ABI for one level.
 * @param raw Current unblurred image, also read by the other two cores.
 * @param level Frozen pyramid level in 0..7.
 * @param points Disjoint cache-aligned selected-point destination.
 * @param summary Disjoint cache-aligned hardware summary destination.
 */
static void configure_front(const void* raw, int level, void* points, void* summary) {
    Xil_Out32(NEXT_FRONT_BASE + NEXT_SOURCE, (uint32_t)(UINTPTR)raw);
    Xil_Out32(NEXT_FRONT_BASE + NEXT_DESTINATION, (uint32_t)(UINTPTR)points);
    Xil_Out32(NEXT_FRONT_BASE + NEXT_FRONT_RESULT, (uint32_t)(UINTPTR)summary);
    Xil_Out32(NEXT_FRONT_BASE + NEXT_WIDTH, (uint32_t)kWidths[level]);
    Xil_Out32(NEXT_FRONT_BASE + NEXT_HEIGHT, (uint32_t)kHeights[level]);
    Xil_Out32(NEXT_FRONT_BASE + NEXT_BUDGET, (uint32_t)kBudgets[level]);
    Xil_Out32(NEXT_FRONT_BASE + NEXT_HIGH, 20);
    Xil_Out32(NEXT_FRONT_BASE + NEXT_LOW, 7);
    Xil_Out32(NEXT_FRONT_BASE + NEXT_DUAL, 1);
    Xil_Out32(NEXT_FRONT_BASE + NEXT_CAPACITY, 256);
}
/**
 * @brief Poll all launched cores and capture each completion exactly once.
 * @param active Bit mask: FAST=1, resize=2, Gaussian=4.
 * @param starts Per-core launch timestamps, in the same core order.
 * @param elapsed Receives PS-observed launch-to-done ticks, including AXI/polling.
 * @return Zero on completion, or a timeout mask after ten seconds.
 * @note ap_done is clear-on-read; completed cores are not read again in this loop.
 */
static uint32_t wait_cores(uint32_t active, const uint64_t starts[3], uint64_t elapsed[3]) {
    const uint64_t begin = now_ticks(); uint32_t pending = active; int core;
    while (pending) {
        for (core = 0; core < 3; ++core) if ((pending & (1u << core)) &&
            (Xil_In32(kBases[core] + NEXT_CTRL) & 2u)) {
            elapsed[core] = now_ticks() - starts[core]; pending &= ~(1u << core);
        }
        if (now_ticks() - begin >= UINT64_C(10) * COUNTS_PER_SECOND) return pending;
    }
    return 0;
}
/**
 * @brief Validate downloaded PGM, all raw/blur reference bytes and workspace bounds.
 * @return Stable input/workspace error, or zero.
 * @note Reference-upload hashes are checked once; actual images are memcmp'd every frame.
 */
static int validate_inputs(void) {
    const char header[] = "P5\n960 720\n255\n";
    const uint8_t* pgm = (const uint8_t*)(UINTPTR)NEXT_INPUT_PGM;
    const uint8_t* raw = (const uint8_t*)(UINTPTR)NEXT_REFERENCE_RAW;
    const uint8_t* blur = (const uint8_t*)(UINTPTR)NEXT_REFERENCE_BLUR; int level;
    if (NEXT_PROGRAM_END >= NEXT_MAILBOX) return ERR_WORKSPACE;
    Xil_DCacheInvalidateRange((INTPTR)pgm, NEXT_MAX_PIXELS + 15);
    if (memcmp(pgm, header, 15)) return ERR_INPUT;
    memcpy((void*)(UINTPTR)NEXT_ALIGNED_INPUT, pgm + 15, NEXT_MAX_PIXELS);
    Xil_DCacheFlushRange(NEXT_ALIGNED_INPUT, NEXT_MAX_PIXELS);
    Xil_DCacheInvalidateRange((INTPTR)raw, NEXT_REFERENCE_PIXELS);
    Xil_DCacheInvalidateRange((INTPTR)blur, NEXT_REFERENCE_PIXELS);
    for (level = 0; level < 8; ++level) {
        const size_t pixels = (size_t)kWidths[level] * kHeights[level];
        if (digest(raw, pixels) != kExpectedImageDigests[level] ||
            digest(blur, pixels) != kExpectedBlurDigests[level]) return ERR_REFERENCE;
        raw += pixels; blur += pixels;
    }
    return 0;
}
/**
 * @brief Run overlapped three-core stages and exact PS descriptors for an eight-level frame.
 * @param core_ticks Accumulates per-core, per-level PS-observed intervals.
 * @param backend_ticks Accumulates PS descriptor computation by level.
 * @param config_ticks Accumulates register programming, excluding cache preparation.
 * @param stage_ticks Accumulates poison-fill, cache and aggregate PL-wait by level.
 * @param mode Legacy/optimized verified mode, or explicitly unverified production.
 * @param verify_ticks Accumulates reference comparisons, guards and output hashing.
 * @param candidates Receives total raw FAST candidates; selected receives features.
 * @param selected Receives all eight-level feature count.
 * @param output_digest Receives ordered feature-record digest aggregate.
 * @param detail Receives level (high byte) and first useful mismatch index or core mask.
 * @return Stable error, or zero. Buffer ownership changes only after all readers finish.
 */
static int run_frame(uint64_t core_ticks[3][8], uint64_t backend_ticks[8],
                     uint64_t stage_ticks[3][8], uint32_t mode,
                     uint64_t* config_ticks, uint64_t* verify_ticks,
                     uint32_t* candidates, uint32_t* selected,
                     uint64_t* output_digest, uint32_t* detail) {
    const uint8_t* current = (const uint8_t*)(UINTPTR)NEXT_ALIGNED_INPUT;
    const uint8_t* reference_raw = (const uint8_t*)(UINTPTR)NEXT_REFERENCE_RAW;
    const uint8_t* reference_blur = (const uint8_t*)(UINTPTR)NEXT_REFERENCE_BLUR;
    uint8_t* blurred = (uint8_t*)(UINTPTR)NEXT_BLURRED;
    OrbPoint* points = (OrbPoint*)(UINTPTR)NEXT_POINTS;
    Fastv2Summary* summary = (Fastv2Summary*)(UINTPTR)NEXT_SUMMARY;
    NextFeature* features = (NextFeature*)(UINTPTR)NEXT_FEATURES;
    uint64_t aggregate = UINT64_C(14695981039346656037); int level;
    *candidates = *selected = 0;
    for (level = 0; level < 8; ++level) {
        const uint32_t pixels = (uint32_t)(kWidths[level] * kHeights[level]);
        const int resize_active = level < 7;
        const uint32_t next_pixels = resize_active ? (uint32_t)(kWidths[level+1] * kHeights[level+1]) : 0;
        uint8_t* next = (uint8_t*)(UINTPTR)((level & 1) ? NEXT_PYRAMID1 : NEXT_PYRAMID0);
        uint64_t starts[3] = {0,0,0}, elapsed[3] = {0,0,0}, mark;
        uint32_t active = resize_active ? 7u : 5u; int core, index, status;
        *detail = (uint32_t)level << 24;
        for (core = 0; core < 3; ++core) if ((active & (1u << core)) &&
            !(Xil_In32(kBases[core] + NEXT_CTRL) & 4u)) { *detail |= 1u << core; return ERR_IDLE; }
        if (mode != NEXT_MODE_PRODUCTION) {
            prepare_output(blurred, pixels, mode, &stage_ticks[0][level], &stage_ticks[1][level]);
            prepare_output(points, 256 * sizeof(*points), mode, &stage_ticks[0][level], &stage_ticks[1][level]);
            prepare_output(summary, sizeof(*summary), mode, &stage_ticks[0][level], &stage_ticks[1][level]);
            if (resize_active) prepare_output(next, next_pixels, mode, &stage_ticks[0][level], &stage_ticks[1][level]);
        }
        mark = now_ticks();
        /* Optimized sources are read-only: input is flushed once at upload,
           subsequent raw levels are PL-written and never dirtied by PS. */
        if (mode == NEXT_MODE_LEGACY) Xil_DCacheFlushRange((INTPTR)current, (pixels + 63u) & ~63u);
        stage_ticks[1][level] += now_ticks() - mark;
        mark = now_ticks();
        configure_front(current, level, points, summary);
        configure_image(NEXT_GAUSSIAN_BASE, current, blurred, level);
        if (resize_active) configure_image(NEXT_RESIZE_BASE, current, next, level);
        *config_ticks += now_ticks() - mark;
        mark = now_ticks();
        for (core = 0; core < 3; ++core) if (active & (1u << core)) {
            starts[core] = now_ticks(); Xil_Out32(kBases[core] + NEXT_CTRL, 1);
        }
        { const uint32_t timeout = wait_cores(active, starts, elapsed);
          if (timeout) { mailbox()[MB_PENDING_CORE_MASK] = timeout; *detail |= timeout; return ERR_TIMEOUT; } }
        stage_ticks[2][level] += now_ticks() - mark;
        for (core = 0; core < 3; ++core) if (active & (1u << core)) {
            core_ticks[core][level] += elapsed[core];
            status = (int)Xil_In32(kBases[core] + NEXT_RETURN);
            if (status) { *detail |= ((uint32_t)core << 16) | ((uint32_t)status & 65535u); return ERR_RETURN; }
        }
        /* Output invalidation/cache preparation count as processing overhead. */
        mark = now_ticks();
        /* Verified resize output was invalidated at the preceding level for
           its guard check. Production defers invalidation until CPU consumption.
           The legacy path deliberately preserves the original cold-raw policy. */
        if (mode != NEXT_MODE_VERIFIED) Xil_DCacheInvalidateRange((INTPTR)current, (pixels + 63u) & ~63u);
        Xil_DCacheInvalidateRange((INTPTR)blurred, (pixels + 127u) & ~63u);
        Xil_DCacheInvalidateRange((INTPTR)points, 256 * sizeof(*points) + 64);
        Xil_DCacheInvalidateRange((INTPTR)summary, sizeof(*summary) + 64);
        if (resize_active && mode != NEXT_MODE_PRODUCTION) Xil_DCacheInvalidateRange((INTPTR)next, (next_pixels + 127u) & ~63u);
        stage_ticks[1][level] += now_ticks() - mark;
        /* Compute descriptors before reference scans can warm raw/blur caches. */
        if (summary->selected_count < 0 || summary->selected_count > 256) return ERR_SUMMARY;
        mark = now_ticks();
        status = next_describe(current, blurred, kWidths[level], kHeights[level], points,
                               summary->selected_count, level, features, 256);
        backend_ticks[level] += now_ticks() - mark;
        if (status) { *detail |= (uint32_t)status & 0xFFFFu; return ERR_BACKEND; }
        if (mode != NEXT_MODE_PRODUCTION) {
            mark = now_ticks();
            if (memcmp(current, reference_raw, pixels)) return ERR_RAW;
            if (memcmp(blurred, reference_blur, pixels)) return ERR_BLUR;
            if (!check_guard(blurred, pixels, 1) || !check_guard((const uint8_t*)points, 256*sizeof(*points), 0) ||
                !check_guard((const uint8_t*)summary, sizeof(*summary), 0) ||
                (resize_active && !check_guard(next, next_pixels, 1))) return ERR_GUARD;
            if (memcmp(summary, &kExpectedSummaries[level], sizeof(*summary))) return ERR_SUMMARY;
            if (summary->selected_count < 0 || summary->selected_count > 256) return ERR_SUMMARY;
            for (index = 0; index < summary->selected_count; ++index)
                if (memcmp(&points[index], &kExpectedPoints[level][index], sizeof(*points))) {
                    *detail |= (uint32_t)index; return ERR_POINTS;
                }
            /* Detect partial/no output, including writes beyond selected_count. */
            for (index = summary->selected_count * (int)sizeof(*points); index < 256*(int)sizeof(*points); ++index)
                if (((const uint8_t*)points)[index] != 0xA5) { *detail |= (uint32_t)index; return ERR_GUARD; }
            for (index = 0; index < summary->selected_count; ++index)
                if (memcmp(&features[index], &kExpectedFeatures[level][index], sizeof(*features))) {
                    *detail |= (uint32_t)index; return ERR_FEATURE;
                }
            aggregate = (aggregate ^ digest((const uint8_t*)features, (size_t)summary->selected_count * sizeof(*features))) * UINT64_C(1099511628211);
            *verify_ticks += now_ticks() - mark;
        }
        *candidates += (uint32_t)summary->candidate_count;
        *selected += (uint32_t)summary->selected_count;
        reference_raw += pixels; reference_blur += pixels;
        if (resize_active) current = next;
    }
    *output_digest = mode == NEXT_MODE_PRODUCTION ? 0 : aggregate; return 0;
}
#include "board_pipeline.inc"
/**
 * @brief Run requested frames and commit mode/schedule-tagged schema-5 averages.
 * @return Zero for PASS, or a stable failure code. Terminal results remain readable.
 * @note Processing includes cache maintenance, register setup, PL waits and PS
 *       descriptors; it excludes only reference validation/comparison/hash time.
 *       Production skips poison and output checks and publishes COMPLETE, never PASS.
 *       Wall time includes checks in verified modes. Mocks never establish board FPS.
 */
int main(void) {
    volatile uint32_t* result = mailbox(); uint32_t iterations = 1, iteration, index, detail = 0;
    uint32_t candidates = 0, selected = 0, mode = NEXT_MODE_VERIFIED, schedule = NEXT_SCHEDULE_SERIAL;
    uint64_t cores[3][8] = {{0}}, backend[8] = {0}, config = 0, verify = 0;
    uint64_t stages[3][8] = {{0}};
    uint64_t wall = 0, process = 0, minimum = UINT64_MAX, maximum = 0, signature = 0;
    int error;
#if defined(NEXT_BOARD_PROFILE) && NEXT_BOARD_PROFILE
    profile_initialize();
#endif
    Xil_DCacheInvalidateRange(NEXT_MAILBOX, NEXT_MAILBOX_WORDS * 4);
    if (result[MB_COMMAND] == NEXT_COMMAND_MAGIC) {
        mode = result[MB_MODE];
        schedule = result[MB_SCHEDULE];
        if (result[MB_ITERATIONS] >= 1 && result[MB_ITERATIONS] <= 1000) iterations = result[MB_ITERATIONS];
    }
    for (index = 0; index < NEXT_MAILBOX_WORDS; ++index) result[index] = 0;
    result[MB_MAGIC] = NEXT_RESULT_MAGIC; result[MB_SCHEMA] = NEXT_SCHEMA;
    result[MB_ITERATIONS] = iterations; result[MB_TIMER_HZ] = (uint32_t)COUNTS_PER_SECOND;
    result[MB_MODE] = mode;
    result[MB_SCHEDULE] = schedule;
    result[MB_PL_OBSERVATION_UPPER_BOUND] = schedule == NEXT_SCHEDULE_PIPELINE;
    result[MB_FABRIC_HZ] = NEXT_FABRIC_HZ; publish(NEXT_RUNNING);
    if (mode > NEXT_MODE_PRODUCTION || schedule > NEXT_SCHEDULE_PIPELINE ||
        (schedule == NEXT_SCHEDULE_PIPELINE && mode == NEXT_MODE_LEGACY)) return fail(ERR_COMMAND, (schedule << 16) | mode, 0);
    error = validate_inputs(); if (error) return fail((uint32_t)error, 0, 0);
    if (mode == NEXT_MODE_PRODUCTION) initialize_production_outputs();
    if (mode == NEXT_MODE_PRODUCTION && schedule == NEXT_SCHEDULE_PIPELINE) initialize_pipeline_outputs();
    for (iteration = 0; iteration < iterations; ++iteration) {
#if defined(NEXT_BOARD_PROFILE) && NEXT_BOARD_PROFILE
        profile_begin(backend,stages,config);
#endif
        const uint64_t begin = now_ticks(), previous_verify = verify;
        uint64_t duration, processing;
        error = schedule == NEXT_SCHEDULE_PIPELINE ?
            run_pipeline_frame(cores, backend, stages, mode, &config, &verify, &candidates, &selected, &signature, &detail) :
            run_frame(cores, backend, stages, mode, &config, &verify, &candidates, &selected, &signature, &detail);
        if (error) return fail((uint32_t)error, detail, iteration);
        duration = now_ticks() - begin; processing = duration - (verify - previous_verify);
#if defined(NEXT_BOARD_PROFILE) && NEXT_BOARD_PROFILE
        if (profile_record(processing,duration,candidates,selected,backend,stages,config))
            return fail(ERR_COMMAND,0x50524F46u,iteration);
#endif
        wall += duration; process += processing;
        if (processing < minimum) minimum = processing;
        if (processing > maximum) maximum = processing;
        result[MB_COMPLETED] = iteration + 1; publish(NEXT_RUNNING);
    }
    result[MB_CANDIDATES] = candidates; result[MB_SELECTED] = selected;
    result[MB_VERIFIED_FRAMES] = mode == NEXT_MODE_PRODUCTION ? 0 : iterations;
    result[MB_PROCESS_US] = microseconds(process / iterations);
    result[MB_FPS_MILLI] = result[MB_PROCESS_US] ? (uint32_t)(UINT64_C(1000000000) / result[MB_PROCESS_US]) : 0;
    result[MB_WALL_US] = microseconds(wall / iterations);
    result[MB_VERIFY_US] = microseconds(verify / iterations);
    result[MB_CONFIG_US] = microseconds(config / iterations);
    result[MB_MIN_US] = microseconds(minimum); result[MB_MAX_US] = microseconds(maximum);
    result[MB_DIGEST_HI] = (uint32_t)(signature >> 32); result[MB_DIGEST_LO] = (uint32_t)signature;
    { uint64_t totals[4] = {0,0,0,0}, stage_totals[3] = {0,0,0};
      for (index = 0; index < 8; ++index) {
          result[MB_FRONT_LEVEL + index] = microseconds(cores[0][index] / iterations);
          result[MB_RESIZE_LEVEL + index] = microseconds(cores[1][index] / iterations);
          result[MB_GAUSSIAN_LEVEL + index] = microseconds(cores[2][index] / iterations);
          result[MB_BACKEND_LEVEL + index] = microseconds(backend[index] / iterations);
          result[MB_FRONT_EQ_CYCLES + index] = equivalent_cycles(cores[0][index] / iterations);
          result[MB_RESIZE_EQ_CYCLES + index] = equivalent_cycles(cores[1][index] / iterations);
          result[MB_GAUSSIAN_EQ_CYCLES + index] = equivalent_cycles(cores[2][index] / iterations);
          result[MB_PREP_LEVEL + index] = microseconds(stages[0][index] / iterations);
          result[MB_CACHE_LEVEL + index] = microseconds(stages[1][index] / iterations);
          result[MB_WAIT_LEVEL + index] = microseconds(stages[2][index] / iterations);
          stage_totals[0] += stages[0][index]; stage_totals[1] += stages[1][index];
          stage_totals[2] += stages[2][index];
          totals[0] += cores[0][index]; totals[1] += cores[1][index];
          totals[2] += cores[2][index]; totals[3] += backend[index];
      }
      result[MB_FRONT_US] = microseconds(totals[0] / iterations);
      result[MB_RESIZE_US] = microseconds(totals[1] / iterations);
      result[MB_GAUSSIAN_US] = microseconds(totals[2] / iterations);
      result[MB_BACKEND_US] = microseconds(totals[3] / iterations);
      result[MB_PREP_US] = microseconds(stage_totals[0] / iterations);
      result[MB_CACHE_US] = microseconds(stage_totals[1] / iterations);
      result[MB_WAIT_US] = microseconds(stage_totals[2] / iterations);
      { const uint64_t accounted = stage_totals[0] + stage_totals[1] + stage_totals[2] + config + totals[3];
        if (accounted > process) return fail(ERR_COMMAND, 0x54494D45u, iterations);
        result[MB_OTHER_US] = microseconds((process - accounted) / iterations); }
    }
#if defined(NEXT_BOARD_PROFILE) && NEXT_BOARD_PROFILE
    if (profile_finish(mode == NEXT_MODE_PRODUCTION ? NEXT_COMPLETE_UNVERIFIED : NEXT_PASS))
        return fail(ERR_COMMAND,0x50524F46u,iterations);
#endif
    publish(mode == NEXT_MODE_PRODUCTION ? NEXT_COMPLETE_UNVERIFIED : NEXT_PASS); return 0;
}
