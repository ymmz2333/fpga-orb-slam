/**
 * @file fastv2_benchmark.c
 * @brief Bit-exact and performance benchmark for resize plus fastv2 resize, FAST, NMS and grid selection.
 */

#ifdef FASTV2_PS_HOST_TEST
#include "ps_mock.hpp"
#else
#include "xfastv2_front_hls.h"
#include "xfastv2_resize_hls.h"
#include "xil_cache.h"
#include "xil_printf.h"
#include "xparameters.h"
#include "xtime_l.h"
#endif

#include <stddef.h>
#include <stdint.h>
#include <string.h>

enum {
    kLevels = 8,
    kInputWidth = 960,
    kInputHeight = 720,
    kMaximumPixels = kInputWidth * kInputHeight,
    kSelectedCapacity = 256,
    kPgmHeaderBytes = 15,
    kMaximumBenchmarkIterations = 1000,
    kFabricClockHz = 100000000,
    kMailboxAddress = 0x01000000,
    kInputPgmAddress = 0x02000000,
    kPyramidBuffer0Address = 0x02400000,
    kPyramidBuffer1Address = 0x02600000,
    kAlignedInputAddress = 0x02800000,
    kSelectedAddress = 0x04000000,
    kSummaryAddress = 0x04100000,
    kReferencePyramidAddress = 0x06000000,
    kReferencePixels = 960*720 + 800*600 + 667*500 + 556*417 +
        463*347 + 386*289 + 322*241 + 268*201,
    kMailboxCommandMagic = 0x46563243,
    kMailboxResultMagic = 0x46563252,
    kMailboxSchemaVersion = 2,
};

enum OrbFastMailboxStatus {
    kMailboxEmpty = 0,
    kMailboxRunning = 1,
    kMailboxPass = 2,
    kMailboxFail = 3,
};

enum OrbFastError {
    kErrorNone = 0,
    kErrorMailboxOverlap = 1,
    kErrorInputPgm = 10,
    kErrorInputReference = 11,
    kErrorResizeInitialize = 101,
    kErrorFastInitialize = 102,
    kErrorResizeTimeout = 201,
    kErrorFastTimeout = 202,
    kErrorResizeAccelerator = 203,
    kErrorFastAccelerator = 204,
    kErrorImageDigest = 205,
    kErrorSummary = 206,
    kErrorSelectedRecord = 207,
};

/** @brief One 16-byte selected point, matching the reference record layout. */
typedef struct {
    int32_t x;
    int32_t y;
    int32_t score;
    int32_t tile;
} OrbPoint;

/** @brief Byte-exact 64-byte result emitted by the fastv2 AXI master. */
typedef struct {
    uint32_t version;
    int32_t status;
    int32_t candidate_count;
    int32_t selected_count;
    int32_t cell_side;
    int32_t cell_cols;
    int32_t cell_rows;
    int32_t empty_cells;
    int32_t fallback_cells;
    int32_t tile_cols;
    int32_t tile_rows;
    int32_t tile_width;
    int32_t tile_height;
    uint32_t reserved0;
    uint32_t reserved1;
    uint32_t reserved2;
} Fastv2Summary;

/** @brief Fixed 512-byte result block read directly through JTAG by XSCT. */
typedef struct {
    uint32_t command_magic;
    uint32_t requested_iterations;
    uint32_t result_magic;
    uint32_t schema_version;
    uint32_t status;
    uint32_t error_code;
    uint32_t completed_iterations;
    uint32_t failing_iteration;
    uint32_t timer_hz;
    uint32_t fabric_clock_hz;
    uint32_t candidates;
    uint32_t fast_digest_hi;
    uint32_t fast_digest_lo;
    uint32_t image_digest_hi;
    uint32_t image_digest_lo;
    uint32_t fast_config_avg_us;
    uint32_t fast_wait_avg_us;
    uint32_t fast_wait_min_us;
    uint32_t fast_wait_max_us;
    uint32_t fast_fps_milli;
    uint32_t resize_config_avg_us;
    uint32_t resize_wait_avg_us;
    uint32_t resize_wait_min_us;
    uint32_t resize_wait_max_us;
    uint32_t resize_fps_milli;
    uint32_t pipeline_avg_us;
    uint32_t pipeline_fps_milli;
    uint32_t verification_avg_us;
    uint32_t wall_avg_us;
    uint32_t wall_fps_milli;
    uint32_t total_elapsed_us_hi;
    uint32_t total_elapsed_us_lo;
    uint32_t failure_detail;
    uint32_t reserved[95];
} OrbFastMailbox;

