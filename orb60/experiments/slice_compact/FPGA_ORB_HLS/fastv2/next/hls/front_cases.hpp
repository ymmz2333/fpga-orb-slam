#pragma once
#include "fastv2_profile_rom.hpp"
#include <cstdint>
#include <vector>

/** Deterministic transaction parameters shared by the CPU exporter and RTL bench. */
struct FrontCase {
    int level, pattern, high, low, dual, capacity, budget_delta;
};
/** Structured, empty, dense, fallback, strength-sort, fault and restart cases. */
static const FrontCase kFrontCases[] = {
    {7, 0, 20, 7, 1, 1000, 0},
    {7, 1, 20, 7, 1, 0, 0},
    {7, 2, 40, 40, 0, 1000, 0},
    {7, 2, 255, 40, 1, 1000, 0},
    {5, 2, 40, 40, 0, 1000, 0},
    {7, 2, 40, 40, 0, 0, 0},
    {0, 2, 1, 1, 1, 1000, 0},
    {7, 0, 20, 7, 0, 1000, 1},
    {7, 0, 20, 7, 0, 1000, 0},
    {7, 2, 40, 40, 0, 53, 0},
    {7, 2, 40, 40, 0, 54, 0}
};
static const int kFrontCaseCount = int(sizeof(kFrontCases) / sizeof(kFrontCases[0]));

/**
 * @brief Generate one reproducible transaction input without using HLS output.
 * @param test Frozen level, pattern and control parameters.
 * @return Row-major grayscale bytes for the selected frozen geometry.
 * @note Pattern 0 is structured detail, 1 is zero and 2 is seeded pseudorandom.
 */
inline std::vector<uint8_t> front_case_pixels(const FrontCase& test) {
    const auto& p = fastv2_profile::kProfiles[test.level];
    std::vector<uint8_t> pixels(size_t(p.width) * size_t(p.height));
    uint32_t state = UINT32_C(0x94a00103) + uint32_t(test.level);
    for (int y = 0; y < p.height; ++y) for (int x = 0; x < p.width; ++x) {
        state = state * UINT32_C(1664525) + UINT32_C(1013904223);
        const int checker = ((x / 5 + y / 7) & 1) ? 91 : 13;
        pixels[size_t(y) * p.width + x] = test.pattern == 3 ? 255 : test.pattern == 1 ? 0 :
            (test.pattern == 2 ? uint8_t(state >> 24) :
             uint8_t((x * 17 + y * 29 + checker + (x * y) % 67) & 255));
    }
    return pixels;
}
