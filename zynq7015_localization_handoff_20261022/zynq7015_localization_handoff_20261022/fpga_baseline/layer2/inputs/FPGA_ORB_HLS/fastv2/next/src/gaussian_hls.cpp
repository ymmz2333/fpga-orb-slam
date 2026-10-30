#include "fastv2.hpp"
#include "fastv2_profile_rom.hpp"
#include "next_gaussian.hpp"
#include "next_stream.hpp"
#include <cstring>

namespace {
/**
 * @brief Exploit the exact symmetric seven-tap Gaussian kernel.
 * @param samples Seven nonnegative bytes or horizontal 16-bit sums.
 * @return Unrounded weighted sum, bounded by 16711680 for legal inputs.
 * @note Pair sums are widened before addition; symmetry changes no rounding.
 */
template <typename Pixel>
uint32_t gaussian_sum(const Pixel samples[7]) {
#pragma HLS INLINE
#pragma HLS ARRAY_PARTITION variable=samples complete dim=1
    const uint32_t outer = (uint32_t(samples[0]) + uint32_t(samples[6])) * 18u;
    const uint32_t middle = (uint32_t(samples[1]) + uint32_t(samples[5])) * 34u;
    const uint32_t inner = (uint32_t(samples[2]) + uint32_t(samples[4])) * 48u;
    const uint32_t center = uint32_t(samples[3]) * 56u;
    return (outer + middle) + (inner + center);
}

/**
 * @brief Reflect a radius-three halo without repeating the boundary pixel.
 * @param coordinate Sample coordinate, at most three pixels outside an edge.
 * @param extent Active dimension, at least 201 in the frozen profiles.
 * @return Exact BORDER_REFLECT_101 sample index.
 */
int reflect(int coordinate, int extent) {
#pragma HLS INLINE
    if (coordinate < 0) return -coordinate;
    if (coordinate >= extent) return 2 * extent - coordinate - 2;
    return coordinate;
}

/**
 * @brief Burst-read bounded DDR blocks and publish exactly one token per pixel.
 * @param source Packed row-major input bytes.
 * @param output Single-producer raw-pixel stream.
 * @param total_pixels Number of valid pixels, excluding final-word padding.
 * @note Load and unpack are sequential inside this stage; downstream stages overlap.
 */
void read_pixels(const uint64_t* source, hls::stream<uint8_t>& output, int total_pixels) {
#pragma HLS INLINE off
    uint64_t block[64];
#pragma HLS RESOURCE variable=block core=RAM_2P_BRAM
ReadGaussianBlocks:
    for (int first = 0; first < total_pixels; first += 512) {
        const int count = total_pixels - first < 512 ? total_pixels - first : 512;
        const int words = (count + 7) >> 3;
        std::memcpy(block, source + (first >> 3), size_t(words) * sizeof(uint64_t));
    EmitGaussianRawPixels:
        for (int pixel = 0; pixel < count; ++pixel) {
#pragma HLS PIPELINE II=1
            output.write(uint8_t(block[pixel >> 3] >> ((pixel & 7) * 8)));
        }
    }
}

/**
 * @brief Apply an exact horizontal seven-tap filter as a single-pixel stream stage.
 * @param input Raw row-major pixels; exactly width*height tokens are consumed.
 * @param output Unsaturated horizontal sums, exactly width*height tokens.
 * @param width Active row width.
 * @param height Number of active rows.
 * @note Four head samples and four tail samples implement reflection without rereads.
 */
void horizontal_filter(hls::stream<uint8_t>& input, hls::stream<uint16_t>& output,
                       int width, int height) {
#pragma HLS INLINE off
HorizontalGaussianRows:
    for (int y = 0; y < height; ++y) {
        uint8_t head[4], tail[4] = {}, window[7] = {};
#pragma HLS ARRAY_PARTITION variable=head complete dim=1
#pragma HLS ARRAY_PARTITION variable=tail complete dim=1
#pragma HLS ARRAY_PARTITION variable=window complete dim=1
    ReadGaussianHead:
        for (int x = 0; x < 4; ++x) {
#pragma HLS PIPELINE II=1
            head[x] = input.read();
        }
    HorizontalPixels:
        for (int scan = -3; scan < width + 3; ++scan) {
#pragma HLS PIPELINE II=1
            uint8_t pixel;
            if (scan < 0) pixel = head[-scan];
            else if (scan < 4) pixel = head[scan];
            else if (scan < width) pixel = input.read();
            else pixel = tail[2 - (scan - width)];
            if (scan >= 0 && scan < width) {
                for (int index = 0; index < 3; ++index) {
#pragma HLS UNROLL
                    tail[index] = tail[index + 1];
                }
                tail[3] = pixel;
            }
            for (int tap = 0; tap < 6; ++tap) {
#pragma HLS UNROLL
                window[tap] = window[tap + 1];
            }
            window[6] = pixel;
            if (scan >= 3) {
                output.write(uint16_t(gaussian_sum(window)));
            }
        }
    }
}

/**
 * @brief Apply the vertical seven-tap filter concurrently with the horizontal stage.
 * @param input Horizontal sums in raster order, exactly width*height tokens.
 * @param output Rounded Gaussian bytes, exactly width*height tokens.
 * @param width Active row width, at most 960.
 * @param height Active image height.
 * @note Seven line banks retain the reflected halo. The current write value is
 *       explicitly bypassed, so correctness does not depend on BRAM write-first mode.
 */
void vertical_filter(hls::stream<uint16_t>& input, hls::stream<uint8_t>& output,
                     int width, int height) {
#pragma HLS INLINE off
    uint16_t lines[7][960];
#pragma HLS ARRAY_PARTITION variable=lines complete dim=1
#pragma HLS RESOURCE variable=lines core=RAM_S2P_BRAM
    int slot = 0;
VerticalGaussianRows:
    for (int scan_y = 0; scan_y < height + 3; ++scan_y) {
        const int y = scan_y - 3;
        uint8_t tap_bank[7];
#pragma HLS ARRAY_PARTITION variable=tap_bank complete dim=1
        /* slot tracks scan_y modulo seven with an increment/compare. For active
           output rows each reflected tap is at most six rows behind scan_y. */
        for (int tap = 0; tap < 7; ++tap) {
#pragma HLS UNROLL
            const int delta = scan_y >= 3 ? reflect(y + tap - 3, height) - scan_y : 0;
            const int bank = slot + delta;
            tap_bank[tap] = uint8_t(bank < 0 ? bank + 7 : bank);
        }
    VerticalPixels:
        for (int x = 0; x < width; ++x) {
#pragma HLS LOOP_FLATTEN off
#pragma HLS PIPELINE II=1
            const uint16_t incoming = scan_y < height ? input.read() : uint16_t(0);
            uint16_t columns[7];
#pragma HLS ARRAY_PARTITION variable=columns complete dim=1
            for (int bank = 0; bank < 7; ++bank) {
#pragma HLS UNROLL
                if (scan_y < height && bank == slot) {
                    columns[bank] = incoming;
                    lines[bank][x] = incoming;
                } else {
                    columns[bank] = scan_y >= 6 || bank <= scan_y ? lines[bank][x] : uint16_t(0);
                }
            }
            if (scan_y >= 3) {
                uint16_t samples[7];
#pragma HLS ARRAY_PARTITION variable=samples complete dim=1
                for (int tap = 0; tap < 7; ++tap) {
#pragma HLS UNROLL
                    samples[tap] = columns[tap_bank[tap]];
                }
                const uint32_t sum = gaussian_sum(samples);
                output.write(uint8_t((sum + 32768u) >> 16));
            }
        }
        slot = slot == 6 ? 0 : slot + 1;
    }
}

/**
 * @brief Pack the flat pixel stream without per-row padding or two-lane feedback.
 * @param input Gaussian bytes in raster order.
 * @param output Complete little-endian 64-bit words.
 * @param total_pixels Active byte count, excluding output padding.
 * @note Emits ceil(total_pixels/8) words and zeroes unused final-word bytes.
 */
void pack_pixels(hls::stream<uint8_t>& input, hls::stream<uint64_t>& output, int total_pixels) {
#pragma HLS INLINE off
    uint64_t carry = 0;
PackGaussianPixels:
    for (int index = 0; index < total_pixels; ++index) {
#pragma HLS PIPELINE II=1
        carry |= uint64_t(input.read()) << ((index & 7) * 8);
        if ((index & 7) == 7) {
            output.write(carry);
            carry = 0;
        }
    }
    if ((total_pixels & 7) != 0) output.write(carry);
}

/**
 * @brief Drain bounded word blocks and write contiguous DDR bursts.
 * @param input Packed output tokens, exactly ceil(total_pixels/8).
 * @param destination Disjoint packed output image.
 * @param total_pixels Active output byte count.
 * @note A full block is collected before its write; FIFO backpressure is intentional.
 */
void write_pixels(hls::stream<uint64_t>& input, uint64_t* destination, int total_pixels) {
#pragma HLS INLINE off
    uint64_t block[64];
#pragma HLS RESOURCE variable=block core=RAM_2P_BRAM
    const int total_words = (total_pixels + 7) >> 3;
WriteGaussianBlocks:
    for (int first = 0; first < total_words; first += 64) {
        const int words = total_words - first < 64 ? total_words - first : 64;
    CollectGaussianWords:
        for (int word = 0; word < words; ++word) {
#pragma HLS PIPELINE II=1
            block[word] = input.read();
        }
        std::memcpy(destination + first, block, size_t(words) * sizeof(uint64_t));
    }
}

/**
 * @brief Connect single-producer/consumer stages with bounded hardware FIFOs.
 * @param source Input packed image.
 * @param destination Disjoint output packed image.
 * @param width Active row width.
 * @param height Active row count.
 * @param total_pixels Precomputed width*height, kept outside the DATAFLOW region.
 * @return Zero on exact token balance, invalid-argument status on host token imbalance.
 * @note C models check values/counts, not bounded-FIFO liveness; RTL co-simulation
 *       must prove backpressure, startup and drain behavior before integration.
 */
int gaussian_dataflow(const uint64_t* source, uint64_t* destination, int width, int height,
                      int total_pixels) {
#pragma HLS INLINE off
    static hls::stream<uint8_t> raw;
    static hls::stream<uint16_t> horizontal;
    static hls::stream<uint8_t> blurred;
    static hls::stream<uint64_t> packed;
#pragma HLS STREAM variable=raw depth=64
#pragma HLS STREAM variable=horizontal depth=64
#pragma HLS STREAM variable=blurred depth=64
#pragma HLS STREAM variable=packed depth=16
#pragma HLS DATAFLOW
    read_pixels(source, raw, total_pixels);
    horizontal_filter(raw, horizontal, width, height);
    vertical_filter(horizontal, blurred, width, height);
    pack_pixels(blurred, packed, total_pixels);
    write_pixels(packed, destination, total_pixels);
#ifndef __SYNTHESIS__
    if (!raw.empty() || !horizontal.empty() || !blurred.empty() || !packed.empty()) {
        return fastv2::kInvalidArgument;
    }
#endif
    return fastv2::kOk;
}
} // namespace

/** @copydoc fastv2_gaussian_hls */
extern "C" int fastv2_gaussian_hls(const uint64_t* source, uint64_t* destination, int level) {
#pragma HLS INTERFACE m_axi port=source offset=slave bundle=gmem0 depth=86400 max_read_burst_length=64 num_read_outstanding=2 max_write_burst_length=2 num_write_outstanding=1
#pragma HLS INTERFACE m_axi port=destination offset=slave bundle=gmem1 depth=86400 max_write_burst_length=64 num_write_outstanding=2 max_read_burst_length=2 num_read_outstanding=1
#pragma HLS INTERFACE s_axilite port=source bundle=control
#pragma HLS INTERFACE s_axilite port=destination bundle=control
#pragma HLS INTERFACE s_axilite port=level bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    if (level < 0 || level > 7) return fastv2::kInvalidArgument;
    const int width = fastv2_profile::kProfiles[level].width;
    const int height = fastv2_profile::kProfiles[level].height;
    return gaussian_dataflow(source, destination, width, height, width * height);
}
