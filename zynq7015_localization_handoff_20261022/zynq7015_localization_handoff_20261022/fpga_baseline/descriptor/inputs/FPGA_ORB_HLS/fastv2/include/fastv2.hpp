#pragma once

#include <cstdint>

namespace fastv2 {

/** Maximum width accepted by the fixed-performance front end. */
constexpr int kMaxWidth = 960;
/** Maximum height accepted by the fixed-performance front end. */
constexpr int kMaxHeight = 720;
/** Maximum number of grid cells retained in on-chip winner storage. */
constexpr int kMaxGridCells = 256;
/** Maximum number of selected points supported by the normal fastv2 profile. */
constexpr int kMaxSelected = 1000;
/** Maximum candidates retained on chip before grid reduction. */
constexpr int kMaxCandidates = 8192;
/** fastv2 result layout version. */
constexpr uint32_t kResultVersion = UINT32_C(0x00020000);

/** Status codes returned by the HLS control interface and result record. */
enum Status {
    kOk = 0,
    kInvalidArgument = 1,
    kCandidateCapacityExceeded = 2,
    kGridCapacityExceeded = 3,
    kSelectedCapacityExceeded = 4,
};

/**
 * @brief One FAST/NMS point in the descriptor-border-free coordinate system.
 *
 * The layout intentionally matches orb_hls::Point so PS software can reuse the
 * existing 128-bit point readers without translation.
 */
struct Point {
    int32_t x;
    int32_t y;
    int32_t score;
    int32_t tile;
};

/**
 * @brief Fixed-size summary written after every fastv2 transaction.
 *
 * The 64-byte record is suitable for a fixed DDR result address. Reserved
 * fields are cleared so later revisions can extend the record deterministically.
 */
struct Result {
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
};

static_assert(sizeof(Point) == 16, "fastv2 Point must be 128 bits");
static_assert(sizeof(Result) == 64, "fastv2 Result must be 512 bits");

} // namespace fastv2

/**
 * @brief Run the exact v1.0 FAST, tile-local NMS, and top-1 grid selection.
 *
 * @param image Row-major grayscale image packed as eight little-endian pixels
 *        per 64-bit word.
 * @param selected Output selected points. When the grid produces no more than
 *        budget points, records are emitted in cell raster order. If the budget
 *        truncates the grid, records are emitted by the reference strength order.
 * @param result One 64-byte transaction summary, always written for legal pointers.
 * @param width Frozen pyramid-level width: 960, 800, 667, 556, 463, 386,
 *        322, or 268.
 * @param height Frozen pyramid-level height paired with width: 720, 600, 500,
 *        417, 347, 289, 241, or 201.
 * @param budget Frozen per-level selection budget paired with width and height:
 *        217, 181, 151, 126, 105, 87, 73, or 60.
 * @param high_threshold Inclusive high FAST threshold, in the range 1..255.
 * @param low_threshold Inclusive fallback threshold, not above high_threshold.
 * @param dual_threshold Set to one to enable per-cell low-threshold fallback.
 * @param selected_capacity Number of Point records available at selected.
 * @return A fastv2::Status value.
 *
 * @pre image、selected和result必须指向有效且互不重叠的DDR区域。
 * @note The top uses a single raster scan. FAST scores and NMS intermediates
 *       remain in line buffers; the full score image and raw candidate list are
 *       never written to external memory.
 */
extern "C" int fastv2_front_hls(
    const uint64_t* image,
    fastv2::Point* selected,
    fastv2::Result* result,
    int width,
    int height,
    int budget,
    int high_threshold,
    int low_threshold,
    int dual_threshold,
    int selected_capacity);

/** Versioned 64-bit AXI entry; DDR Point/Result byte layouts are unchanged. */
extern "C" int fastv2_front64_hls(
    const uint64_t* image, uint64_t* selected_words, uint64_t* result_words,
    int width, int height, int budget, int high_threshold, int low_threshold,
    int dual_threshold, int selected_capacity);

/** Two-pixel stream scan; preserves the original DDR records and ordering. */
extern "C" int fastv2_front2_hls(
    const uint64_t* image, uint64_t* selected, uint64_t* result,
    int width, int height, int budget, int high_threshold, int low_threshold,
    int dual_threshold, int selected_capacity);

/**
 * @brief Resize one adjacent frozen pyramid level with exact v1.0 arithmetic.
 *
 * @param source Source grayscale image packed as eight little-endian pixels per
 *        64-bit word.
 * @param destination Destination buffer using the same packed representation.
 * @param source_level Source pyramid level in the inclusive range 0..6; the
 *        destination geometry is the next level.
 * @return A fastv2::Status value.
 *
 * @pre source and destination must identify valid, non-overlapping DDR ranges.
 * @note All source coordinates and Q0.11 interpolation weights come from the
 *       generated fixed-profile ROM; no transaction-time division is used.
 */
extern "C" int fastv2_resize_hls(
    const uint64_t* source,
    uint64_t* destination,
    int source_level);
