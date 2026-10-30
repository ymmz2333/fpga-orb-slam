#include "fastv2.hpp"
#include "fastv2_profile_rom.hpp"
#include "golden.hpp"
#include "../hls/image_test_reference.hpp"
#include <cstring>
#include <iostream>
#include <stdexcept>

/**
 * @brief Check the frozen four-source-column gathering contract for every pair.
 * @param level Adjacent resize transition index in 0..6.
 * @throws std::runtime_error If an edited profile no longer fits the bank window.
 */
static void check_gather_span(int level) {
    const int width = fastv2_profile::kProfiles[level + 1].width;
    const int offset = fastv2_profile::kResizeXOffsets[level];
    for (int pair = 0; pair < (width + 1) / 2; ++pair) {
        const uint64_t first = fastv2_profile::kResizeXAxis[offset + pair * 2];
        const int start = int(first & 0x3ffu);
        for (int lane = 0; lane < 2 && pair * 2 + lane < width; ++lane) {
            const uint64_t entry = fastv2_profile::kResizeXAxis[offset + pair * 2 + lane];
            const int a = int(entry & 0x3ffu), b = a + 1;
            if (a < start || b < a || b > start + 3) {
                throw std::runtime_error("resize pair exceeds four-source-column bank window");
            }
        }
    }
}

/**
 * @brief Prove that every frozen resize record has a redundant adjacent index.
 * @param level Transition index 0..6.
 * @throws std::runtime_error When deriving b=a+1 would change a source sample.
 */
static void check_adjacent_indices(int level) {
    const auto& source = fastv2_profile::kProfiles[level];
    const auto& destination = fastv2_profile::kProfiles[level + 1];
    for (int dimension = 0; dimension < 2; ++dimension) {
        const auto* table = dimension == 0 ? fastv2_profile::kResizeXAxis : fastv2_profile::kResizeYAxis;
        const int offset = dimension == 0 ? fastv2_profile::kResizeXOffsets[level] : fastv2_profile::kResizeYOffsets[level];
        const int count = dimension == 0 ? destination.width : destination.height;
        const int extent = dimension == 0 ? source.width : source.height;
        for (int index = 0; index < count; ++index) {
            const uint64_t record = table[offset + index];
            const int a = int(record & 0x3ffu), b = a + 1;
            const int weight = int((record >> 10) & 0x7ffu);
            const auto oracle = next_image_test::axis(index, extent, count);
            if (a != oracle.a || b != oracle.b || weight != oracle.weight || b >= extent || record >= (UINT64_C(1) << 21))
                throw std::runtime_error("resize adjacent-index/weight contract failed");
        }
    }
}

/**
 * @brief Verify an actual resize transaction against independent CPU pixels.
 * @param level Adjacent transition in 0..6.
 * @param pattern Zero, maximum or pseudorandom input; includes row-alignment changes.
 * @throws std::runtime_error On status, pixel, padding or guard mismatch.
 */
static void check_transition(int level, int pattern) {
    const int widths[8] = {960, 800, 667, 556, 463, 386, 322, 268};
    const int heights[8] = {720, 600, 500, 417, 347, 289, 241, 201};
    orb_golden::Image input(widths[level], heights[level]);
    uint32_t state = UINT32_C(0x193ad501) + uint32_t(level);
    for (size_t index = 0; index < input.pixels.size(); ++index) {
        state = state * UINT32_C(1664525) + UINT32_C(1013904223);
        input.pixels[index] = pattern == 0 ? 0 : (pattern == 1 ? 255 : uint8_t(state >> 24));
    }
    const auto expected = orb_golden::resize_linear(input, widths[level + 1], heights[level + 1]);
    std::vector<uint64_t> source((input.pixels.size() + 7) / 8, 0);
    std::memcpy(source.data(), input.pixels.data(), input.pixels.size());
    const size_t word_count = (expected.pixels.size() + 7) / 8;
    const uint64_t guard = UINT64_C(0x17deadbeefacac83);
    std::vector<uint64_t> output(word_count + 2, guard);
    if (fastv2_resize_hls(source.data(), output.data() + 1, level) != fastv2::kOk ||
        std::memcmp(output.data() + 1, expected.pixels.data(), expected.pixels.size()) != 0) {
        throw std::runtime_error("resize pixel/status mismatch");
    }
    if (output.front() != guard || output.back() != guard ||
        ((expected.pixels.size() & 7) != 0 &&
         (output[word_count] >> ((expected.pixels.size() & 7) * 8)) != 0)) {
        throw std::runtime_error("resize wrote outside output or left nonzero padding");
    }
}

/**
 * @brief Validate bank gathering, flat row layout and 21 repeated transactions.
 * @return Zero on success; one with deterministic diagnostic on first failure.
 */
int main() {
    try {
        for (int level = 0; level < 7; ++level) {
            check_gather_span(level);
            check_adjacent_indices(level);
            for (int pattern = 0; pattern < 3; ++pattern) check_transition(level, pattern);
        }
        std::cout << "NEXT_RESIZE_LAYOUT_PASS transitions=7 patterns=3 guards=PASS padding=PASS\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "NEXT_RESIZE_LAYOUT_FAIL " << error.what() << '\n';
        return 1;
    }
}
