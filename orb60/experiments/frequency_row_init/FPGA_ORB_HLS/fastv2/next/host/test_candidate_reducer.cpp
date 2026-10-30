// Independent sorted-grid oracle for the register-score / BRAM-payload reducer.
#include "fastv2.hpp"
#include "golden.hpp"
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>

extern "C" int next_test_candidate_reduce(const uint64_t*, int, int, int, int, int, uint64_t*, uint64_t*);

static void run(int level, int pattern, int high, int dual, int capacity) {
    const int widths[] = {960, 800, 667, 556, 463, 386, 322, 268};
    const int heights[] = {720, 600, 500, 417, 347, 289, 241, 201};
    const int budgets[] = {217, 181, 151, 126, 105, 87, 73, 60};
    const int w = widths[level] - 32, h = heights[level] - 32;
    const int side = int(orb_golden::isqrt(uint64_t(w) * h / budgets[level]));
    const int cols = w / side, rows = h / side;
    const int minimum = dual ? 7 : high;
    std::vector<orb_golden::Point> points;
    std::vector<uint64_t> tokens;
    uint32_t state = 0x411ad705u + unsigned(level + pattern);
    if (pattern != 3) for (int y = 3; y < h - 3; ++y) for (int x = 3; x < w - 3; ++x) {
        state = state * 1664525u + 1013904223u;
        const int score = pattern == 1 ? minimum : pattern == 2 ?
            std::min(254, minimum + (x & 7) * 9) : minimum + int(state % unsigned(255 - minimum));
        const int tile = (x * 3 + y * 7) % 1024;
        points.push_back({x, y, score, tile});
        const int cell = std::min(y / side, rows - 1) * cols + std::min(x / side, cols - 1);
        const uint64_t packed = uint64_t(x) | (uint64_t(y) << 11) | (uint64_t(score) << 22) | (uint64_t(tile) << 30);
        tokens.push_back(packed | (uint64_t(cell) << 41));
    }
    orb_golden::Config config;
    config.threshold = high;
    config.low_threshold = 7;
    config.dual_threshold = dual != 0;
    orb_golden::Layer layer;
    const auto winners = orb_golden::select_grid(points, w, h, budgets[level], layer, &config);
    const bool overflow = int(winners.size()) > capacity;
    const int tc = w / 35, tr = h / 35;
    const fastv2::Result expected = {0x20000u, overflow ? 4 : 0,
        int(points.size()), int(winners.size()), layer.cell_side, layer.cell_cols, layer.cell_rows,
        layer.empty_cells, layer.fallback_cells, tc, tr, (w + tc - 1) / tc, (h + tr - 1) / tr, 0, 0, 0};
    constexpr uint64_t poison = UINT64_C(0xa5a5a5a5a5a5a5a5);
    std::vector<uint64_t> output(2002, poison), wanted(2002, poison);
    uint64_t summary[10]; std::fill(summary, summary + 10, poison);
    if (!overflow) for (size_t i = 0; i < winners.size(); ++i) {
        const auto& p = winners[i];
        const fastv2::Point point = {p.x, p.y, p.score, p.tile};
        std::memcpy(wanted.data() + 1 + 2 * i, &point, sizeof(point));
    }
    const int status = next_test_candidate_reduce(tokens.data(), int(tokens.size()), level,
        high, dual, capacity, output.data() + 1, summary + 1);
    if (status != expected.status || std::memcmp(summary + 1, &expected, sizeof(expected)) ||
        output != wanted || summary[0] != poison || summary[9] != poison)
        throw std::runtime_error("reducer exact ordering/fallback/capacity/guard mismatch");
}

int main() {
    try {
        int cases = 0;
        for (int level = 0; level < 8; ++level) for (int pattern = 0; pattern < 4; ++pattern) {
            run(level, pattern, 20, 1, 1000); ++cases;
            run(level, pattern, 20, 0, 1000); ++cases;
        }
        run(7, 1, 255, 1, 1000); ++cases;
        run(5, 0, 20, 1, 0); ++cases;
        run(7, 3, 20, 1, 0); ++cases;
        std::cout << "CANDIDATE_REDUCER_EXACT_PASS cases=" << cases
                  << " consecutive_same_cell=true equal_score_raster_ties=true cell_revisit=true guards=true\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "CANDIDATE_REDUCER_EXACT_FAIL " << error.what() << '\n';
        return 1;
    }
}
