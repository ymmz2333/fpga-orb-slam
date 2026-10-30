#include "fastv2.hpp"
#include "fastv2_profile_rom.hpp"
#include <cstring>
#ifndef __SYNTHESIS__
#include <cassert>
#endif

namespace {
/** Exact coordinates and Q0.11 weight decoded from the frozen resize ROM. */
struct ResizeAxis { int a, b, weight; };

/**
 * @brief Expose the proven row-copy size bound to the HLS memcpy lowering.
 * @param word_count Number of 64-bit words, in 0..121 for frozen profiles.
 * @return Exact byte count for every legal row transfer.
 * @note Without the seven-bit bound, HLS 2018.3 estimates 536870911
 *       memcpy iterations and generates an impractically large AXI cosim model.
 *       The mask is wiring, not a clamp; host assertions detect contract violations.
 */
size_t row_transfer_bytes(int word_count) {
#pragma HLS INLINE
#ifndef __SYNTHESIS__
    assert(word_count >= 0 && word_count <= 121);
#endif
    return size_t(unsigned(word_count) & 0x7fu) * sizeof(uint64_t);
}

/**
 * @brief Decode a frozen half-pixel bilinear coordinate without runtime division.
 * @param packed Original ROM record; the second index is redundant in this profile.
 * @return Exact source indices and interpolation weight.
 */
ResizeAxis decode_axis(uint64_t packed) {
#pragma HLS INLINE
    ResizeAxis axis;
    axis.a = int(packed & 0x3ffu);
    /* All seven frozen downscale transitions have b=a+1, checked independently
       by the host profile contract test. Ignore the redundant ROM index bits. */
    axis.b = axis.a + 1;
    axis.weight = int((packed >> 10) & 0x7ffu);
    return axis;
}

/**
 * @brief Load one DDR source row into four byte-interleaved, non-replicated banks.
 * @param source Packed source image, including its final partial word.
 * @param rows Two cached rows, each split by column modulo four.
 * @param bank Physical row slot to replace, zero or one.
 * @param row Logical source row.
 * @param width Source width, at most 960.
 * @note The DDR request is contiguous. Four pixels are distributed per copy cycle.
 */
void load_row(const uint64_t* source, uint8_t rows[2][4][240],
              int bank, int row, int width) {
#pragma HLS INLINE
    uint64_t transfer[121];
#pragma HLS RESOURCE variable=transfer core=RAM_2P_BRAM
    const int row_base = row * width;
    const int first = row_base >> 3;
    const int count = ((row_base + width + 7) >> 3) - first;
    std::memcpy(transfer, source + first, row_transfer_bytes(count));
CopyFourSourcePixels:
    for (int group = 0; group < (width + 3) / 4; ++group) {
#pragma HLS PIPELINE II=1
        const int index = row_base + group * 4;
        const int word = (index >> 3) - first;
        const int shift = (index & 7) * 8;
        uint64_t pixels = transfer[word] >> shift;
        if (shift > 32 && word + 1 < count) {
            pixels |= transfer[word + 1] << (64 - shift);
        }
        for (int lane = 0; lane < 4; ++lane) {
#pragma HLS UNROLL
            if (group * 4 + lane < width) {
                rows[bank][lane][group] = uint8_t(pixels >> (lane * 8));
            }
        }
    }
}

/**
 * @brief Pack independent 64-bit words instead of a two-lane carry recurrence.
 * @param pairs Row pixels in four interleaved 16-bit pair banks.
 * @param words Completed packed DDR words, starting at the row's containing word.
 * @param width Active output-row width.
 * @param row Active output-row index.
 * @param height Total output rows.
 * @param carry In/out partial word shared across row boundaries, never row padding.
 * @return Number of completed words; final-image unused bytes are zero.
 * @note Odd row widths preserve the flat, tightly packed image representation.
 */
int pack_row(const uint16_t pairs[4][120], uint64_t words[121],
             int width, int row, int height, uint64_t& carry) {
#pragma HLS INLINE off
    const int offset = (row * width) & 7;
    const int pair_count = (width + 1) / 2;
    const bool final_row = row + 1 == height;
    const int count = (offset + width + (final_row ? 7 : 0)) >> 3;
PackResizeWords:
    for (int word = 0; word < count; ++word) {
#pragma HLS PIPELINE II=1
        const int first_x = word * 8 - offset;
        const int first_pair = first_x < 0 ? 0 : first_x / 2;
        const int first_bank = first_pair & 3;
        uint16_t values[4][2];
        int first_index[4];
#pragma HLS ARRAY_PARTITION variable=values complete dim=0
#pragma HLS ARRAY_PARTITION variable=first_index complete dim=1
        for (int bank = 0; bank < 4; ++bank) {
#pragma HLS UNROLL
            const int index = (first_pair >> 2) + (bank < first_bank ? 1 : 0);
            first_index[bank] = index;
            values[bank][0] = index * 4 + bank < pair_count ? pairs[bank][index] : uint16_t(0);
            values[bank][1] = (index + 1) * 4 + bank < pair_count ? pairs[bank][index + 1] : uint16_t(0);
        }
        uint64_t packed = 0;
        for (int byte = 0; byte < 8; ++byte) {
#pragma HLS UNROLL
            const int x = first_x + byte;
            uint8_t pixel = 0;
            if (x < 0) {
                pixel = uint8_t(carry >> (byte * 8));
            } else if (x < width) {
                const int pair = x >> 1;
                const int bank = pair & 3;
                const int slot = (pair >> 2) == first_index[bank] ? 0 : 1;
                pixel = uint8_t(values[bank][slot] >> ((x & 1) * 8));
            }
            packed |= uint64_t(pixel) << (byte * 8);
        }
        words[word] = packed;
    }
    uint64_t remainder = 0;
    if (!final_row) {
        const int remaining = (offset + width) & 7;
        const int first_x = count * 8 - offset;
    SaveResizeRemainder:
        for (int byte = 0; byte < 7; ++byte) {
            if (byte < remaining) {
                const int x = first_x + byte;
                const uint16_t pair = pairs[(x >> 1) & 3][x >> 3];
                remainder |= uint64_t(uint8_t(pair >> ((x & 1) * 8))) << (byte * 8);
            }
        }
    }
    carry = remainder;
    return count;
}
} // namespace

