#ifndef NEXT_BOARD_CONTRACT_H
#define NEXT_BOARD_CONTRACT_H
#include <stdint.h>
#include "next_backend.h"
/** Fixed PS-visible MMIO bases; Vivado assigns the same three 64-KiB windows. */
enum { NEXT_FRONT_BASE = 0x43C00000, NEXT_RESIZE_BASE = 0x43C10000,
       NEXT_GAUSSIAN_BASE = 0x43C20000 };
/** Register offsets confirmed from the frozen Vivado HLS 2018.3 AXI-Lite RTL. */
enum { NEXT_CTRL = 0x00, NEXT_RETURN = 0x10, NEXT_SOURCE = 0x18,
       NEXT_DESTINATION = 0x20, NEXT_LEVEL = 0x28,
       NEXT_FRONT_RESULT = 0x28, NEXT_WIDTH = 0x30, NEXT_HEIGHT = 0x38,
       NEXT_BUDGET = 0x40, NEXT_HIGH = 0x48, NEXT_LOW = 0x50,
       NEXT_DUAL = 0x58, NEXT_CAPACITY = 0x60 };
/** Disjoint, cache-line-aligned DDR workspaces, below the confirmed 1-GiB limit. */
enum { NEXT_MAILBOX = 0x01000000, NEXT_INPUT_PGM = 0x02000000,
       NEXT_PYRAMID0 = 0x02400000, NEXT_PYRAMID1 = 0x02600000,
       NEXT_ALIGNED_INPUT = 0x02800000, NEXT_BLURRED = 0x02A00000,
       NEXT_POINTS = 0x04000000, NEXT_SUMMARY = 0x04100000,
       NEXT_FEATURES = 0x04200000, NEXT_REFERENCE_RAW = 0x06000000,
       NEXT_REFERENCE_BLUR = 0x06400000, NEXT_MAX_PIXELS = 960 * 720,
       NEXT_REFERENCE_PIXELS = 960*720 + 800*600 + 667*500 + 556*417 +
           463*347 + 386*289 + 322*241 + 268*201,
       NEXT_COMMAND_MAGIC = 0x4E585443, NEXT_RESULT_MAGIC = 0x4E585452,
       NEXT_SCHEMA = 5, NEXT_FABRIC_HZ = 100000000, NEXT_MAILBOX_WORDS = 128 };
/** Extra DDR buffers; existing addresses/MMIO and hardware record ABI are unchanged. */
enum { NEXT_PIPE_RAW2 = 0x02C00000, NEXT_PIPE_BLUR1 = 0x02E00000,
       NEXT_PIPE_POINTS1 = 0x04400000, NEXT_PIPE_SUMMARY1 = 0x04500000 };
/** Schema-5 retains existing indexes; requests are read before clearing results. */
enum { MB_COMMAND, MB_ITERATIONS, MB_MAGIC, MB_SCHEMA, MB_STATUS, MB_ERROR,
       MB_COMPLETED, MB_FAILING_ITERATION, MB_DETAIL, MB_TIMER_HZ, MB_FABRIC_HZ,
       MB_CANDIDATES, MB_SELECTED, MB_PROCESS_US, MB_FPS_MILLI, MB_WALL_US,
       MB_VERIFY_US, MB_CONFIG_US, MB_BACKEND_US, MB_FRONT_US, MB_RESIZE_US,
       MB_GAUSSIAN_US, MB_MIN_US, MB_MAX_US, MB_DIGEST_HI, MB_DIGEST_LO,
       MB_MODE, MB_VERIFIED_FRAMES, MB_PREP_US, MB_CACHE_US, MB_WAIT_US, MB_OTHER_US,
       MB_FRONT_LEVEL = 32, MB_RESIZE_LEVEL = 40, MB_GAUSSIAN_LEVEL = 48,
       MB_BACKEND_LEVEL = 56, MB_FRONT_EQ_CYCLES = 64,
       MB_RESIZE_EQ_CYCLES = 72, MB_GAUSSIAN_EQ_CYCLES = 80,
       MB_PREP_LEVEL = 88, MB_CACHE_LEVEL = 96, MB_WAIT_LEVEL = 104,
       MB_SCHEDULE = 112, MB_BACKEND_AHEAD_LAUNCHES, MB_PL_OBSERVATION_UPPER_BOUND,
       MB_ABORT_DRAIN_ERROR, MB_PENDING_CORE_MASK };
/** Serial is the safe default until authorized physical pipeline acceptance. */
enum { NEXT_SCHEDULE_SERIAL = 0, NEXT_SCHEDULE_PIPELINE = 1 };
/** Production skips output poison/oracle scans and must never publish exact PASS. */
enum { NEXT_MODE_LEGACY = 0, NEXT_MODE_VERIFIED = 1, NEXT_MODE_PRODUCTION = 2 };
enum { NEXT_RUNNING = 1, NEXT_PASS = 2, NEXT_FAIL = 3, NEXT_COMPLETE_UNVERIFIED = 4 };
enum { ERR_WORKSPACE = 1, ERR_COMMAND = 2, ERR_INPUT = 10, ERR_REFERENCE = 11,
       ERR_IDLE = 100, ERR_TIMEOUT = 200, ERR_RETURN = 210,
       ERR_RAW = 300, ERR_BLUR = 301, ERR_SUMMARY = 302, ERR_POINTS = 303,
       ERR_GUARD = 304, ERR_BACKEND = 400, ERR_FEATURE = 401 };
typedef NextPoint OrbPoint;
/** Unchanged 64-byte hardware FAST summary ABI. */
typedef struct {
    uint32_t version;
    int32_t status, candidate_count, selected_count, cell_side, cell_cols, cell_rows;
    int32_t empty_cells, fallback_cells, tile_cols, tile_rows, tile_width, tile_height;
    uint32_t reserved0, reserved1, reserved2;
} Fastv2Summary;
typedef char NextSummaryMustBe64[(sizeof(Fastv2Summary) == 64) ? 1 : -1];
#endif
