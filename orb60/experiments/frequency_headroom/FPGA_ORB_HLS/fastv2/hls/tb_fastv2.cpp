#include "fastv2.hpp"
#include "golden.hpp"

#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

namespace {

/**
 * @brief Build a deterministic image containing gradients and tile-edge detail.
 * @param width Image width.
 * @param height Image height.
 * @return Generated grayscale image.
 */
orb_golden::Image make_test_image(int width, int height) {
    orb_golden::Image image(width, height);
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            const uint32_t checker = ((x / 5 + y / 7) & 1) ? 91u : 13u;
            image.at(x, y) = uint8_t(
                (x * 17 + y * 29 + checker + (x * y) % 67) & 255);
        }
    }
    return image;
}

/**
 * @brief Pack an 8-bit image into little-endian 64-bit words.
 * @param image Source image.
 * @return Packed storage accepted by fastv2_front_hls.
 */
std::vector<uint64_t> pack_image(const orb_golden::Image& image) {
    std::vector<uint64_t> packed((image.pixels.size() + 7u) / 8u, 0);
    for (std::size_t index = 0; index < image.pixels.size(); ++index) {
        packed[index >> 3] |= uint64_t(image.pixels[index]) << ((index & 7u) * 8u);
    }
    return packed;
}

/**
 * @brief Compare fastv2 and reference point records.
 * @param actual fastv2 output.
 * @param expected v1.0 reference output.
 * @return True when all externally visible fields match.
 */
#ifndef FASTV2_HLS_CSIM
bool same_point(const fastv2::Point& actual, const orb_golden::Point& expected) {
    return actual.x == expected.x && actual.y == expected.y &&
           actual.score == expected.score && actual.tile == expected.tile;
}
#endif

/**
 * @brief Compute the stable v1.0-style digest of selected point records.
 * @param points Selected point storage.
 * @param count Number of valid records.
 * @return 64-bit FNV-1a digest in field and little-endian byte order.
 */
uint64_t digest_points(const std::vector<fastv2::Point>& points, int count) {
    uint64_t digest = UINT64_C(14695981039346656037);
    for (int index = 0; index < count; ++index) {
        const uint32_t fields[4] = {
            uint32_t(points[size_t(index)].x), uint32_t(points[size_t(index)].y),
            uint32_t(points[size_t(index)].score), uint32_t(points[size_t(index)].tile)};
        for (int field = 0; field < 4; ++field) {
            for (int byte = 0; byte < 4; ++byte) {
                digest ^= uint8_t(fields[field] >> (byte * 8));
                digest *= UINT64_C(1099511628211);
            }
        }
    }
    return digest;
}

/**
 * @brief Run one exact front-end comparison.
 * @param image Input image.
 * @param budget Grid selection budget.
 * @param dual_threshold Whether low-threshold fallback is enabled.
 * @return True when candidates, selected points, and metadata match v1.0.
 */
#ifndef FASTV2_HLS_CSIM
bool run_case(const orb_golden::Image& image, int budget, bool dual_threshold) {
    orb_golden::Config config;
    config.threshold = 20;
    config.low_threshold = 7;
    config.dual_threshold = dual_threshold;
    config.grid_top_k = 1;

    const std::vector<orb_golden::Point> candidates =
        orb_golden::tiled_candidates(image, config);
    orb_golden::Layer layer;
    const std::vector<orb_golden::Point> expected = orb_golden::select_grid(
        candidates, image.width - 32, image.height - 32, budget, layer, &config);
    const std::vector<uint64_t> packed = pack_image(image);
    std::vector<fastv2::Point> actual(fastv2::kMaxSelected);
    fastv2::Result result = {};
    const int status = fastv2_front_hls(
        packed.data(), actual.data(), &result, image.width, image.height,
        budget, config.threshold, config.low_threshold,
        dual_threshold ? 1 : 0, int(actual.size()));
    if (status != fastv2::kOk || result.status != fastv2::kOk) {
        std::cerr << "FASTV2_FAIL status=" << status
                  << " result_status=" << result.status << '\n';
        return false;
    }
    if (result.candidate_count != int(candidates.size()) ||
        result.selected_count != int(expected.size()) ||
        result.cell_side != layer.cell_side ||
        result.cell_cols != layer.cell_cols ||
        result.cell_rows != layer.cell_rows ||
        result.empty_cells != layer.empty_cells ||
        result.fallback_cells != layer.fallback_cells) {
        std::cerr << "FASTV2_FAIL metadata dual=" << dual_threshold
                  << " candidates=" << result.candidate_count << '/' << candidates.size()
                  << " selected=" << result.selected_count << '/' << expected.size()
                  << " cells=" << result.cell_cols << 'x' << result.cell_rows
                  << " expected_cells=" << layer.cell_cols << 'x' << layer.cell_rows
                  << " empty=" << result.empty_cells << '/' << layer.empty_cells
                  << " fallback=" << result.fallback_cells << '/' << layer.fallback_cells
                  << '\n';
        return false;
    }
    for (std::size_t index = 0; index < expected.size(); ++index) {
        if (!same_point(actual[index], expected[index])) {
            std::cerr << "FASTV2_FAIL point=" << index
                      << " actual=" << actual[index].x << ',' << actual[index].y << ','
                      << actual[index].score << ',' << actual[index].tile
                      << " expected=" << expected[index].x << ',' << expected[index].y << ','
                      << expected[index].score << ',' << expected[index].tile << '\n';
            return false;
        }
    }
    std::cout << "FASTV2_CASE_PASS size=" << image.width << 'x' << image.height
              << " budget=" << budget << " dual=" << dual_threshold
              << " candidates=" << result.candidate_count
              << " selected=" << result.selected_count
              << " cell=" << result.cell_side << ',' << result.cell_cols << ','
              << result.cell_rows << " empty=" << result.empty_cells
              << " fallback=" << result.fallback_cells
              << " digest=" << std::hex
              << digest_points(actual, result.selected_count) << std::dec << '\n';
    return true;
}
#else
/**
 * @brief Check one HLS C-simulation case against frozen reference signatures.
 * @param image Deterministic supported pyramid-level source image.
 * @param budget Grid budget for this case.
 * @param dual_threshold Whether low-threshold fallback is enabled.
 * @param expected_candidates Frozen v1.0 candidate count.
 * @param expected_selected Frozen v1.0 selected count.
 * @param expected_digest Frozen selected-point digest.
 * @return True when result fields and selected records match the signature.
 */
