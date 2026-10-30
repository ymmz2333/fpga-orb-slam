#include "fastv2.hpp"
#include "front_cases.hpp"
#include "golden.hpp"
#include <fstream>
#include <iostream>
#include <stdexcept>

/**
 * @brief Serialize every summary field in ABI order, including reserved zeros.
 * @param out Generated C++ initializer destination.
 * @param r Independent CPU-derived result metadata.
 */
static void write_summary(std::ostream& out, const fastv2::Result& r) {
    out << '{' << r.version << "u," << r.status << ',' << r.candidate_count << ','
        << r.selected_count << ',' << r.cell_side << ',' << r.cell_cols << ','
        << r.cell_rows << ',' << r.empty_cells << ',' << r.fallback_cells << ','
        << r.tile_cols << ',' << r.tile_rows << ',' << r.tile_width << ','
        << r.tile_height << ',' << r.reserved0 << "u," << r.reserved1 << "u,"
        << r.reserved2 << "u}";
}

/**
 * @brief Export small immutable reference tables using independent v1.0 CPU code.
 * @param argc Must be two.
 * @param argv Executable and generated include path.
 * @return Zero when summaries and all point records were written successfully.
 * @note This generator never calls the DUT; C++17 CPU code is kept out of HLS 2018.3.
 */
int main(int argc, char** argv) {
    try {
        if (argc != 2) throw std::runtime_error("expected output include path");
        std::ofstream out(argv[1]);
        if (!out) throw std::runtime_error("cannot open reference include");
        std::vector<fastv2::Result> summaries;
        std::vector<std::vector<orb_golden::Point>> points;
        for (const auto& test : kFrontCases) {
            const auto& p = fastv2_profile::kProfiles[test.level];
            fastv2::Result summary = {}; summary.version = fastv2::kResultVersion;
            std::vector<orb_golden::Point> chosen;
            if (test.budget_delta) summary.status = fastv2::kInvalidArgument;
            else {
                orb_golden::Image image(p.width, p.height); image.pixels = front_case_pixels(test);
                orb_golden::Config config;
                config.threshold = test.high; config.low_threshold = test.low;
                config.dual_threshold = test.dual != 0;
                const auto candidates = orb_golden::tiled_candidates(image, config);
                orb_golden::Layer layer;
                chosen = orb_golden::select_grid(candidates, p.width - 32, p.height - 32, p.budget, layer, &config);
                summary.candidate_count = int(candidates.size());
                summary.selected_count = int(chosen.size());
                summary.cell_side = layer.cell_side; summary.cell_cols = layer.cell_cols;
                summary.cell_rows = layer.cell_rows; summary.empty_cells = layer.empty_cells;
                summary.fallback_cells = layer.fallback_cells;
                summary.tile_cols = (p.width - 32) / 35; summary.tile_rows = (p.height - 32) / 35;
                summary.tile_width = (p.width - 32 + summary.tile_cols - 1) / summary.tile_cols;
                summary.tile_height = (p.height - 32 + summary.tile_rows - 1) / summary.tile_rows;
                if (summary.selected_count > test.capacity) {
                    summary.status = fastv2::kSelectedCapacityExceeded; chosen.clear();
                }
            }
            summaries.push_back(summary); points.push_back(chosen);
        }
        if (summaries[4].selected_count != 87 || summaries[4].empty_cells != 0 ||
            summaries[3].fallback_cells != 54 || summaries[6].candidate_count <= 8192)
            throw std::runtime_error("required sort/fallback/dense branches are not covered");
        if (summaries[5].status != fastv2::kSelectedCapacityExceeded ||
            summaries[9].status != fastv2::kSelectedCapacityExceeded ||
            summaries[10].status != fastv2::kOk ||
            summaries[9].selected_count != 54 || summaries[10].selected_count != 54 ||
            !points[9].empty() || points[10].size() != 54)
            throw std::runtime_error("required capacity boundary branches are not covered");
        out << "// Generated from independent v1.0 CPU reference; do not edit.\n"
            << "static const fastv2::Result kFrontExpectedSummary[" << kFrontCaseCount << "] = {\n";
        for (const auto& summary : summaries) { write_summary(out, summary); out << ",\n"; }
        out << "};\nstatic const fastv2::Point kFrontExpectedPoints[" << kFrontCaseCount << "][217] = {\n";
        for (const auto& chosen : points) {
            out << '{';
            if (chosen.empty()) out << "{0,0,0,0}";
            for (const auto& point : chosen)
                out << '{' << point.x << ',' << point.y << ',' << point.score << ',' << point.tile << "},";
            out << "},\n";
        }
        out << "};\n";
        if (!out) throw std::runtime_error("reference output write failed");
        std::cout << "NEXT_FRONT_VECTORS_PASS cases=" << kFrontCaseCount
                  << " dense_candidates=" << summaries[6].candidate_count << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "NEXT_FRONT_VECTORS_FAIL " << error.what() << '\n'; return 1;
    }
}