/**
 * @brief Perform exact frozen-profile resize with two output lanes and banked cache.
 * @param source Little-endian packed source grayscale pixels.
 * @param destination Disjoint packed output, with zero final padding.
 * @param source_level Source pyramid level, in 0..6.
 * @return fastv2 status; invalid levels access neither image buffer.
 * @note Two adjacent outputs span at most four source columns in these profiles.
 *       The four source banks provide those samples without full-row duplication.
 */
extern "C" int fastv2_resize_hls(const uint64_t* source, uint64_t* destination, int source_level) {
#pragma HLS INTERFACE m_axi port=source offset=slave bundle=gmem0 depth=86400 max_read_burst_length=64 num_read_outstanding=2 max_write_burst_length=2 num_write_outstanding=1
#pragma HLS INTERFACE m_axi port=destination offset=slave bundle=gmem1 depth=86400 max_write_burst_length=64 num_write_outstanding=2 max_read_burst_length=2 num_read_outstanding=1
#pragma HLS INTERFACE s_axilite port=source bundle=control
#pragma HLS INTERFACE s_axilite port=destination bundle=control
#pragma HLS INTERFACE s_axilite port=source_level bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    if (source_level < 0 || source_level > 6) return fastv2::kInvalidArgument;
    const int source_width = fastv2_profile::kProfiles[source_level].width;
    const int width = fastv2_profile::kProfiles[source_level + 1].width;
    const int height = fastv2_profile::kProfiles[source_level + 1].height;
    const int x_offset = fastv2_profile::kResizeXOffsets[source_level];
    const int y_offset = fastv2_profile::kResizeYOffsets[source_level];
    uint8_t rows[2][4][240];
    uint16_t pairs[4][120];
    uint64_t words[121];
    int cached_rows[2] = {-1, -1};
#pragma HLS ARRAY_PARTITION variable=rows complete dim=1
#pragma HLS ARRAY_PARTITION variable=rows complete dim=2
#pragma HLS RESOURCE variable=rows core=RAM_2P_BRAM
#pragma HLS ARRAY_PARTITION variable=pairs complete dim=1
#pragma HLS RESOURCE variable=pairs core=RAM_2P_BRAM
#pragma HLS ARRAY_PARTITION variable=cached_rows complete dim=1
    uint64_t carry = 0;
ResizeRows:
    for (int y = 0; y < height; ++y) {
        const ResizeAxis vertical = decode_axis(fastv2_profile::kResizeYAxis[y_offset + y]);
        int bank_a = cached_rows[0] == vertical.a ? 0 : (cached_rows[1] == vertical.a ? 1 : -1);
        int bank_b = cached_rows[0] == vertical.b ? 0 : (cached_rows[1] == vertical.b ? 1 : -1);
        if (bank_a < 0) {
            bank_a = bank_b == 0 ? 1 : 0;
            load_row(source, rows, bank_a, vertical.a, source_width);
            cached_rows[bank_a] = vertical.a;
        }
        bank_b = vertical.b == vertical.a ? bank_a :
                 (cached_rows[0] == vertical.b ? 0 : (cached_rows[1] == vertical.b ? 1 : -1));
        if (bank_b < 0) {
            bank_b = 1 - bank_a;
            load_row(source, rows, bank_b, vertical.b, source_width);
            cached_rows[bank_b] = vertical.b;
        }
    InterpolateResizePairs:
        for (int pair = 0; pair < (width + 1) / 2; ++pair) {
#pragma HLS PIPELINE II=1
            ResizeAxis horizontal[2];
#pragma HLS ARRAY_PARTITION variable=horizontal complete dim=1
            horizontal[0] = decode_axis(fastv2_profile::kResizeXAxis[x_offset + pair * 2]);
            horizontal[1] = pair * 2 + 1 < width ?
                decode_axis(fastv2_profile::kResizeXAxis[x_offset + pair * 2 + 1]) : horizontal[0];
            uint8_t samples[2][4];
#pragma HLS ARRAY_PARTITION variable=samples complete dim=0
            const int first = horizontal[0].a;
            for (int row_bank = 0; row_bank < 2; ++row_bank) {
#pragma HLS UNROLL
                for (int bank = 0; bank < 4; ++bank) {
#pragma HLS UNROLL
                    const int index = (first >> 2) + (bank < (first & 3) ? 1 : 0);
                    samples[row_bank][bank] = cached_rows[row_bank] >= 0 && index * 4 + bank < source_width
                        ? rows[row_bank][bank][index] : uint8_t(0);
                }
            }
            uint16_t packed = 0;
            for (int lane = 0; lane < 2; ++lane) {
#pragma HLS UNROLL
                if (pair * 2 + lane < width) {
                    const ResizeAxis axis = horizontal[lane];
                    const uint8_t a0 = samples[bank_a][axis.a & 3];
                    const uint8_t a1 = samples[bank_a][axis.b & 3];
                    const uint8_t b0 = samples[bank_b][axis.a & 3];
                    const uint8_t b1 = samples[bank_b][axis.b & 3];
                    /* All operands are nonnegative. Horizontal sums <=522240;
                       vertical products <=66846720, so 32 bits suffice exactly. */
                    const uint32_t top = uint32_t(a0) * uint32_t(2048 - axis.weight) + uint32_t(a1) * uint32_t(axis.weight);
                    const uint32_t bottom = uint32_t(b0) * uint32_t(2048 - axis.weight) + uint32_t(b1) * uint32_t(axis.weight);
                    const uint32_t value = ((top >> 4) * uint32_t(2048 - vertical.weight) >> 16) +
                                          ((bottom >> 4) * uint32_t(vertical.weight) >> 16);
                    packed |= uint16_t(uint8_t((value + 2) >> 2)) << (lane * 8);
                }
            }
            pairs[pair & 3][pair >> 2] = packed;
        }
        const int completed = pack_row(pairs, words, width, y, height, carry);
        std::memcpy(destination + ((y * width) >> 3), words, row_transfer_bytes(completed));
    }
    return fastv2::kOk;
}
