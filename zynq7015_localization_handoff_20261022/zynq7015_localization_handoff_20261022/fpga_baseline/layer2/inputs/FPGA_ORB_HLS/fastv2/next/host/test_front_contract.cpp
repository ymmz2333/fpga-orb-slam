#include "fastv2.hpp"
#include "fastv2_profile_rom.hpp"
#include "golden.hpp"
#include <algorithm>
#include <cstring>
#include <iostream>
#include <stdexcept>

uint8_t next_test_fast_score(uint8_t center, const uint8_t ring[16]);
extern "C" int next_baseline_front_hls(const uint64_t*, fastv2::Point*, fastv2::Result*,
                                      int, int, int, int, int, int, int);

/**
 * @brief Compute an independent, direct nine-contiguous-sample FAST score.
 * @param center Center byte.
 * @param ring Radius-three samples in clockwise order.
 * @return Exact public score, including the minus-one adjustment.
 */
static uint8_t direct_score(uint8_t center, const uint8_t ring[16]) {
    int best = 0;
    for (int start = 0; start < 16; ++start) {
        int low = 255, high = -255;
        for (int tap = 0; tap < 9; ++tap) {
            const int value = int(ring[(start + tap) & 15]) - int(center);
            low = std::min(low, value); high = std::max(high, value);
        }
        best = std::max(best, std::max(low, -high));
    }
    return uint8_t(best > 0 ? best - 1 : 0);
}

/**
 * @brief Check shared extrema for bright/dark wraparound arcs and random rings.
 * @throws std::runtime_error On the first score mismatch.
 */
static void check_score() {
    uint8_t ring[16];
    const int centers[] = {0, 1, 127, 128, 254, 255};
    for (int center : centers) for (int start = 0; start < 16; ++start) {
        for (int polarity = 0; polarity < 2; ++polarity) {
            std::fill(ring, ring + 16, uint8_t(center));
            for (int tap = 0; tap < 9; ++tap) ring[(start + tap) & 15] = polarity ? 255 : 0;
            if (next_test_fast_score(uint8_t(center), ring) != direct_score(uint8_t(center), ring))
                throw std::runtime_error("FAST shared-extrema arc mismatch");
        }
    }
    uint32_t state = UINT32_C(0x94a00103);
    for (int trial = 0; trial < 10000; ++trial) {
        state = state * UINT32_C(1664525) + UINT32_C(1013904223);
        const uint8_t center = uint8_t(state >> 24);
        for (auto& pixel : ring) {
            state = state * UINT32_C(1664525) + UINT32_C(1013904223);
            pixel = uint8_t(state >> 24);
        }
        if (next_test_fast_score(center, ring) != direct_score(center, ring))
            throw std::runtime_error("FAST shared-extrema random mismatch");
    }
}

/**
 * @brief Build repeatable dense inputs for all frozen layer geometries.
 * @param level Frozen layer 0..7.
 * @param zero Whether to use a constant zero image instead of pseudorandom bytes.
 * @return Reference-compatible image.
 */
static orb_golden::Image make_image(int level, bool zero = false) {
    const auto& profile = fastv2_profile::kProfiles[level];
    orb_golden::Image image(profile.width, profile.height);
    uint32_t state = UINT32_C(0x94a00103) + uint32_t(level);
    for (auto& pixel : image.pixels) {
        state = state * UINT32_C(1664525) + UINT32_C(1013904223);
        pixel = zero ? 0 : uint8_t(state >> 24);
    }
    return image;
}

/**
 * @brief Compare CPU selection and, within its capacity, the untouched baseline.
 * @param image Input image for a legal frozen profile.
 * @param level Frozen layer index.
 * @param high Inclusive high threshold.
 * @param low Inclusive fallback threshold.
 * @param dual Fallback enable flag.
 * @param capacity Advertised selected record capacity.
 * @param truncated Number of successful budget-truncation cases observed.
 * @param fallback Number of successful fallback cells observed.
 * @return Transaction status, checked against baseline and independent CPU.
 * @throws std::runtime_error On status, 64-byte summary, records or guard mismatch.
 * @note Baseline-overflow cases intentionally extend behavior: all candidates are
 *       reduced and checked against CPU instead of returning a frame-store error.
 */