/** @brief Per-frame accumulated accelerator configuration and wait timing. */
typedef struct {
    uint64_t config_total_ticks;
    uint64_t wait_total_ticks;
    uint64_t wait_min_ticks;
    uint64_t wait_max_ticks;
} OrbPerfStats;

typedef char Fastv2SummarySizeMustBe64[(sizeof(Fastv2Summary) == 64) ? 1 : -1];
typedef char OrbPointSizeMustBe16[(sizeof(OrbPoint) == 16) ? 1 : -1];
typedef char OrbMailboxSizeMustBe512[(sizeof(OrbFastMailbox) == 512) ? 1 : -1];
typedef char OrbWorkspaceMustFitDdr[
    ((kSelectedAddress + kSelectedCapacity * sizeof(OrbPoint) - 1) <=
      XPAR_PS7_DDR_0_S_AXI_HIGHADDR)
        ? 1
        : -1];

static const int kWidths[kLevels] = {960, 800, 667, 556, 463, 386, 322, 268};
static const int kHeights[kLevels] = {720, 600, 500, 417, 347, 289, 241, 201};
static const int kBudgets[kLevels] = {217, 181, 151, 126, 105, 87, 73, 60};
#include "fastv2_reference.inc"

typedef char Fastv2SummaryDdrMustFit[
    (kSummaryAddress + kLevels * sizeof(Fastv2Summary) - 1 <=
     XPAR_PS7_DDR_0_S_AXI_HIGHADDR) ? 1 : -1];
typedef char Fastv2ReferenceDdrMustFit[
    (kReferencePyramidAddress + kReferencePixels - 1 <=
     XPAR_PS7_DDR_0_S_AXI_HIGHADDR) ? 1 : -1];

#ifndef FASTV2_PS_HOST_TEST
extern char _end;
#define FASTV2_PROGRAM_END ((UINTPTR)&_end)
#endif

/** @brief Return the fixed DDR command/result mailbox. */
static volatile OrbFastMailbox* benchmark_mailbox(void) {
    return (volatile OrbFastMailbox*)(UINTPTR)kMailboxAddress;
}

/** @brief Return the aligned level-zero input image. */
static const uint8_t* input_pixels(void) {
    return (const uint8_t*)(UINTPTR)kAlignedInputAddress;
}

/** @brief Return one of the two resize ping-pong buffers. */
static uint8_t* pyramid_buffer(int index) {
    return (uint8_t*)(UINTPTR)(index == 0 ? kPyramidBuffer0Address : kPyramidBuffer1Address);
}

/** @brief Return the 64-byte-aligned selected-point output buffer. */
static OrbPoint* selected_buffer(void) {
    return (OrbPoint*)(UINTPTR)kSelectedAddress;
}

/**
 * @brief Return the independent DMA result record for one pyramid level.
 * @param level Valid index from zero through seven.
 * @return Pointer to a cache-line-aligned 64-byte DDR result.
 */
static Fastv2Summary* summary_buffer(int level) {
    return (Fastv2Summary*)(UINTPTR)(kSummaryAddress + level * sizeof(Fastv2Summary));
}

/**
 * @brief Clean and invalidate complete cache lines before a PL output write.
 * @param address Aligned destination, disjoint from all active input buffers.
 * @param bytes Maximum number of bytes the accelerator may write.
 */
static void prepare_dma_output(void* address, uint32_t bytes) {
    const uint32_t aligned_bytes = (bytes + 63u) & ~63u;
    Xil_DCacheFlushRange((INTPTR)address, aligned_bytes);
    Xil_DCacheInvalidateRange((INTPTR)address, aligned_bytes);
}

/** @brief Flush the result mailbox so XSCT observes the latest PS writes. */
static void publish_mailbox(void) {
    Xil_DCacheFlushRange((INTPTR)kMailboxAddress, sizeof(OrbFastMailbox));
}

/** @brief Return the requested iteration count after bounds checking. */
static uint32_t read_requested_iterations(void) {
    volatile OrbFastMailbox* const mailbox = benchmark_mailbox();
    Xil_DCacheInvalidateRange((INTPTR)kMailboxAddress, sizeof(OrbFastMailbox));
    if (mailbox->command_magic == kMailboxCommandMagic &&
        mailbox->requested_iterations >= 1 &&
        mailbox->requested_iterations <= kMaximumBenchmarkIterations) {
        return mailbox->requested_iterations;
    }
    return 1;
}

