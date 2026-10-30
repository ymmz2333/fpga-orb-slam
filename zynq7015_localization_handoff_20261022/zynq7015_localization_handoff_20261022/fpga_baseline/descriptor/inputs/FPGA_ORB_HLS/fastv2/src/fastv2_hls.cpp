#include "fastv2.hpp"
#include "fastv2_profile_rom.hpp"

#include <cstdint>

namespace {

using fastv2::Point;
using fastv2::Result;

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

/** Packed exact resize coordinate decoded from the generated ROM. */
struct ResizeAxis {
    int source_a;
    int source_b;
    int weight;
};

/**
 * @brief Decode one generated resize-axis record.
 * @param packed ROM word containing two 11-bit indices and one 12-bit weight.
 * @return Expanded exact resize coordinate.
 */
ResizeAxis unpack_resize_axis(uint64_t packed) {
#pragma HLS INLINE
    ResizeAxis axis;
    axis.source_a = int(packed & 0x7ffu);
    axis.source_b = int((packed >> 11) & 0x7ffu);
    axis.weight = int((packed >> 22) & 0xfffu);
    return axis;
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
    int difference[25];
    int response_by_start[16];
#pragma HLS ARRAY_PARTITION variable=difference complete dim=1
#pragma HLS ARRAY_PARTITION variable=response_by_start complete dim=1

    for (int index = 0; index < 16; ++index) {
#pragma HLS UNROLL
        difference[index] = int(ring[index]) - int(center);
    }
    for (int index = 16; index < 25; ++index) {
#pragma HLS UNROLL
        difference[index] = difference[index - 16];
    }
    for (int start = 0; start < 16; ++start) {
#pragma HLS UNROLL
        int low = 255;
        int high = -255;
        for (int offset = 0; offset < 9; ++offset) {
#pragma HLS UNROLL
            const int value = difference[start + offset];
            if (value < low) low = value;
            if (value > high) high = value;
        }
        response_by_start[start] = low > -high ? low : -high;
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

} // namespace

/** @copydoc fastv2_front_hls */
extern "C" int fastv2_front_hls(
    const uint64_t* image, Point* selected, Result* result,
    int width, int height, int budget, int high_threshold,
    int low_threshold, int dual_threshold, int selected_capacity) {
#ifdef FASTV2_HLS_COSIM_SMALL_DEPTH
#pragma HLS INTERFACE m_axi port=image offset=slave bundle=gmem0 depth=6734
#pragma HLS INTERFACE m_axi port=selected offset=slave bundle=gmem1 depth=1000
#else
#pragma HLS INTERFACE m_axi port=image offset=slave bundle=gmem0 depth=86400
#pragma HLS INTERFACE m_axi port=selected offset=slave bundle=gmem1 depth=1000
#endif
#pragma HLS INTERFACE m_axi port=result offset=slave bundle=gmem1 depth=1
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
    const int effective_width = profile.effective_width;
    const int effective_height = profile.effective_height;
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
    if (cell_count > fastv2::kMaxGridCells) {
        summary.status = fastv2::kGridCapacityExceeded;
        result[0] = summary;
        return fastv2::kGridCapacityExceeded;
    }

    uint64_t best_high[fastv2::kMaxGridCells];
    uint64_t best_low[fastv2::kMaxGridCells];
    uint64_t packed_candidates[fastv2::kMaxCandidates];
    bool valid_high[fastv2::kMaxGridCells];
    bool valid_low[fastv2::kMaxGridCells];
#pragma HLS RESOURCE variable=best_high core=RAM_2P_BRAM
#pragma HLS RESOURCE variable=best_low core=RAM_2P_BRAM
#pragma HLS RESOURCE variable=packed_candidates core=RAM_2P_BRAM
InitializeCells:
    for (int cell = 0; cell < fastv2::kMaxGridCells; ++cell) {
#pragma HLS PIPELINE II=1
        best_high[cell] = 0;
        best_low[cell] = 0;
        valid_high[cell] = false;
        valid_low[cell] = false;
    }

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
    LoadPackedRow:
        for (int word = first_word; word < final_word; ++word) {
#pragma HLS PIPELINE II=1
            packed_row[word - first_word] = image[word];
        }

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
            if (candidate_count < fastv2::kMaxCandidates) {
                packed_candidates[candidate_count] = pack_point(point);
            }
            ++candidate_count;
        }
    }

