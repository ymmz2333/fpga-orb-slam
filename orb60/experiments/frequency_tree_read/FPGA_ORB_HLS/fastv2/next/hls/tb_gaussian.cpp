#include "next_gaussian.hpp"
#include "fastv2.hpp"
#include <cstdint>
#include <iostream>
#include <vector>

/**
 * @brief Map a radius-three sample to an independent reflect-101 reference index.
 * @param index Possibly out-of-range sample coordinate.
 * @param extent Active image-axis length, greater than three.
 * @return Mirrored active coordinate; the edge pixel is not repeated.
 */
static int reflect_index(int index, int extent) {
    while (index < 0 || index >= extent) {
        index = index < 0 ? -index : 2 * extent - 2 - index;
    }
    return index;
}

/**
 * @brief Verify one Gaussian transaction, exact bytes, padding and output bounds.
 * @param level Frozen pyramid level in 0..7.
 * @param width Active row width.
 * @param height Number of active rows.
 * @param constant If true, use maximum-valued input; otherwise use structured detail.
 * @return True only when status, every pixel and guard words match.
 */
static bool run_case(int level, int width, int height, bool constant) {
    const int kernel[7] = {18, 34, 48, 56, 48, 34, 18};
    const size_t pixels = size_t(width) * height;
    const size_t words = (pixels + 7u) / 8u;
    const uint64_t guard = UINT64_C(0xdeadbeef6a5a0ff0);
    std::vector<uint8_t> input(pixels);
    std::vector<uint16_t> horizontal(pixels);
    std::vector<uint64_t> packed(words, 0);
    std::vector<uint64_t> actual(words + 2u, guard);
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            const size_t index = size_t(y) * width + x;
            input[index] = constant ? 255u : uint8_t((x * 37 + y * 53 + x * y * 3 + level * 19) & 255);
            packed[index >> 3] |= uint64_t(input[index]) << ((index & 7u) * 8u);
        }
    }
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            unsigned sum = 0;
            for (int tap = 0; tap < 7; ++tap) {
                sum += unsigned(kernel[tap]) * input[size_t(y) * width + reflect_index(x + tap - 3, width)];
            }
            horizontal[size_t(y) * width + x] = uint16_t(sum);
        }
    }
    if (fastv2_gaussian_hls(packed.data(), actual.data() + 1, level) != fastv2::kOk) {
        std::cerr << "NEXT_GAUSSIAN_FAIL status level=" << level << '\n';
        return false;
    }
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            unsigned sum = 0;
            for (int tap = 0; tap < 7; ++tap) {
                sum += unsigned(kernel[tap]) * horizontal[size_t(reflect_index(y + tap - 3, height)) * width + x];
            }
            const uint8_t expected = uint8_t((sum + 32768u) >> 16);
            const size_t index = size_t(y) * width + x;
            const uint8_t observed = uint8_t(actual[1 + (index >> 3)] >> ((index & 7u) * 8u));
            if (observed != expected) {
                std::cerr << "NEXT_GAUSSIAN_FAIL level=" << level << " pixel=" << x << ',' << y
                          << " actual=" << unsigned(observed) << " expected=" << unsigned(expected) << '\n';
                return false;
            }
        }
    }
    if (actual.front() != guard || actual.back() != guard ||
        ((pixels & 7u) != 0 && (actual[words] >> ((pixels & 7u) * 8u)) != 0)) {
        std::cerr << "NEXT_GAUSSIAN_FAIL output bounds/padding level=" << level << '\n';
        return false;
    }
    std::cout << "NEXT_GAUSSIAN_CASE_PASS level=" << level << " constant=" << constant << '\n';
    return true;
}

/**
 * @brief Run reproducible Gaussian cases; HLS uses the smallest frozen profile.
 * @return Zero only when all comparisons pass, one on the first failure.
 * @note Multiple transactions check that line-buffer state is not reused incorrectly.
 */
int main() {
    const int widths[8] = {960, 800, 667, 556, 463, 386, 322, 268};
    const int heights[8] = {720, 600, 500, 417, 347, 289, 241, 201};
#ifdef FASTV2_HLS_CSIM
    const int first_level = 7;
#else
    const int first_level = 0;
#endif
    for (int level = first_level; level < 8; ++level) {
        if (!run_case(level, widths[level], heights[level], false) ||
            !run_case(level, widths[level], heights[level], true)) return 1;
    }
    std::cout << "NEXT_GAUSSIAN_PASS\n";
    return 0;
}