/** @brief Clear the mailbox and publish the RUNNING state. */
static void initialize_mailbox(uint32_t iterations) {
    volatile OrbFastMailbox* const mailbox = benchmark_mailbox();
    volatile uint32_t* const words = (volatile uint32_t*)mailbox;
    size_t index;
    for (index = 0; index < sizeof(*mailbox) / sizeof(uint32_t); ++index) words[index] = 0;
    mailbox->requested_iterations = iterations;
    mailbox->result_magic = kMailboxResultMagic;
    mailbox->schema_version = kMailboxSchemaVersion;
    mailbox->status = kMailboxRunning;
    mailbox->timer_hz = (uint32_t)COUNTS_PER_SECOND;
    mailbox->fabric_clock_hz = kFabricClockHz;
    publish_mailbox();
}

/** @brief Publish a terminal failure and return its stable error code. */
static int publish_failure(uint32_t error, uint32_t detail, uint32_t iteration) {
    volatile OrbFastMailbox* const mailbox = benchmark_mailbox();
    mailbox->error_code = error;
    mailbox->failure_detail = detail;
    mailbox->failing_iteration = iteration;
    /* Publish payload first; terminal status is the commit marker for XSCT. */
    publish_mailbox();
    mailbox->status = kMailboxFail;
    publish_mailbox();
    return (int)error;
}

/** @brief Convert global-timer ticks to rounded integer microseconds. */
static uint64_t ticks_to_microseconds(uint64_t ticks) {
    return (ticks * UINT64_C(1000000) + COUNTS_PER_SECOND / 2) / COUNTS_PER_SECOND;
}

/** @brief Convert microseconds per frame to frames per second times 1000. */
static uint32_t microseconds_to_milli_fps(uint32_t average_us) {
    if (average_us == 0) return 0;
    return (uint32_t)((UINT64_C(1000000000) + average_us / 2) / average_us);
}

/**
 * @brief Convert PS-observed elapsed ticks to equivalent 100-MHz PL cycles.
 * @param ticks PS global-timer interval, including AXI and polling overhead.
 * @return Rounded equivalent elapsed cycles; not internal kernel cycles.
 */
static uint64_t ticks_to_fabric_cycles(uint64_t ticks) {
    return (ticks * kFabricClockHz + COUNTS_PER_SECOND / 2) / COUNTS_PER_SECOND;
}

/** @brief Reset a frame-level timing accumulator. */
static void initialize_perf_stats(OrbPerfStats* stats) {
    stats->config_total_ticks = 0;
    stats->wait_total_ticks = 0;
    stats->wait_min_ticks = UINT64_MAX;
    stats->wait_max_ticks = 0;
}

/** @brief Accumulate one frame's configuration and accelerator wait times. */
static void record_frame_perf(OrbPerfStats* stats, uint64_t config_ticks, uint64_t wait_ticks) {
    stats->config_total_ticks += config_ticks;
    stats->wait_total_ticks += wait_ticks;
    if (wait_ticks < stats->wait_min_ticks) stats->wait_min_ticks = wait_ticks;
    if (wait_ticks > stats->wait_max_ticks) stats->wait_max_ticks = wait_ticks;
}

/** @brief Append one byte to a 64-bit FNV-1a digest. */
static uint64_t hash_byte(uint64_t hash, uint8_t value) {
    hash ^= value;
    return hash * UINT64_C(1099511628211);
}

/** @brief Append one 32-bit value in little-endian order. */
static uint64_t hash_u32(uint64_t hash, uint32_t value) {
    int byte;
    for (byte = 0; byte < 4; ++byte) hash = hash_byte(hash, (uint8_t)(value >> (8 * byte)));
    return hash;
}

/** @brief Append one 64-bit value in little-endian word order. */
static uint64_t hash_u64(uint64_t hash, uint64_t value) {
    hash = hash_u32(hash, (uint32_t)value);
    return hash_u32(hash, (uint32_t)(value >> 32));
}

/** @brief Hash all active row-major pixels in one pyramid level. */
static uint64_t digest_image(const uint8_t* image, int pixels) {
    uint64_t hash = UINT64_C(14695981039346656037);
    int index;
    for (index = 0; index < pixels; ++index) hash = hash_byte(hash, image[index]);
    return hash;
}

/** @brief Hash ordered 16-byte selected-point records, not raw candidates. */
static uint64_t digest_selected(const OrbPoint* points, int count) {
    uint64_t hash = UINT64_C(14695981039346656037);
    int index;
    for (index = 0; index < count; ++index) {
        hash = hash_u32(hash, (uint32_t)points[index].x);
        hash = hash_u32(hash, (uint32_t)points[index].y);
        hash = hash_u32(hash, (uint32_t)points[index].score);
        hash = hash_u32(hash, (uint32_t)points[index].tile);
    }
    return hash;
}

/**
 * @brief Validate the downloaded PGM and copy its pixels to an aligned buffer.
 * @return Zero when the fixed 960x720 binary-PGM header and payload are valid.
 */