    summary.candidate_count = candidate_count;
    if (candidate_count > fastv2::kMaxCandidates) {
        summary.status = fastv2::kCandidateCapacityExceeded;
        result[0] = summary;
        return fastv2::kCandidateCapacityExceeded;
    }

AccumulateCandidates:
    for (int candidate = 0; candidate < fastv2::kMaxCandidates; ++candidate) {
        if (candidate >= candidate_count) break;
        const Point point = unpack_point(packed_candidates[candidate]);
        const uint32_t x_info = fastv2_profile::kAxisXInfo[
            profile.x_info_offset + point.x + 20];
        const uint32_t y_info = fastv2_profile::kAxisYInfo[
            profile.y_info_offset + point.y + 20];
        const int cell_x = int((x_info >> 25) & 0x1fu);
        const int cell_y = int((y_info >> 25) & 0x1fu);
        const int cell = cell_y * cell_cols + cell_x;
        const uint64_t packed_point = pack_point(point);
        if (!valid_low[cell] || stronger(point, unpack_point(best_low[cell]))) {
            best_low[cell] = packed_point;
            valid_low[cell] = true;
        }
        if (point.score >= high_threshold &&
            (!valid_high[cell] || stronger(point, unpack_point(best_high[cell])))) {
            best_high[cell] = packed_point;
            valid_high[cell] = true;
        }
    }

    uint64_t winners[fastv2::kMaxGridCells];
    bool winner_valid[fastv2::kMaxGridCells];
    bool emitted[fastv2::kMaxGridCells];
#pragma HLS RESOURCE variable=winners core=RAM_2P_BRAM
    int winner_count = 0;
BuildWinners:
    for (int cell = 0; cell < fastv2::kMaxGridCells; ++cell) {
#pragma HLS PIPELINE II=1
        winner_valid[cell] = false;
        emitted[cell] = false;
        winners[cell] = 0;
        if (cell < cell_count) {
            if (dual_threshold && valid_high[cell]) {
                winners[cell] = best_high[cell];
                winner_valid[cell] = true;
            } else if (valid_low[cell]) {
                winners[cell] = best_low[cell];
                winner_valid[cell] = true;
                if (dual_threshold) ++summary.fallback_cells;
            } else {
                ++summary.empty_cells;
            }
            if (winner_valid[cell]) ++winner_count;
        }
    }

    const int selected_count = winner_count < budget ? winner_count : budget;
    summary.selected_count = selected_count;
    if (selected_count > selected_capacity) {
        summary.status = fastv2::kSelectedCapacityExceeded;
        result[0] = summary;
        return fastv2::kSelectedCapacityExceeded;
    }

    if (winner_count <= budget) {
        int output_index = 0;
    EmitCellOrder:
        for (int cell = 0; cell < fastv2::kMaxGridCells; ++cell) {
#pragma HLS PIPELINE II=1
            if (cell < cell_count && winner_valid[cell]) {
                selected[output_index] = unpack_point(winners[cell]);
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
            for (int cell = 0; cell < fastv2::kMaxGridCells; ++cell) {
#pragma HLS PIPELINE II=1
                if (cell < cell_count && winner_valid[cell] && !emitted[cell]) {
                    const Point point = unpack_point(winners[cell]);
                    if (best_cell < 0 || stronger(point, best_point)) {
                        best_cell = cell;
                        best_point = point;
                    }
                }
            }
            if (best_cell >= 0) {
                selected[output_index] = best_point;
                emitted[best_cell] = true;
            }
        }
    }

    result[0] = summary;
    return fastv2::kOk;
}

/** @copydoc fastv2_resize_hls */
extern "C" int fastv2_resize_hls(
    const uint64_t* source, uint64_t* destination, int source_level) {
#ifdef FASTV2_HLS_COSIM_SMALL_DEPTH
#pragma HLS INTERFACE m_axi port=source offset=slave bundle=gmem0 depth=9701
#pragma HLS INTERFACE m_axi port=destination offset=slave bundle=gmem1 depth=6734
#else
#pragma HLS INTERFACE m_axi port=source offset=slave bundle=gmem0 depth=86400
#pragma HLS INTERFACE m_axi port=destination offset=slave bundle=gmem1 depth=86400
#endif
#pragma HLS INTERFACE s_axilite port=source bundle=control
#pragma HLS INTERFACE s_axilite port=destination bundle=control
#pragma HLS INTERFACE s_axilite port=source_level bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    if (source_level < 0 || source_level >= 7) {
        return fastv2::kInvalidArgument;
    }

    const fastv2_profile::Profile source_profile =
        fastv2_profile::kProfiles[source_level];
    const fastv2_profile::Profile destination_profile =
        fastv2_profile::kProfiles[source_level + 1];
    const int source_width = source_profile.width;
    const int destination_width = destination_profile.width;
    const int destination_height = destination_profile.height;
    const int x_offset = fastv2_profile::kResizeXOffsets[source_level];
    const int y_offset = fastv2_profile::kResizeYOffsets[source_level];

