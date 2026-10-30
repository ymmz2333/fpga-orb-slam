#pragma once
#include <cstdint>
#include <iostream>
#include <vector>

namespace next_image_test {
/** Frozen geometry, independent of the DUT's generated profile/axis ROM. */
static const int kWidths[8] = {960, 800, 667, 556, 463, 386, 322, 268};
static const int kHeights[8] = {720, 600, 500, 417, 347, 289, 241, 201};
static const size_t kPortWords = 86400; // Both declared AXI depths, not active size.
static const uint64_t kPoison = UINT64_C(0xdeadbeef6a5a0ff0);
/** Pattern 0: structured; 1: zero; 2: 255; 3: deterministic pseudorandom. */
struct ImageCase { int level, pattern; };
static const ImageCase kResizeCases[] = {
    {6, 0}, {0, 0}, {1, 0}, {2, 0}, {3, 0}, {4, 0}, {5, 0},
    {6, 1}, {6, 2}, {6, 3}, {-1, 0}, {7, 0}, {6, 0}
};
static const ImageCase kGaussianCases[] = {
    {7, 0}, {0, 0}, {1, 0}, {2, 0}, {3, 0}, {4, 0}, {5, 0}, {6, 0},
    {7, 1}, {7, 2}, {7, 3}, {-1, 0}, {8, 0}, {7, 0}
};
static const int kResizeCaseCount = int(sizeof(kResizeCases) / sizeof(kResizeCases[0]));
static const int kGaussianCaseCount = int(sizeof(kGaussianCases) / sizeof(kGaussianCases[0]));

/**
 * @brief Build deterministic grayscale data without calling a DUT or its ROM.
 * @param test Legal frozen level and one of the four input patterns.
 * @return Flat active bytes, with no row padding.
 * @note Pseudorandom seed is 0x193ad501 plus the level.
 */
inline std::vector<uint8_t> pixels(const ImageCase& test) {
    const int width = kWidths[test.level], height = kHeights[test.level];
    std::vector<uint8_t> result(size_t(width) * size_t(height));
    uint32_t state = UINT32_C(0x193ad501) + uint32_t(test.level);
    for (int y = 0; y < height; ++y) for (int x = 0; x < width; ++x) {
        state = state * UINT32_C(1664525) + UINT32_C(1013904223);
        result[size_t(y) * width + x] = test.pattern == 1 ? 0 :
            (test.pattern == 2 ? 255 : (test.pattern == 3 ? uint8_t(state >> 24) :
             uint8_t((x * 37 + y * 53 + x * y * 3 + test.level * 19 + 17) & 255)));
    }
    return result;
}

/**
 * @brief Pack a full declared AXI buffer with poisoned unused storage.
 * @param active Flat active image bytes; empty for rejected transactions.
 * @param output True to zero final output padding; false to poison input padding.
 * @return Exactly 86400 words, safe for the HLS co-simulation adapter to marshal.
 */
inline std::vector<uint64_t> pack(const std::vector<uint8_t>& active, bool output) {
    std::vector<uint64_t> result(kPortWords, kPoison);
    if (output) for (size_t word = 0; word < (active.size() + 7u) / 8u; ++word) result[word] = 0;
    for (size_t index = 0; index < active.size(); ++index) {
        const unsigned shift = unsigned(index & 7u) * 8u;
        const uint64_t mask = UINT64_C(255) << shift;
        result[index >> 3] = (result[index >> 3] & ~mask) | (uint64_t(active[index]) << shift);
    }
    return result;
}

/** Independent half-pixel axis coordinate and Q0.11 interpolation weight. */
struct Axis { int a, b, weight; };

/**
 * @brief Derive resize coordinates using rational ties-to-even arithmetic.
 * @param target Destination coordinate.
 * @param source Source-axis extent.
 * @param destination Destination-axis extent.
 * @return Replicated-edge indices and exact Q0.11 weight, without DUT ROM access.
 */
inline Axis axis(int target, int source, int destination) {
    const int64_t numerator = int64_t(2 * target + 1) * source - destination;
    const int64_t denominator = int64_t(2) * destination;
    int64_t a = numerator / denominator, remainder = numerator % denominator;
    if (remainder < 0) { --a; remainder += denominator; }
    if (a < 0) return {0, 0, 0};
    if (a >= source - 1) return {source - 1, source - 1, 0};
    const int64_t scaled = remainder * 2048;
    int64_t weight = scaled / denominator;
    const int64_t fraction = scaled % denominator;
    if (fraction > denominator - fraction ||
        (fraction == denominator - fraction && (weight & 1))) ++weight;
    return {int(a), int(a + 1), int(weight)};
}

/**
 * @brief Compute exact reference resize bytes using independent 64-bit arithmetic.
 * @param input Active source pixels for the given level.
 * @param level Legal transition index in 0..6.
 * @return Flat destination bytes, preserving the CPU's staged shifts/rounding.
 */
inline std::vector<uint8_t> resize(const std::vector<uint8_t>& input, int level) {
    const int sw = kWidths[level], sh = kHeights[level];
    const int dw = kWidths[level + 1], dh = kHeights[level + 1];
    std::vector<Axis> horizontal;
    for (int x = 0; x < dw; ++x) horizontal.push_back(axis(x, sw, dw));
    std::vector<uint8_t> result(size_t(dw) * dh);
    for (int y = 0; y < dh; ++y) {
        const Axis v = axis(y, sh, dh);
        for (int x = 0; x < dw; ++x) {
            const Axis h = horizontal[x];
            const int64_t top = int64_t(input[size_t(v.a) * sw + h.a]) * (2048 - h.weight) +
                                int64_t(input[size_t(v.a) * sw + h.b]) * h.weight;
            const int64_t bottom = int64_t(input[size_t(v.b) * sw + h.a]) * (2048 - h.weight) +
                                   int64_t(input[size_t(v.b) * sw + h.b]) * h.weight;
            const int64_t value = ((top >> 4) * (2048 - v.weight) >> 16) +
                                  ((bottom >> 4) * v.weight >> 16);
            result[size_t(y) * dw + x] = uint8_t((value + 2) >> 2);
        }
    }
    return result;
}

/**
 * @brief Map an out-of-range coordinate using independent reflect-101 iteration.
 * @param coordinate Sample coordinate, possibly outside the image.
 * @param extent Axis length, greater than three.
 * @return Reflected valid coordinate; the edge pixel is not repeated.
 */
inline int reflect(int coordinate, int extent) {
    while (coordinate < 0 || coordinate >= extent)
        coordinate = coordinate < 0 ? -coordinate : 2 * extent - 2 - coordinate;
    return coordinate;
}

/**
 * @brief Compute Gaussian bytes using direct seven-tap reference convolution.
 * @param input Active source pixels for the given frozen level.
 * @param level Legal level in 0..7.
 * @return Exact reflect-101 output; rounding occurs only after both passes.
 * @note No symmetric-pair optimization or DUT line-bank/FIFO logic is reused.
 */
inline std::vector<uint8_t> gaussian(const std::vector<uint8_t>& input, int level) {
    const int kernel[7] = {18, 34, 48, 56, 48, 34, 18};
    const int width = kWidths[level], height = kHeights[level];
    std::vector<uint16_t> horizontal(input.size());
    std::vector<uint8_t> result(input.size());
    for (int y = 0; y < height; ++y) for (int x = 0; x < width; ++x) {
        unsigned sum = 0;
        for (int tap = 0; tap < 7; ++tap)
            sum += unsigned(kernel[tap]) * input[size_t(y) * width + reflect(x + tap - 3, width)];
        horizontal[size_t(y) * width + x] = uint16_t(sum);
    }
    for (int y = 0; y < height; ++y) for (int x = 0; x < width; ++x) {
        unsigned sum = 0;
        for (int tap = 0; tap < 7; ++tap)
            sum += unsigned(kernel[tap]) * horizontal[size_t(reflect(y + tap - 3, height)) * width + x];
        result[size_t(y) * width + x] = uint8_t((sum + 32768u) >> 16);
    }
    return result;
}

/**
 * @brief Check the return code and every declared output word, including padding/tail.
 * @param name Kernel diagnostic label.
 * @param index Transaction index in its fixed sequence.
 * @param test Level and input pattern for mismatch context.
 * @param status Actual public return code.
 * @param expected_status CPU interface contract code (0 or 1).
 * @param actual Full declared output buffer after the DUT returns.
 * @param expected Independent packed image plus poisoned untouched region.
 * @return True only when status and all 691200 output bytes match.
 * @note In-depth sentinels prove no writes in the unused declared region, not
 *       arbitrary out-of-range AXI addresses, reset or random-stall coverage.
 */
inline bool check(const char* name, int index, const ImageCase& test, int status,
                  int expected_status, const std::vector<uint64_t>& actual,
                  const std::vector<uint64_t>& expected) {
    bool matches = status == expected_status;
    if (!matches) std::cerr << name << "_FAIL case=" << index << " level=" << test.level
                           << " status=" << status << '/' << expected_status << '\n';
    for (size_t word = 0; word < kPortWords; ++word) if (actual[word] != expected[word]) {
        std::cerr << name << "_FAIL case=" << index << " level=" << test.level
                  << " pattern=" << test.pattern << " word=" << word << " actual="
                  << actual[word] << " expected=" << expected[word] << '\n';
        return false;
    }
    if (matches) std::cout << name << "_CASE_PASS case=" << index << " level=" << test.level
                           << " pattern=" << test.pattern << " status=" << status << '\n';
    return matches;
}
} // namespace next_image_test