static int check_case(const orb_golden::Image& image, int level, int high, int low,
                      int dual, int capacity, int& truncated, int& fallback) {
    const auto& p = fastv2_profile::kProfiles[level];
    std::vector<uint64_t> words((image.pixels.size() + 7) / 8, 0);
    std::memcpy(words.data(), image.pixels.data(), image.pixels.size());
    std::vector<fastv2::Point> actual(1002), baseline(1002);
    std::memset(actual.data(), 0xa5, actual.size() * sizeof(actual[0]));
    std::memset(baseline.data(), 0xa5, baseline.size() * sizeof(baseline[0]));
    fastv2::Result result = {}, expected_summary = {};
    const int status = fastv2_front_hls(words.data(), actual.data() + 1, &result,
        p.width, p.height, p.budget, high, low, dual, capacity);
    const int expected_status = next_baseline_front_hls(words.data(), baseline.data() + 1,
        &expected_summary, p.width, p.height, p.budget, high, low, dual, capacity);
    if (expected_status != fastv2::kCandidateCapacityExceeded &&
        (status != expected_status || std::memcmp(&result, &expected_summary, sizeof(result)) ||
         std::memcmp(actual.data(), baseline.data(), actual.size() * sizeof(actual[0]))))
        throw std::runtime_error("front stream differs from baseline bytes level=" + std::to_string(level));
    orb_golden::Config config;
    config.threshold = high; config.low_threshold = low; config.dual_threshold = dual != 0;
    const auto candidates = orb_golden::tiled_candidates(image, config);
    if (result.candidate_count != int(candidates.size())) throw std::runtime_error("CPU candidate count mismatch");
    orb_golden::Layer layer;
    const auto selected = orb_golden::select_grid(candidates, p.effective_width,
        p.effective_height, p.budget, layer, &config);
    const int cpu_status = int(selected.size()) > capacity ? fastv2::kSelectedCapacityExceeded : fastv2::kOk;
    if (status != cpu_status) throw std::runtime_error("CPU status mismatch");
    if (status == fastv2::kOk) {
        if (result.selected_count != int(selected.size()) || result.empty_cells != layer.empty_cells ||
            result.fallback_cells != layer.fallback_cells) throw std::runtime_error("CPU grid metadata mismatch");
        for (size_t i = 0; i < selected.size(); ++i) {
            const auto& a = actual[i + 1]; const auto& b = selected[i];
            if (a.x != b.x || a.y != b.y || a.score != b.score || a.tile != b.tile)
                throw std::runtime_error("CPU selected point/order mismatch");
        }
        if (layer.cell_cols * layer.cell_rows - layer.empty_cells > p.budget) ++truncated;
        fallback += result.fallback_cells;
    }
    const unsigned char* bytes = reinterpret_cast<const unsigned char*>(actual.data());
    const size_t written = status == fastv2::kOk ? size_t(result.selected_count) : 0;
    for (size_t i = 0; i < actual.size() * sizeof(actual[0]); ++i) {
        if ((i < sizeof(actual[0]) || i >= (written + 1) * sizeof(actual[0])) && bytes[i] != 0xa5)
            throw std::runtime_error("front changed guard/unused output bytes");
    }
    std::cout << "FRONT_CONTRACT_CASE level=" << level << " high=" << high << " low=" << low
              << " dual=" << dual << " status=" << status << " candidates=" << candidates.size()
              << " selected=" << result.selected_count << " fallback=" << result.fallback_cells << '\n';
    return status;
}

/**
 * @brief Exercise reduced storage, repeat transactions, extrema, faults and sorting.
 * @return Zero only when all checks pass and required algorithm branches were hit.
 */
int main() {
    try {
        check_score();
        for (const auto& p : fastv2_profile::kProfiles) {
            if (p.cell_cols * p.cell_rows > 204 || p.width > 960 || p.height > 720)
                throw std::runtime_error("frozen front storage contract changed");
        }
        int truncated = 0, fallback = 0;
        for (int level = 7; level >= 0; --level) {
            const auto image = make_image(level);
            check_case(image, level, 40, 40, 0, 1000, truncated, fallback);
            check_case(image, level, 255, 40, 1, 1000, truncated, fallback);
            check_case(image, level, 120, 120, 0, 1000, truncated, fallback);
        }
        if (check_case(make_image(0), 0, 1, 1, 1, 1000, truncated, fallback) != fastv2::kOk)
            throw std::runtime_error("dense candidate stream did not complete");
        if (check_case(make_image(7), 7, 40, 40, 0, 0, truncated, fallback) != fastv2::kSelectedCapacityExceeded)
            throw std::runtime_error("selected capacity branch not covered");
        check_case(make_image(7, true), 7, 255, 255, 1, 0, truncated, fallback);
        if (truncated == 0 || fallback == 0) throw std::runtime_error("budget/fallback branch not covered");
        uint64_t image[1] = {}; fastv2::Point selected = {3, 4, 5, 6}; fastv2::Result result = {};
        if (fastv2_front_hls(image, &selected, &result, 268, 201, 61, 20, 7, 1, 1) != fastv2::kInvalidArgument ||
            result.status != fastv2::kInvalidArgument || result.candidate_count != 0 || selected.x != 3)
            throw std::runtime_error("invalid-profile early rejection failed");
        std::cout << "NEXT_FRONT_CONTRACT_PASS score_cases=10192 baseline_nonoverflow_bytes=PASS CPU=PASS truncated="
                  << truncated << " fallback=" << fallback << " dense_over8192=PASS faults=PASS guards=PASS\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "NEXT_FRONT_CONTRACT_FAIL " << error.what() << '\n';
        return 1;
    }
}