static int validate_input_pgm(void) {
    static const uint8_t expected[kPgmHeaderBytes] = {
        'P', '5', '\n', '9', '6', '0', ' ', '7', '2', '0', '\n', '2', '5', '5', '\n'};
    const uint8_t* const source = (const uint8_t*)(UINTPTR)kInputPgmAddress;
    uint8_t* const aligned = (uint8_t*)(UINTPTR)kAlignedInputAddress;
    int index;
    Xil_DCacheInvalidateRange((INTPTR)kInputPgmAddress, kPgmHeaderBytes + kMaximumPixels);
    for (index = 0; index < kPgmHeaderBytes; ++index) {
        if (source[index] != expected[index]) return -1;
    }
    for (index = 0; index < kMaximumPixels; ++index) {
        aligned[index] = source[kPgmHeaderBytes + index];
    }
    Xil_DCacheFlushRange((INTPTR)kAlignedInputAddress, kMaximumPixels);
    return 0;
}

/**
 * @brief Validate all CPU-generated reference pixels downloaded separately by XSCT.
 * @return Zero only when all eight reference images have the frozen expected digests.
 * @note Actual PL images are compared byte-for-byte in run_frame, not only hashed.
 */
static int validate_reference_pyramid(void) {
    const uint8_t* reference = (const uint8_t*)(UINTPTR)kReferencePyramidAddress;
    int level;
    Xil_DCacheInvalidateRange((INTPTR)reference, kReferencePixels);
    for (level = 0; level < kLevels; ++level) {
        const int pixels = kWidths[level] * kHeights[level];
        if (digest_image(reference, pixels) != kExpectedImageDigests[level]) return -1;
        reference += pixels;
    }
    return 0;
}

/**
 * @brief Poll FAST and an optional concurrent resize until both complete.
 * @param fast_accelerator Active streaming-FAST accelerator.
 * @param resize_accelerator Active resize accelerator when resize_active is nonzero.
 * @param resize_active Nonzero when the next pyramid level is being generated.
 * @param timeout_seconds Shared transaction timeout.
 * @param fast_done Completion timestamp for FAST.
 * @param resize_done Completion timestamp for resize when active.
 * @return Timeout mask: bit zero denotes FAST and bit one denotes resize.
 */
static int wait_for_accelerators(XFastv2_front_hls* fast_accelerator,
                                 XFastv2_resize_hls* resize_accelerator,
                                 int resize_active,
                                 unsigned timeout_seconds,
                                 XTime* fast_done,
                                 XTime* resize_done) {
    XTime start;
    XTime now;
    int fast_complete = 0;
    int resize_complete = resize_active ? 0 : 1;
    XTime_GetTime(&start);
    do {
        if (!fast_complete && XFastv2_front_hls_IsDone(fast_accelerator)) {
            XTime_GetTime(fast_done);
            fast_complete = 1;
        }
        if (!resize_complete && XFastv2_resize_hls_IsDone(resize_accelerator)) {
            XTime_GetTime(resize_done);
            resize_complete = 1;
        }
        if (fast_complete && resize_complete) return 0;
        XTime_GetTime(&now);
    } while ((now - start) < ((XTime)timeout_seconds * (XTime)COUNTS_PER_SECOND));
    return (fast_complete ? 0 : 1) | (resize_complete ? 0 : 2);
}

/**
 * @brief Execute and verify one complete eight-level resize plus FAST frame.
 * @param resize_accelerator Initialized fixed-profile resize driver.
 * @param fast_accelerator Initialized FAST/NMS/grid driver.
 * @param resize_stats Accumulated seven-transition configuration and wait times.
 * @param fast_stats Accumulated eight-level configuration and wait times.
 * @param image_digest Receives the ordered aggregate of level image checksums.
 * @param fast_digest Receives the ordered aggregate of selected-point checksums.
 * @param verification_ticks Accumulates hashing, point checks and output preparation.
 * @param pipeline_ticks Accumulates register setup plus overlapping core execution.
 * @param total_candidates Receives the eight-level raw candidate sum.
 * @param fast_level_ticks Accumulates PS-observed front time for each level.
 * @param resize_level_ticks Accumulates resize time by destination level (L0 zero).
 * @param level_counts Receives the eight per-level candidate counts.
 * @param level_digests Receives ordered selected-point checksums.
 * @param detail Receives level and first failing record/summary-word index.
 * @return Stable OrbFastError code, or kErrorNone on success.
 */