bool run_fixed_case(const orb_golden::Image& image, int budget, bool dual_threshold,
                    int expected_candidates, int expected_selected,
                    uint64_t expected_digest) {
    const std::vector<uint64_t> packed = pack_image(image);
    std::vector<fastv2::Point> actual(fastv2::kMaxSelected);
    fastv2::Result result = {};
    const int status = fastv2_front_hls(
        packed.data(), actual.data(), &result, image.width, image.height,
        budget, 20, 7, dual_threshold ? 1 : 0, int(actual.size()));
    const uint64_t digest = digest_points(actual, result.selected_count);
    if (status != fastv2::kOk || result.status != fastv2::kOk ||
        result.candidate_count != expected_candidates ||
        result.selected_count != expected_selected ||
        result.empty_cells != 0 || result.fallback_cells != 0 ||
        digest != expected_digest) {
        std::cerr << "FASTV2_CSIM_FAIL budget=" << budget
                  << " dual=" << dual_threshold
                  << " status=" << status << '/' << result.status
                  << " candidates=" << result.candidate_count << '/' << expected_candidates
                  << " selected=" << result.selected_count << '/' << expected_selected
                  << " digest=" << std::hex << digest << '/' << expected_digest
                  << std::dec << '\n';
        return false;
    }
    std::cout << "FASTV2_CSIM_CASE_PASS budget=" << budget
              << " dual=" << dual_threshold << '\n';
    return true;
}
#endif

} // namespace

/**
 * @brief Verify the fastv2 streaming front end against the independent v1.0 model.
 * @param argc Optional PGM path argument count.
 * @param argv Optional PGM path for a full-resolution regression.
 * @return Zero when every comparison passes.
 */
int main(int argc, char** argv) {
#ifdef FASTV2_HLS_CSIM
    (void)argc;
    (void)argv;
    const orb_golden::Image image = make_test_image(268, 201);
    const int budgets[1] = {60};
    const int selected_counts[1] = {54};
    const uint64_t digests[1] = {UINT64_C(0x2fc38f125e80fe9a)};
    for (int dual = 0; dual <= 1; ++dual) {
        const int candidate_count = dual ? 2934 : 2888;
        for (int index = 0; index < 1; ++index) {
            if (!run_fixed_case(image, budgets[index], dual != 0,
                                candidate_count, selected_counts[index],
                                digests[index])) {
                return 1;
            }
        }
    }
    std::cout << "FASTV2_CSIM_PASS\n";
    return 0;
#else
    if (argc > 2) return 2;
    const orb_golden::Image image = argc == 2
        ? orb_golden::read_pgm(argv[1])
        : make_test_image(268, 201);
    if (argc != 2) {
        for (int dual = 0; dual <= 1; ++dual) {
            if (!run_case(image, 60, dual != 0)) return 1;
        }
    }
    if (argc == 2) {
        const int widths[8] = {960, 800, 667, 556, 463, 386, 322, 268};
        const int heights[8] = {720, 600, 500, 417, 347, 289, 241, 201};
        const int level_budgets[8] = {217, 181, 151, 126, 105, 87, 73, 60};
        orb_golden::Image level_image = image;
        for (int level = 0; level < 8; ++level) {
            if (level != 0) {
                level_image = orb_golden::resize_linear(
                    level_image, widths[level], heights[level]);
            }
            if (!run_case(level_image, level_budgets[level], true)) return 1;
        }
    }
    std::cout << "FASTV2_PASS\n";
    return 0;
#endif
}
