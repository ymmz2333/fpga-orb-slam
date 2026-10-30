#include "fastv2.hpp"
#include "next_gaussian.hpp"
#include "next_backend.h"
#include "golden.hpp"
#include <cstring>
#include <iostream>
#include <stdexcept>

/** @brief Raise deterministic Release-build failures with stage context. */
static void require(bool valid, const char* message) {
    if (!valid) throw std::runtime_error(message);
}

/** @brief Pack active pixels and zero the final partial AXI word. */
static std::vector<uint64_t> pack(const orb_golden::Image& image) {
    std::vector<uint64_t> words((image.pixels.size() + 7) / 8);
    std::memcpy(words.data(), image.pixels.data(), image.pixels.size());
    return words;
}

/**
 * @brief Verify all eight full layers: front points, Gaussian and every feature field.
 * @param image Real or deterministic grayscale source.
 * @return Number of exactly verified features across all pyramid levels.
 */
static int verify_complete(const orb_golden::Image& image) {
    orb_golden::Config config;
    const auto expected = orb_golden::extract(image, config);
    int total = 0;
    std::vector<uint64_t> previous_level;
    for (int level = 0; level < 8; ++level) {
        const auto& layer = expected.layers[level];
        auto input = pack(layer.image);
        if (level != 0) {
            input.assign(input.size(), UINT64_C(0xa5a5a5a5a5a5a5a5));
            require(fastv2_resize_hls(previous_level.data(), input.data(), level - 1) == 0,
                    "Actual pyramid resize status");
            require(std::memcmp(input.data(), layer.image.pixels.data(), layer.image.pixels.size()) == 0,
                    "Actual pyramid resize pixel mismatch");
        }
        previous_level = input;
        std::vector<uint64_t> blurred(input.size(), UINT64_C(0xa5a5a5a5a5a5a5a5));
        require(fastv2_gaussian_hls(input.data(), blurred.data(), level) == 0, "Gaussian status");
        require(std::memcmp(blurred.data(), layer.blurred.pixels.data(), layer.image.pixels.size()) == 0,
                "Gaussian pixel mismatch");
        fastv2::Point points[256];
        fastv2::Result summary;
        require(fastv2_front_hls(input.data(), points, &summary, layer.image.width, layer.image.height,
            layer.budget, 20, 7, 1, 256) == 0, "Front status");
        require(summary.selected_count == int(layer.features.size()), "Selected count mismatch");
        NextPoint selected[256];
        for (int index = 0; index < summary.selected_count; ++index) {
            selected[index] = {points[index].x, points[index].y, points[index].score, points[index].tile};
        }
        NextFeature actual[256];
        require(next_describe(reinterpret_cast<const uint8_t*>(input.data()), reinterpret_cast<const uint8_t*>(blurred.data()),
            layer.image.width, layer.image.height, selected, summary.selected_count, level, actual, 256) == 0,
            "PS descriptor status");
        for (int index = 0; index < summary.selected_count; ++index) {
            const auto& reference = layer.features[index];
            const auto& feature = actual[index];
            require(feature.x == reference.point.x && feature.y == reference.point.y &&
                feature.score == reference.point.score && feature.level == reference.level &&
                feature.bin == reference.bin && feature.m10 == reference.m10 &&
                feature.m01 == reference.m01 && feature.angle_q16 == reference.angle_q16 &&
                std::memcmp(feature.descriptor, reference.descriptor.data(), 32) == 0,
                "Feature fields/descriptor mismatch");
        }
        total += summary.selected_count;
    }
    return total;
}

/**
 * @brief Check full fixed-profile ORB layer semantics and PS argument/angle boundaries.
 * @param argc Must include one real PGM path.
 * @param argv Program name and PGM path.
 * @return Zero only when all actual HLS models and PS C backend match golden.cpp.
 * @note This verifies per-layer feature records, not the legacy cross-level packet serializer.
 */
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    try {
        const int real_features = verify_complete(orb_golden::read_pgm(argv[1]));
        orb_golden::Image synthetic(960,720);
        for (int y = 0; y < 720; ++y) for (int x = 0; x < 960; ++x) {
            synthetic.at(x,y) = uint8_t((x * 37 + y * 53 + x * y * 3) & 255);
        }
        /* Gaussian extremes/odd geometry independently of candidate-capacity limits. */
        const int widths[8] = {960,800,667,556,463,386,322,268};
        const int heights[8] = {720,600,500,417,347,289,241,201};
        for (int level = 0; level < 8; ++level) {
            auto layer = orb_golden::resize_linear(synthetic, widths[level], heights[level]);
            auto reference = orb_golden::gaussian7(layer);
            auto words = pack(layer);
            std::vector<uint64_t> result(words.size());
            require(fastv2_gaussian_hls(words.data(), result.data(), level) == 0 &&
                    std::memcmp(result.data(), reference.pixels.data(), layer.pixels.size()) == 0,
                    "Synthetic Gaussian mismatch");
        }
        for (int32_t x : {-1000000, -1, 0, 1, 1000000}) {
            for (int32_t y : {-1000000, -1, 0, 1, 1000000}) {
                require(next_angle_q16(x,y) == orb_golden::angle_q16(x,y), "CORDIC axis/quadrant mismatch");
            }
        }
        require(next_describe(nullptr,nullptr,960,720,nullptr,0,0,nullptr,0) == -1,
                "Null images not rejected");
        require(fastv2_gaussian_hls(nullptr,nullptr,-1) == fastv2::kInvalidArgument &&
                fastv2_gaussian_hls(nullptr,nullptr,8) == fastv2::kInvalidArgument,
                "Invalid Gaussian level not rejected");
        std::cout << "NEXT_COMPLETE_PASS levels=8 features=" << real_features << " gaussian_synthetic_levels=8\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "NEXT_COMPLETE_FAIL: " << error.what() << '\n';
        return 1;
    }
}