static int run_frame(XFastv2_resize_hls* resize_accelerator,
                     XFastv2_front_hls* fast_accelerator,
                     OrbPerfStats* resize_stats,
                     OrbPerfStats* fast_stats,
                     uint64_t* image_digest,
                     uint64_t* fast_digest,
                     uint64_t* verification_ticks,
                     uint64_t* pipeline_ticks,
                     uint32_t* total_candidates,
                     uint64_t fast_level_ticks[kLevels],
                     uint64_t resize_level_ticks[kLevels],
                     uint32_t level_counts[kLevels],
                     uint64_t level_digests[kLevels],
                     uint32_t* detail) {
    const uint8_t* current_image = input_pixels();
    const uint8_t* reference_image = (const uint8_t*)(UINTPTR)kReferencePyramidAddress;
    OrbPoint* const candidates = selected_buffer();
    uint64_t image_aggregate = UINT64_C(14695981039346656037);
    uint64_t fast_aggregate = UINT64_C(14695981039346656037);
    uint64_t fast_config_ticks = 0;
    uint64_t fast_wait_ticks = 0;
    uint64_t resize_config_ticks = 0;
    uint64_t resize_wait_ticks = 0;
    uint64_t pipeline_frame_ticks = 0;
    uint32_t candidate_sum = 0;
    uint32_t selected_sum = 0;
    int level;

    for (level = 0; level < kLevels; ++level) {
        const int width = kWidths[level];
        const int height = kHeights[level];
        const int active_pixels = width * height;
        const int resize_active = level + 1 < kLevels;
        uint8_t* const next_image = resize_active ? pyramid_buffer(level & 1) : (uint8_t*)0;
        XTime verify_start;
        XTime verify_end;
        XTime config_start;
        XTime config_end;
        XTime stage_start;
        XTime fast_wait_start;
        XTime fast_done;
        XTime resize_wait_start = 0;
        XTime resize_done = 0;
        uint64_t observed_image_digest;
        uint64_t observed_fast_digest;
        Fastv2Summary* const summary = summary_buffer(level);
        int selected_count;
        int status;

        XTime_GetTime(&verify_start);
        Xil_DCacheInvalidateRange((INTPTR)current_image, (u32)active_pixels);
        observed_image_digest = digest_image(current_image, active_pixels);
        if (observed_image_digest != kExpectedImageDigests[level]) {
            *detail = ((uint32_t)level << 24) | ((uint32_t)observed_image_digest & 0x00ffffffu);
            return kErrorImageDigest;
        }
        if (memcmp(current_image, reference_image, (size_t)active_pixels) != 0) {
            int pixel;
            for (pixel = 0; pixel < active_pixels; ++pixel) {
                if (current_image[pixel] != reference_image[pixel]) break;
            }
            *detail = ((uint32_t)level << 24) | (uint32_t)pixel;
            return kErrorImageDigest;
        }
        reference_image += active_pixels;
        XTime_GetTime(&verify_end);
        *verification_ticks += verify_end - verify_start;
        image_aggregate = hash_u64(image_aggregate, observed_image_digest);

        XTime_GetTime(&verify_start);
        summary->version = 0;
        summary->status = -1;
        /* Repeated identical frames must not pass using stale DDR outputs. */
        memset(candidates, 0xa5, kSelectedCapacity * sizeof(OrbPoint));
        prepare_dma_output(summary, sizeof(*summary));
        prepare_dma_output(candidates, kSelectedCapacity * sizeof(OrbPoint));
        if (resize_active) {
            memset(next_image, 0xa5, kWidths[level + 1] * kHeights[level + 1]);
            prepare_dma_output(next_image, kWidths[level + 1] * kHeights[level + 1]);
        }
        XTime_GetTime(&verify_end);
        *verification_ticks += verify_end - verify_start;

        /* Pipeline time includes both cores' PS register configuration. */
        XTime_GetTime(&stage_start);
        XTime_GetTime(&config_start);
        XFastv2_front_hls_Set_image_r(fast_accelerator, (u32)(UINTPTR)current_image);
        XFastv2_front_hls_Set_selected(fast_accelerator, (u32)(UINTPTR)candidates);
        XFastv2_front_hls_Set_result(fast_accelerator, (u32)(UINTPTR)summary);
        XFastv2_front_hls_Set_budget(fast_accelerator, kBudgets[level]);
        XFastv2_front_hls_Set_width(fast_accelerator, width);
        XFastv2_front_hls_Set_height(fast_accelerator, height);
        XFastv2_front_hls_Set_high_threshold(fast_accelerator, 20);
        XFastv2_front_hls_Set_low_threshold(fast_accelerator, 7);
        XFastv2_front_hls_Set_dual_threshold(fast_accelerator, 1);
        XFastv2_front_hls_Set_selected_capacity(fast_accelerator, kSelectedCapacity);
        XTime_GetTime(&config_end);
        fast_config_ticks += config_end - config_start;

        if (resize_active) {
            XTime_GetTime(&config_start);
            XFastv2_resize_hls_Set_source(resize_accelerator, (u32)(UINTPTR)current_image);
            XFastv2_resize_hls_Set_destination(resize_accelerator, (u32)(UINTPTR)next_image);
            XFastv2_resize_hls_Set_source_level(resize_accelerator, level);
            XTime_GetTime(&config_end);
            resize_config_ticks += config_end - config_start;
        }

        XTime_GetTime(&fast_wait_start);
        XFastv2_front_hls_Start(fast_accelerator);
        if (resize_active) {
            XTime_GetTime(&resize_wait_start);
            XFastv2_resize_hls_Start(resize_accelerator);
        }
        status = wait_for_accelerators(
            fast_accelerator, resize_accelerator, resize_active, 30,
            &fast_done, &resize_done);
        if (status & 1) {
            *detail = (uint32_t)level;
            return kErrorFastTimeout;
        }
        if (status & 2) {
            *detail = (uint32_t)(level + 1);
            return kErrorResizeTimeout;
        }
        fast_wait_ticks += fast_done - fast_wait_start;
        fast_level_ticks[level] += fast_done - fast_wait_start;
        if (resize_active) {
            resize_wait_ticks += resize_done - resize_wait_start;
            resize_level_ticks[level + 1] += resize_done - resize_wait_start;
        }
        pipeline_frame_ticks +=
            ((resize_active && resize_done > fast_done) ? resize_done : fast_done) - stage_start;

        status = (int32_t)XFastv2_front_hls_Get_return(fast_accelerator);
        if (status != 0) {
            *detail = ((uint32_t)level << 16) | ((uint32_t)status & 0xffffu);
            return kErrorFastAccelerator;
        }
        if (resize_active) {
            status = (int32_t)XFastv2_resize_hls_Get_return(resize_accelerator);
            if (status != 0) {
                *detail = ((uint32_t)(level + 1) << 16) | ((uint32_t)status & 0xffffu);
                return kErrorResizeAccelerator;
            }
        }

        XTime_GetTime(&verify_start);
        Xil_DCacheInvalidateRange((INTPTR)summary, sizeof(*summary));
        benchmark_mailbox()->reserved[level] = (uint32_t)summary->candidate_count;
        benchmark_mailbox()->reserved[41 + level] = (uint32_t)summary->selected_count;
        /* Compare all 64 bytes: layout version, counts, grid/tile and reserves. */
        if (memcmp(summary, &kExpectedSummaries[level], sizeof(*summary)) != 0) {
            const uint32_t* actual_words = (const uint32_t*)summary;
            const uint32_t* expected_words = (const uint32_t*)&kExpectedSummaries[level];
            int word;
            for (word = 0; word < 16; ++word) {
                if (actual_words[word] != expected_words[word]) break;
            }
            *detail = ((uint32_t)level << 24) | (uint32_t)word;
            return kErrorSummary;
        }
        selected_count = summary->selected_count;
        if (selected_count < 0 || selected_count > kSelectedCapacity) {
            *detail = (uint32_t)level << 24;
            return kErrorSummary;
        }
        Xil_DCacheInvalidateRange((INTPTR)candidates, kSelectedCapacity * sizeof(OrbPoint));
        observed_fast_digest = digest_selected(candidates, selected_count);
        level_counts[level] = (uint32_t)summary->candidate_count;
        level_digests[level] = observed_fast_digest;
        benchmark_mailbox()->reserved[8 + 2 * level] = (uint32_t)(observed_fast_digest >> 32);
        benchmark_mailbox()->reserved[9 + 2 * level] = (uint32_t)observed_fast_digest;
        benchmark_mailbox()->reserved[41 + level] = (uint32_t)selected_count;
        if (memcmp(candidates, kExpectedPoints[level],
                   (size_t)selected_count * sizeof(OrbPoint)) != 0) {
            int point;
            for (point = 0; point < selected_count; ++point) {
                if (memcmp(&candidates[point], &kExpectedPoints[level][point],
                           sizeof(OrbPoint)) != 0) break;
            }
            *detail = ((uint32_t)level << 24) | (uint32_t)point;
            return kErrorSelectedRecord;
        }
        XTime_GetTime(&verify_end);
        *verification_ticks += verify_end - verify_start;
        candidate_sum += (uint32_t)summary->candidate_count;
        selected_sum += (uint32_t)selected_count;
        fast_aggregate = hash_u64(fast_aggregate, observed_fast_digest);
        current_image = next_image;
    }

    record_frame_perf(fast_stats, fast_config_ticks, fast_wait_ticks);
    record_frame_perf(resize_stats, resize_config_ticks, resize_wait_ticks);
    *pipeline_ticks += pipeline_frame_ticks;
    *image_digest = image_aggregate;
    *fast_digest = fast_aggregate;
    *total_candidates = candidate_sum;
    benchmark_mailbox()->reserved[40] = selected_sum;
    return kErrorNone;
}

