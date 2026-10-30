#include "fastv2.hpp"
#include "fastv2_profile_rom.hpp"
#include "next_stream.hpp"

#include <cstdint>
#include <cstring>
#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
#include <ap_int.h>
#endif

namespace {

using fastv2::Point;
using fastv2::Result;
/** Frozen eight-layer maximum: level zero contains 17*12=204 cells. */
constexpr int kGridCells = 204;
#if defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM)
/** Exact range -255..255; no 32-bit datapath is needed for pixel differences. */
typedef ap_int<9> ScoreSigned;
/** Point payload is exactly 41 bits; neither grid memory needs a 64-bit word. */
typedef ap_uint<41> PackedPoint;
#else
typedef int16_t ScoreSigned;
typedef uint64_t PackedPoint;
#endif

/**
 * @brief Find the frozen pyramid profile matching one transaction.
 * @param width Layer width.
 * @param height Layer height.
 * @param budget Layer feature budget.
 * @return Profile index in 0..7, or -1 when the tuple is unsupported.
 */
int find_profile(int width, int height, int budget) {
    int profile = -1;
    for (int index = 0; index < 8; ++index) {
#pragma HLS UNROLL
        if (width == fastv2_profile::kProfiles[index].width &&
            height == fastv2_profile::kProfiles[index].height &&
            budget == fastv2_profile::kProfiles[index].budget) {
            profile = index;
        }
    }
    return profile;
}

/**
 * @brief Compare two points in raster order.
 * @param left First point.
 * @param right Second point.
 * @return True when left precedes right by y and then x.
 */
bool raster_before(const Point& left, const Point& right) {
#pragma HLS INLINE
    return left.y < right.y || (left.y == right.y && left.x < right.x);
}

/**
 * @brief Compare points using the v1.0 grid strength ordering.
 * @param left First point.
 * @param right Second point.
 * @return True when left must rank before right.
 */
bool stronger(const Point& left, const Point& right) {
#pragma HLS INLINE
    return left.score > right.score ||
           (left.score == right.score && raster_before(left, right));
}

/**
 * @brief Pack a point into the compact on-chip grid representation.
 * @param point Point with nonnegative effective coordinates.
 * @return Packed x, y, score, and tile fields.
 */
uint64_t pack_point(const Point& point) {
#pragma HLS INLINE
    return uint64_t(uint32_t(point.x) & 0x7ffu) |
           (uint64_t(uint32_t(point.y) & 0x7ffu) << 11) |
           (uint64_t(uint32_t(point.score) & 0xffu) << 22) |
           (uint64_t(uint32_t(point.tile) & 0x7ffu) << 30);
}

/**
 * @brief Restore a point from the compact on-chip grid representation.
 * @param packed Value produced by pack_point.
 * @return Expanded point record.
 */
Point unpack_point(uint64_t packed) {
#pragma HLS INLINE
    Point point;
    point.x = int32_t(packed & 0x7ffu);
    point.y = int32_t((packed >> 11) & 0x7ffu);
    point.score = int32_t((packed >> 22) & 0xffu);
    point.tile = int32_t((packed >> 30) & 0x7ffu);
    return point;
}

/**
 * @brief Compute the exact v1.0 FAST response for one radius-three ring.
 * @param center Center-pixel intensity.
 * @param ring Sixteen clockwise ring samples.
 * @return Public FAST score including the reference minus-one adjustment.
 */
uint8_t fast_score(uint8_t center, const uint8_t ring[16]) {
#pragma HLS INLINE
#pragma HLS ARRAY_PARTITION variable=ring complete dim=1
    ScoreSigned difference[16];
    ScoreSigned minimum3[16], maximum3[16], response_by_start[16];
#pragma HLS ARRAY_PARTITION variable=difference complete dim=1
#pragma HLS ARRAY_PARTITION variable=minimum3 complete dim=1
#pragma HLS ARRAY_PARTITION variable=maximum3 complete dim=1
#pragma HLS ARRAY_PARTITION variable=response_by_start complete dim=1

    for (int index = 0; index < 16; ++index) {
#pragma HLS UNROLL
        difference[index] = ScoreSigned(int(ring[index]) - int(center));
    }
    /* Reuse 16 cyclic three-tap extrema instead of recomputing nine taps
       for every arc. Three disjoint triples exactly cover each nine-tap arc. */
    for (int start = 0; start < 16; ++start) {
#pragma HLS UNROLL
        const ScoreSigned a = difference[start];
        const ScoreSigned b = difference[(start + 1) & 15];
        const ScoreSigned c = difference[(start + 2) & 15];
        const ScoreSigned low2 = a < b ? a : b;
        const ScoreSigned high2 = a > b ? a : b;
        minimum3[start] = low2 < c ? low2 : c;
        maximum3[start] = high2 > c ? high2 : c;
    }
    for (int start = 0; start < 16; ++start) {
#pragma HLS UNROLL
        const ScoreSigned a = minimum3[start], b = minimum3[(start + 3) & 15];
        const ScoreSigned c = minimum3[(start + 6) & 15];
        const ScoreSigned d = maximum3[start], e = maximum3[(start + 3) & 15];
        const ScoreSigned f = maximum3[(start + 6) & 15];
        const ScoreSigned low2 = a < b ? a : b;
        const ScoreSigned high2 = d > e ? d : e;
        const ScoreSigned low = low2 < c ? low2 : c;
        const ScoreSigned high = high2 > f ? high2 : f;
        const ScoreSigned negative_high = ScoreSigned(-high);
        response_by_start[start] = low > negative_high ? low : negative_high;
    }

    int best = 0;
    for (int start = 0; start < 16; ++start) {
#pragma HLS UNROLL
        if (response_by_start[start] > best) best = response_by_start[start];
    }
    return uint8_t(best > 0 ? best - 1 : 0);
}

/**
 * @brief Initialize a deterministic result record.
 * @param output Record to clear and stamp with the layout version.
 */
void clear_result(Result& output) {
    output.version = fastv2::kResultVersion;
    output.status = fastv2::kOk;
    output.candidate_count = 0;
    output.selected_count = 0;
    output.cell_side = 0;
    output.cell_cols = 0;
    output.cell_rows = 0;
    output.empty_cells = 0;
    output.fallback_cells = 0;
    output.tile_cols = 0;
    output.tile_rows = 0;
    output.tile_width = 0;
    output.tile_height = 0;
    output.reserved0 = 0;
    output.reserved1 = 0;
    output.reserved2 = 0;
}

/**
 * @brief Scan FAST/NMS once and stream lossless grid-reduction tokens.
 * @param image Packed input image, not modified.
 * @param output FIFO: point bits 0..40, cell bits 41..48; final token bit 63.
 * @param profile Frozen geometry and ownership lookup offsets.
 * @param high_threshold Inclusive high threshold.
 * @param low_threshold Inclusive fallback threshold.
 * @param dual_threshold Zero or one, validated by the public top.
 * @note Sends every candidate followed by the full-count sentinel. There is no
 *       frame-capacity limit; blocking FIFO writes provide lossless backpressure.
 */
void scan_candidates(const uint64_t* image, hls::stream<uint64_t>& output,
                     const fastv2_profile::Profile& profile,
                     int high_threshold, int low_threshold, int dual_threshold) {
#pragma HLS INLINE off
    const int width = profile.width, height = profile.height;
    const int effective_width = profile.effective_width;
    const int effective_height = profile.effective_height;
    const int tile_cols = profile.tile_cols;
    uint8_t pixel_lines[7][fastv2::kMaxWidth];
    uint8_t score_lines[2][fastv2::kMaxWidth];
    uint64_t packed_row[(fastv2::kMaxWidth + 14) / 8];
#pragma HLS ARRAY_PARTITION variable=pixel_lines complete dim=1
#pragma HLS ARRAY_PARTITION variable=score_lines complete dim=1
#pragma HLS RESOURCE variable=pixel_lines core=RAM_S2P_BRAM
#pragma HLS RESOURCE variable=score_lines core=RAM_S2P_BRAM
#pragma HLS RESOURCE variable=packed_row core=RAM_2P_BRAM

    int candidate_count = 0;
RasterRows:
    for (int source_y = 0; source_y < height; ++source_y) {
        const uint32_t y_info = fastv2_profile::kAxisYInfo[
            profile.y_info_offset + source_y];
        const int scan_tile_y_start = int(y_info & 0x3ffu);
        const int scan_tile_y_end = int((y_info >> 10) & 0x3ffu);
        const int scan_tile_y = int((y_info >> 20) & 0x1fu);
        const int row_base = source_y * width;
        const int first_word = row_base >> 3;
        const int final_word = (row_base + width + 7) >> 3;
        /* Keep DDR burst transfer separate from the single-pixel scan. */
        std::memcpy(packed_row, image + first_word,
                    size_t(final_word - first_word) * sizeof(uint64_t));

        uint8_t pixel_window[7][7];
        uint8_t nms_window[3][3];
#pragma HLS ARRAY_PARTITION variable=pixel_window complete dim=1
#pragma HLS ARRAY_PARTITION variable=pixel_window complete dim=2
#pragma HLS ARRAY_PARTITION variable=nms_window complete dim=1
#pragma HLS ARRAY_PARTITION variable=nms_window complete dim=2
    ClearPixelWindowRows:
        for (int row = 0; row < 7; ++row) {
#pragma HLS UNROLL
            for (int column = 0; column < 7; ++column) {
#pragma HLS UNROLL
                pixel_window[row][column] = 0;
            }
        }
    ClearNmsWindowRows:
        for (int row = 0; row < 3; ++row) {
#pragma HLS UNROLL
            for (int column = 0; column < 3; ++column) {
#pragma HLS UNROLL
                nms_window[row][column] = 0;
            }
        }

    RasterColumns:
        for (int source_x = 0; source_x < width; ++source_x) {
#pragma HLS LOOP_FLATTEN off
#pragma HLS PIPELINE II=1
            const int source_index = row_base + source_x;
            const uint64_t packed = packed_row[(source_index >> 3) - first_word];
            const uint8_t pixel = uint8_t(packed >> ((source_index & 7) * 8));
            uint8_t column[7];
#pragma HLS ARRAY_PARTITION variable=column complete dim=1
            for (int row = 0; row < 6; ++row) {
#pragma HLS UNROLL
                column[row] = source_y >= 6 - row
                    ? pixel_lines[row + 1][source_x]
                    : uint8_t(0);
                pixel_lines[row][source_x] = column[row];
            }
            column[6] = pixel;
            pixel_lines[6][source_x] = pixel;
            for (int row = 0; row < 7; ++row) {
#pragma HLS UNROLL
                for (int column_index = 0; column_index < 6; ++column_index) {
#pragma HLS UNROLL
                    pixel_window[row][column_index] = pixel_window[row][column_index + 1];
                }
                pixel_window[row][6] = column[row];
            }
            if (source_y < 6 || source_x < 6) continue;

            uint8_t ring[16];
#pragma HLS ARRAY_PARTITION variable=ring complete dim=1
            ring[0] = pixel_window[6][3];
            ring[1] = pixel_window[6][4];
            ring[2] = pixel_window[5][5];
            ring[3] = pixel_window[4][6];
            ring[4] = pixel_window[3][6];
            ring[5] = pixel_window[2][6];
            ring[6] = pixel_window[1][5];
            ring[7] = pixel_window[0][4];
            ring[8] = pixel_window[0][3];
            ring[9] = pixel_window[0][2];
            ring[10] = pixel_window[1][1];
            ring[11] = pixel_window[2][0];
            ring[12] = pixel_window[3][0];
            ring[13] = pixel_window[4][0];
            ring[14] = pixel_window[5][1];
            ring[15] = pixel_window[6][2];
            const uint8_t score = fast_score(pixel_window[3][3], ring);
            const int score_x = source_x - 6;
            const int score_y = source_y - 6;
            const uint8_t previous2 = score_y >= 2 ? score_lines[0][score_x] : uint8_t(0);
            const uint8_t previous1 = score_y >= 1 ? score_lines[1][score_x] : uint8_t(0);
            score_lines[0][score_x] = previous1;
            score_lines[1][score_x] = score;
            for (int row = 0; row < 3; ++row) {
#pragma HLS UNROLL
                nms_window[row][0] = nms_window[row][1];
                nms_window[row][1] = nms_window[row][2];
            }
            nms_window[0][2] = previous2;
            nms_window[1][2] = previous1;
            nms_window[2][2] = score;
            if (score_x < 2 || score_y < 2) continue;

            const int center_x = source_x - 4;
            const int center_y = source_y - 4;
            const int effective_x = center_x - 16;
            const int effective_y = center_y - 16;
            const uint32_t tile_info = fastv2_profile::kAxisXInfo[
                profile.x_info_offset + source_x];
            const int scan_tile_x_start = int(tile_info & 0x3ffu);
            const int scan_tile_x_end = int((tile_info >> 10) & 0x3ffu);
            const int scan_tile_x = int((tile_info >> 20) & 0x1fu);
            if (effective_x < 3 || effective_x >= effective_width - 3 ||
                effective_y < 3 || effective_y >= effective_height - 3) {
                continue;
            }
            const int tile = scan_tile_y * tile_cols + scan_tile_x;
            const int response = nms_window[1][1];
            const int threshold = dual_threshold ? low_threshold : high_threshold;
            if (response < threshold) continue;

            bool keep = true;
        CompareNmsRows:
            for (int offset_y = -1; offset_y <= 1; ++offset_y) {
#pragma HLS UNROLL
            CompareNmsColumns:
                for (int offset_x = -1; offset_x <= 1; ++offset_x) {
#pragma HLS UNROLL
                    if (offset_x == 0 && offset_y == 0) continue;
                    int neighbour = 0;
                    const int neighbour_x = effective_x + offset_x;
                    const int neighbour_y = effective_y + offset_y;
                    if (neighbour_x >= scan_tile_x_start && neighbour_x < scan_tile_x_end &&
                        neighbour_y >= scan_tile_y_start && neighbour_y < scan_tile_y_end) {
                        neighbour = nms_window[offset_y + 1][offset_x + 1];
                    }
                    if (neighbour >= response) keep = false;
                }
            }
            if (!keep) continue;

            Point point;
            point.x = center_x - 16;
            point.y = center_y - 16;
            point.score = response;
            point.tile = tile;
            const int cell_x = int((tile_info >> 25) & 0x1fu);
            const int cell_y = int((y_info >> 25) & 0x1fu);
            const int cell = cell_y * profile.cell_cols + cell_x;
            output.write(pack_point(point) | (uint64_t(cell) << 41));
            ++candidate_count;
        }
    }

    output.write((UINT64_C(1) << 63) | uint64_t(uint32_t(candidate_count)));
}

/**
 * @brief Own all grid state, drain candidates, select exact winners and write DDR.
 * @param input Candidate FIFO with a mandatory full-count end marker.
 * @param selected Expanded Point output; unchanged on output-capacity failure.
 * @param result Exact 64-byte transaction summary.
 * @param profile Validated frozen layer geometry and feature budget.
 * @param high_threshold Inclusive high response threshold.
 * @param dual_threshold Validated fallback selector.
 * @param selected_capacity Advertised output-record capacity.
 * @param completion Exactly one status token (0 or 4), after summary writeback.
 * @note Grid memories are local to this actor, never DATAFLOW/PIPO array channels.
 *       Every transaction clears validity, drains to the sentinel and only then
 *       emits records. Consecutive same-cell updates retain true dependencies.
 */
void consume_and_select(hls::stream<uint64_t>& input, Point* selected, Result* result,
                        const fastv2_profile::Profile& profile, int high_threshold,
                        int dual_threshold, int selected_capacity,
                        hls::stream<uint8_t>& completion) {
#pragma HLS INLINE off
    PackedPoint best_high[kGridCells], best_low[kGridCells];
    bool valid_high[kGridCells], valid_low[kGridCells];
#pragma HLS RESOURCE variable=best_high core=RAM_2P_BRAM
#pragma HLS RESOURCE variable=best_low core=RAM_2P_BRAM
    Result summary;
    clear_result(summary);
    summary.cell_side = profile.cell_side;
    summary.cell_cols = profile.cell_cols;
    summary.cell_rows = profile.cell_rows;
    summary.tile_cols = profile.tile_cols;
    summary.tile_rows = profile.tile_rows;
    summary.tile_width = profile.tile_width;
    summary.tile_height = profile.tile_height;
    const int cell_count = profile.cell_cols * profile.cell_rows;
    const int budget = profile.budget;
InitializeCells:
    for (int cell = 0; cell < kGridCells; ++cell) {
#pragma HLS PIPELINE II=1
        best_high[cell] = 0;
        best_low[cell] = 0;
        valid_high[cell] = false;
        valid_low[cell] = false;
    }
ReduceCandidateTokens:
    for (;;) {
        const uint64_t token = input.read();
        if ((token >> 63) != 0) {
            summary.candidate_count = int(uint32_t(token));
            break;
        }
        const uint64_t packed = token & ((UINT64_C(1) << 41) - 1);
        const Point point = unpack_point(packed);
        const int cell = int((token >> 41) & 0xffu);
        if (!valid_low[cell] || stronger(point, unpack_point(best_low[cell]))) {
            best_low[cell] = packed;
            valid_low[cell] = true;
        }
        if (point.score >= high_threshold &&
            (!valid_high[cell] || stronger(point, unpack_point(best_high[cell])))) {
            best_high[cell] = packed;
            valid_high[cell] = true;
        }
    }
    /* High winners are a subset of low validity. Reuse the low store in place
       after reduction; strength-order emission consumes its validity bits. */
    int winner_count = 0;
BuildWinners:
    for (int cell = 0; cell < kGridCells; ++cell) {
#pragma HLS PIPELINE II=1
        if (cell < cell_count) {
            if (dual_threshold && valid_high[cell]) {
                best_low[cell] = best_high[cell];
            } else if (valid_low[cell]) {
                if (dual_threshold) ++summary.fallback_cells;
            } else {
                ++summary.empty_cells;
            }
            if (valid_low[cell]) ++winner_count;
        }
    }

    const int selected_count = winner_count < budget ? winner_count : budget;
    summary.selected_count = selected_count;
    if (selected_count > selected_capacity) {
        summary.status = fastv2::kSelectedCapacityExceeded;
        result[0] = summary;
        completion.write(uint8_t(fastv2::kSelectedCapacityExceeded));
        return;
    }

    if (winner_count <= budget) {
        int output_index = 0;
    EmitCellOrder:
        for (int cell = 0; cell < kGridCells; ++cell) {
#pragma HLS PIPELINE II=1
            if (cell < cell_count && valid_low[cell]) {
                selected[output_index] = unpack_point(best_low[cell]);
                ++output_index;
            }
        }
    } else {
    EmitStrengthOrder:
        for (int output_index = 0; output_index < fastv2::kMaxSelected; ++output_index) {
            if (output_index >= budget) break;
            int best_cell = -1;
            Point best_point = {0, 0, 0, 0};
        FindStrongestCell:
            for (int cell = 0; cell < kGridCells; ++cell) {
#pragma HLS PIPELINE II=1
                if (cell < cell_count && valid_low[cell]) {
                    const Point point = unpack_point(best_low[cell]);
                    if (best_cell < 0 || stronger(point, best_point)) {
                        best_cell = cell;
                        best_point = point;
                    }
                }
            }
            if (best_cell >= 0) {
                selected[output_index] = best_point;
                valid_low[best_cell] = false;
            }
        }
    }

    result[0] = summary;
    completion.write(uint8_t(fastv2::kOk));
}

/**
 * @brief Overlap the scanner with one state-owning reduction/selection actor.
 * @param image Packed input image.
 * @param selected Expanded selected-record destination.
 * @param result Fixed-size summary destination.
 * @param profile Validated frozen geometry.
 * @param high_threshold Inclusive high threshold.
 * @param low_threshold Inclusive low threshold.
 * @param dual_threshold Fallback enable flag.
 * @param selected_capacity Advertised record capacity.
 * @param completion One status token produced by the consumer, read by the top.
 * @note Only the bounded candidate FIFO connects the actors; no grid arrays cross
 *       the DATAFLOW boundary. Finite-FIFO liveness still requires RTL testing.
 */
void front_dataflow(const uint64_t* image, Point* selected, Result* result,
                    const fastv2_profile::Profile& profile, int high_threshold,
                    int low_threshold, int dual_threshold, int selected_capacity,
                    hls::stream<uint8_t>& completion) {
#pragma HLS INLINE off
    static hls::stream<uint64_t> candidates;
#pragma HLS STREAM variable=candidates depth=128
#pragma HLS DATAFLOW
    scan_candidates(image, candidates, profile, high_threshold, low_threshold, dual_threshold);
    consume_and_select(candidates, selected, result, profile, high_threshold,
                       dual_threshold, selected_capacity, completion);
}

} // namespace