    // Four identical copies provide four independent read ports for the two
    // horizontal taps on both vertical rows. This deliberately trades a few
    // BRAMs for one output pixel per cycle on Vivado HLS 2018.3.
    uint64_t source_rows[2][4][(fastv2::kMaxWidth + 14) / 8];
#pragma HLS ARRAY_PARTITION variable=source_rows complete dim=1
#pragma HLS ARRAY_PARTITION variable=source_rows complete dim=2
#pragma HLS RESOURCE variable=source_rows core=RAM_2P_BRAM
    int cached_row0 = -1;
    int cached_row1 = -1;
    uint64_t output_word = 0;

ResizeRows:
    for (int y = 0; y < destination_height; ++y) {
        const ResizeAxis vertical = unpack_resize_axis(
            fastv2_profile::kResizeYAxis[y_offset + y]);
        int bank_a = cached_row0 == vertical.source_a
            ? 0 : (cached_row1 == vertical.source_a ? 1 : -1);
        int bank_b = cached_row0 == vertical.source_b
            ? 0 : (cached_row1 == vertical.source_b ? 1 : -1);

        if (bank_a < 0) {
            bank_a = bank_b == 0 ? 1 : 0;
            const int row_base = vertical.source_a * source_width;
            const int first_word = row_base >> 3;
            const int final_word = (row_base + source_width + 7) >> 3;
        LoadResizeRowA:
            for (int word = first_word; word < final_word; ++word) {
#pragma HLS PIPELINE II=1
                const uint64_t packed = source[word];
                for (int copy = 0; copy < 4; ++copy) {
#pragma HLS UNROLL
                    source_rows[bank_a][copy][word - first_word] = packed;
                }
            }
            if (bank_a == 0) cached_row0 = vertical.source_a;
            else cached_row1 = vertical.source_a;
        }
        if (vertical.source_b == vertical.source_a) {
            bank_b = bank_a;
        } else {
            bank_b = cached_row0 == vertical.source_b
                ? 0 : (cached_row1 == vertical.source_b ? 1 : -1);
        }
        if (bank_b < 0) {
            bank_b = bank_a == 0 ? 1 : 0;
            const int row_base = vertical.source_b * source_width;
            const int first_word = row_base >> 3;
            const int final_word = (row_base + source_width + 7) >> 3;
        LoadResizeRowB:
            for (int word = first_word; word < final_word; ++word) {
#pragma HLS PIPELINE II=1
                const uint64_t packed = source[word];
                for (int copy = 0; copy < 4; ++copy) {
#pragma HLS UNROLL
                    source_rows[bank_b][copy][word - first_word] = packed;
                }
            }
            if (bank_b == 0) cached_row0 = vertical.source_b;
            else cached_row1 = vertical.source_b;
        }

        const int row_a_base = vertical.source_a * source_width;
        const int row_b_base = vertical.source_b * source_width;
        const int row_a_first_word = row_a_base >> 3;
        const int row_b_first_word = row_b_base >> 3;
    InterpolateResizeRow:
        for (int x = 0; x < destination_width; ++x) {
#pragma HLS PIPELINE II=1
            const ResizeAxis horizontal = unpack_resize_axis(
                fastv2_profile::kResizeXAxis[x_offset + x]);
            const int row_a_index0 = row_a_base + horizontal.source_a;
            const int row_a_index1 = row_a_base + horizontal.source_b;
            const int row_b_index0 = row_b_base + horizontal.source_a;
            const int row_b_index1 = row_b_base + horizontal.source_b;
            const uint64_t row_a_word0 = source_rows[bank_a][0][
                (row_a_index0 >> 3) - row_a_first_word];
            const uint64_t row_a_word1 = source_rows[bank_a][1][
                (row_a_index1 >> 3) - row_a_first_word];
            const uint64_t row_b_word0 = source_rows[bank_b][2][
                (row_b_index0 >> 3) - row_b_first_word];
            const uint64_t row_b_word1 = source_rows[bank_b][3][
                (row_b_index1 >> 3) - row_b_first_word];
            const uint8_t row_a0 = uint8_t(
                row_a_word0 >> ((row_a_index0 & 7) * 8));
            const uint8_t row_a1 = uint8_t(
                row_a_word1 >> ((row_a_index1 & 7) * 8));
            const uint8_t row_b0 = uint8_t(
                row_b_word0 >> ((row_b_index0 & 7) * 8));
            const uint8_t row_b1 = uint8_t(
                row_b_word1 >> ((row_b_index1 & 7) * 8));
            const int64_t row0 =
                int64_t(row_a0) * (2048 - horizontal.weight) +
                int64_t(row_a1) * horizontal.weight;
            const int64_t row1 =
                int64_t(row_b0) * (2048 - horizontal.weight) +
                int64_t(row_b1) * horizontal.weight;
            const int64_t value =
                ((row0 >> 4) * (2048 - vertical.weight) >> 16) +
                ((row1 >> 4) * vertical.weight >> 16);
            const int destination_index = y * destination_width + x;
            const int lane = destination_index & 7;
            output_word |= uint64_t(uint8_t((value + 2) >> 2)) << (lane * 8);
            if (lane == 7 ||
                destination_index + 1 == destination_width * destination_height) {
                destination[destination_index >> 3] = output_word;
                output_word = 0;
            }
        }
    }
    return fastv2::kOk;
}