/** @brief Publish averaged performance and the last verified frame summary. */
static void finalize_mailbox(uint32_t iterations,
                             const OrbPerfStats* resize_stats,
                             const OrbPerfStats* fast_stats,
                             uint64_t image_digest,
                             uint64_t fast_digest,
                             uint64_t verification_ticks,
                             uint64_t pipeline_ticks,
                             uint64_t wall_ticks,
                             uint32_t total_candidates,
                             const uint64_t fast_level_ticks[kLevels],
                             const uint64_t resize_level_ticks[kLevels],
                             const uint32_t level_counts[kLevels],
                             const uint64_t level_digests[kLevels]) {
    volatile OrbFastMailbox* const mailbox = benchmark_mailbox();
    const uint64_t fast_config_avg = fast_stats->config_total_ticks / iterations;
    const uint64_t fast_wait_avg = fast_stats->wait_total_ticks / iterations;
    const uint64_t resize_config_avg = resize_stats->config_total_ticks / iterations;
    const uint64_t resize_wait_avg = resize_stats->wait_total_ticks / iterations;
    const uint64_t pipeline_avg = pipeline_ticks / iterations;
    const uint64_t total_us = ticks_to_microseconds(wall_ticks);
    int level;

    mailbox->candidates = total_candidates;
    mailbox->fast_digest_hi = (uint32_t)(fast_digest >> 32);
    mailbox->fast_digest_lo = (uint32_t)fast_digest;
    mailbox->image_digest_hi = (uint32_t)(image_digest >> 32);
    mailbox->image_digest_lo = (uint32_t)image_digest;
    mailbox->fast_config_avg_us = (uint32_t)ticks_to_microseconds(fast_config_avg);
    mailbox->fast_wait_avg_us = (uint32_t)ticks_to_microseconds(fast_wait_avg);
    mailbox->fast_wait_min_us = (uint32_t)ticks_to_microseconds(fast_stats->wait_min_ticks);
    mailbox->fast_wait_max_us = (uint32_t)ticks_to_microseconds(fast_stats->wait_max_ticks);
    mailbox->fast_fps_milli = microseconds_to_milli_fps(
        mailbox->fast_config_avg_us + mailbox->fast_wait_avg_us);
    mailbox->resize_config_avg_us = (uint32_t)ticks_to_microseconds(resize_config_avg);
    mailbox->resize_wait_avg_us = (uint32_t)ticks_to_microseconds(resize_wait_avg);
    mailbox->resize_wait_min_us = (uint32_t)ticks_to_microseconds(resize_stats->wait_min_ticks);
    mailbox->resize_wait_max_us = (uint32_t)ticks_to_microseconds(resize_stats->wait_max_ticks);
    mailbox->resize_fps_milli = microseconds_to_milli_fps(
        mailbox->resize_config_avg_us + mailbox->resize_wait_avg_us);
    mailbox->pipeline_avg_us = (uint32_t)ticks_to_microseconds(pipeline_avg);
    mailbox->pipeline_fps_milli = microseconds_to_milli_fps(mailbox->pipeline_avg_us);
    mailbox->verification_avg_us =
        (uint32_t)ticks_to_microseconds(verification_ticks / iterations);
    mailbox->wall_avg_us = (uint32_t)ticks_to_microseconds(wall_ticks / iterations);
    mailbox->wall_fps_milli = microseconds_to_milli_fps(mailbox->wall_avg_us);
    mailbox->total_elapsed_us_hi = (uint32_t)(total_us >> 32);
    mailbox->total_elapsed_us_lo = (uint32_t)total_us;
    for (level = 0; level < kLevels; ++level) {
        mailbox->reserved[level] = level_counts[level];
        mailbox->reserved[8 + 2 * level] = (uint32_t)(level_digests[level] >> 32);
        mailbox->reserved[9 + 2 * level] = (uint32_t)level_digests[level];
        mailbox->reserved[24 + level] =
            (uint32_t)ticks_to_microseconds(fast_level_ticks[level] / iterations);
        uint64_t cycles;
        mailbox->reserved[32 + level] = level == 0 ? 0u :
            (uint32_t)ticks_to_microseconds(resize_level_ticks[level] / iterations);
        cycles = ticks_to_fabric_cycles(fast_level_ticks[level] / iterations);
        mailbox->reserved[49 + 2 * level] = (uint32_t)(cycles >> 32);
        mailbox->reserved[50 + 2 * level] = (uint32_t)cycles;
        cycles = ticks_to_fabric_cycles(resize_level_ticks[level] / iterations);
        mailbox->reserved[65 + 2 * level] = (uint32_t)(cycles >> 32);
        mailbox->reserved[66 + 2 * level] = (uint32_t)cycles;
    }
    /* A read of PASS must never precede writeback of the result payload. */
    publish_mailbox();
    mailbox->status = kMailboxPass;
    publish_mailbox();
}