#if !defined(__SYNTHESIS__) && !defined(FASTV2_HLS_CSIM)
/**
 * @brief Expose the actual score datapath only to host arithmetic regression.
 * @param center Center byte.
 * @param ring Clockwise radius-three samples.
 * @return Exact FAST response; this hook is absent from vendor synthesis.
 */
uint8_t next_test_fast_score(uint8_t center, const uint8_t ring[16]) {
    return fast_score(center, ring);
}
#endif

/** @copydoc fastv2_front_hls */
extern "C" int fastv2_front_hls(
    const uint64_t* image, Point* selected, Result* result,
    int width, int height, int budget, int high_threshold,
    int low_threshold, int dual_threshold, int selected_capacity) {
#ifdef FASTV2_HLS_COSIM_SMALL_DEPTH
#pragma HLS INTERFACE m_axi port=image offset=slave bundle=gmem0 depth=6734 max_read_burst_length=64 num_read_outstanding=2 max_write_burst_length=2 num_write_outstanding=1
#pragma HLS INTERFACE m_axi port=selected offset=slave bundle=gmem1 depth=1000 max_read_burst_length=2 num_read_outstanding=1 max_write_burst_length=16 num_write_outstanding=2
#else
#pragma HLS INTERFACE m_axi port=image offset=slave bundle=gmem0 depth=86400 max_read_burst_length=64 num_read_outstanding=2 max_write_burst_length=2 num_write_outstanding=1
#pragma HLS INTERFACE m_axi port=selected offset=slave bundle=gmem1 depth=1000 max_read_burst_length=2 num_read_outstanding=1 max_write_burst_length=16 num_write_outstanding=2
#endif
#pragma HLS INTERFACE m_axi port=result offset=slave bundle=gmem1 depth=1 max_read_burst_length=2 num_read_outstanding=1 max_write_burst_length=16 num_write_outstanding=2
#pragma HLS DATA_PACK variable=selected
#pragma HLS DATA_PACK variable=result
#pragma HLS INTERFACE s_axilite port=image bundle=control
#pragma HLS INTERFACE s_axilite port=selected bundle=control
#pragma HLS INTERFACE s_axilite port=result bundle=control
#pragma HLS INTERFACE s_axilite port=width bundle=control
#pragma HLS INTERFACE s_axilite port=height bundle=control
#pragma HLS INTERFACE s_axilite port=budget bundle=control
#pragma HLS INTERFACE s_axilite port=high_threshold bundle=control
#pragma HLS INTERFACE s_axilite port=low_threshold bundle=control
#pragma HLS INTERFACE s_axilite port=dual_threshold bundle=control
#pragma HLS INTERFACE s_axilite port=selected_capacity bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control

    Result summary;
    clear_result(summary);
    const int profile_index = find_profile(width, height, budget);
    if (profile_index < 0 || high_threshold < 1 ||
        high_threshold > 255 || low_threshold < 1 ||
        low_threshold > high_threshold ||
        (dual_threshold != 0 && dual_threshold != 1) ||
        selected_capacity < 0) {
        summary.status = fastv2::kInvalidArgument;
        result[0] = summary;
        return fastv2::kInvalidArgument;
    }

    const fastv2_profile::Profile profile = fastv2_profile::kProfiles[profile_index];
    const int tile_cols = profile.tile_cols;
    const int tile_rows = profile.tile_rows;
    const int tile_width = profile.tile_width;
    const int tile_height = profile.tile_height;
    const int cell_side = profile.cell_side;
    const int cell_cols = profile.cell_cols;
    const int cell_rows = profile.cell_rows;
    const int cell_count = cell_cols * cell_rows;

    summary.cell_side = cell_side;
    summary.cell_cols = cell_cols;
    summary.cell_rows = cell_rows;
    summary.tile_cols = tile_cols;
    summary.tile_rows = tile_rows;
    summary.tile_width = tile_width;
    summary.tile_height = tile_height;
    if (cell_count > kGridCells) {
        summary.status = fastv2::kGridCapacityExceeded;
        result[0] = summary;
        return fastv2::kGridCapacityExceeded;
    }

    /* One token per valid transaction. Depth two permits the producer to finish
       before this non-DATAFLOW top drains the token, without a feedback wait.
       Invalid arguments return above without producing or consuming a token. */
    static hls::stream<uint8_t> completion;
#pragma HLS STREAM variable=completion depth=2
    front_dataflow(image, selected, result, profile, high_threshold, low_threshold,
                   dual_threshold, selected_capacity, completion);
    /* Reconstruct public enum constants explicitly: the old scalar-reference
       path was reduced to bit zero by HLS 2018.3 and mapped status 4 to 0. */
    const uint8_t status = completion.read();
    if (status == uint8_t(fastv2::kSelectedCapacityExceeded))
        return fastv2::kSelectedCapacityExceeded;
    if (status == uint8_t(fastv2::kOk)) return fastv2::kOk;
    return fastv2::kInvalidArgument; // Unreachable unless the internal protocol fails.
}