/**
 * @brief Run 1..1000 verified frames and commit schema-2 results to fixed DDR.
 * @return Zero on PASS, otherwise a stable OrbFastError diagnostic code.
 * @note Hardware latency cannot be inferred from the offline mocked timer.
 */
int main(void) {
    volatile OrbFastMailbox* const mailbox = benchmark_mailbox();
    XFastv2_resize_hls resize_accelerator;
    XFastv2_front_hls fast_accelerator;
    OrbPerfStats resize_stats;
    OrbPerfStats fast_stats;
    uint64_t image_digest = 0;
    uint64_t fast_digest = 0;
    uint64_t verification_ticks = 0;
    uint64_t pipeline_ticks = 0;
    uint64_t wall_ticks = 0;
    uint64_t fast_level_ticks[kLevels] = {0};
    uint64_t resize_level_ticks[kLevels] = {0};
    uint32_t level_counts[kLevels] = {0};
    uint64_t level_digests[kLevels] = {0};
    uint32_t total_candidates = 0;
    uint32_t iterations;
    uint32_t iteration;
    uint32_t detail = 0;
    int status;

    if (FASTV2_PROGRAM_END >= (UINTPTR)kMailboxAddress) {
        return publish_failure(kErrorMailboxOverlap, (uint32_t)FASTV2_PROGRAM_END, 0);
    }
    iterations = read_requested_iterations();
    initialize_mailbox(iterations);
    if (validate_input_pgm() != 0) return publish_failure(kErrorInputPgm, kInputPgmAddress, 0);
    if (validate_reference_pyramid() != 0) {
        return publish_failure(kErrorInputReference, kReferencePyramidAddress, 0);
    }

    status = XFastv2_resize_hls_Initialize(&resize_accelerator, XPAR_FASTV2_RESIZE_DEVICE_ID);
    if (status != XST_SUCCESS) return publish_failure(kErrorResizeInitialize, (uint32_t)status, 0);
    status = XFastv2_front_hls_Initialize(
        &fast_accelerator, XPAR_FASTV2_FRONT_DEVICE_ID);
    if (status != XST_SUCCESS) return publish_failure(kErrorFastInitialize, (uint32_t)status, 0);

    initialize_perf_stats(&resize_stats);
    initialize_perf_stats(&fast_stats);
    for (iteration = 1; iteration <= iterations; ++iteration) {
        XTime frame_start;
        XTime frame_end;
        const uint64_t previous_pipeline_ticks = pipeline_ticks;
        uint32_t frame_pipeline_us;
        XTime_GetTime(&frame_start);
        detail = 0;
        status = run_frame(
            &resize_accelerator, &fast_accelerator, &resize_stats, &fast_stats,
            &image_digest, &fast_digest, &verification_ticks, &pipeline_ticks,
            &total_candidates, fast_level_ticks, resize_level_ticks,
            level_counts, level_digests, &detail);
        XTime_GetTime(&frame_end);
        wall_ticks += frame_end - frame_start;
        if (status != kErrorNone) return publish_failure((uint32_t)status, detail, iteration);
        frame_pipeline_us = (uint32_t)ticks_to_microseconds(pipeline_ticks - previous_pipeline_ticks);
        if (iteration == 1 || frame_pipeline_us < mailbox->reserved[81]) {
            mailbox->reserved[81] = frame_pipeline_us;
        }
        if (frame_pipeline_us > mailbox->reserved[82]) mailbox->reserved[82] = frame_pipeline_us;
        mailbox->completed_iterations = iteration;
        if ((iteration % 10u) == 0u || iteration == iterations) publish_mailbox();
    }

    finalize_mailbox(
        iterations, &resize_stats, &fast_stats, image_digest, fast_digest,
        verification_ticks, pipeline_ticks, wall_ticks, total_candidates,
        fast_level_ticks, resize_level_ticks, level_counts, level_digests);
    xil_printf("FASTV2_PASS iterations=%d candidates=%d pipeline_us=%d\r\n",
               iterations, total_candidates, mailbox->pipeline_avg_us);
    return 0;
}
