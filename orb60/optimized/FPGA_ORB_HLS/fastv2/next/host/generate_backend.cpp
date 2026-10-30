#include "golden.hpp"
#include "constants.hpp"
#include <fstream>
#include <iostream>
#include <iomanip>
#include <stdexcept>

/** @brief Compute FNV-1a over independent exact Gaussian bytes. */
static uint64_t checksum(const orb_golden::Image& image) {
    uint64_t result = UINT64_C(14695981039346656037);
    for (uint8_t byte : image.pixels) result = (result ^ byte) * UINT64_C(1099511628211);
    return result;
}

/**
 * @brief Generate exact frozen A32 offset ROM and independent full-ORB references.
 * @param argc Must be six including program name.
 * @param argv Input PGM, offset header, full-reference include, constants header, blur binary.
 * @return Zero on successful generation; tables preserve ties-to-even rounding.
 */
int main(int argc, char** argv) {
    if (argc != 6) return 2;
    std::ifstream constants(argv[4], std::ios::binary);
    if (!constants) return 2;
    std::string notices, line;
    bool found_boundary = false;
    while (std::getline(constants, line)) {
        if (line.find("#pragma once") != std::string::npos) {
            found_boundary = true;
            break;
        }
        notices += line + '\n';
    }
    if (!found_boundary) return 2;
    std::ofstream tables(argv[2], std::ios::binary), reference(argv[3], std::ios::binary);
    if (!tables || !reference) return 2;
    tables << notices << "/* Generated from v1.0 constants.hpp; do not edit. */\n"
              "#ifndef NEXT_BACKEND_TABLES_H\n#define NEXT_BACKEND_TABLES_H\n#include <stdint.h>\n"
              "static const int8_t kNextUmax[16] = {";
    for (int index = 0; index < 16; ++index) tables << orb_golden::umax[index] << ',';
    tables << "};\nstatic const int64_t kNextCordicDegrees[32] = {";
    for (int index = 0; index < 32; ++index) tables << "INT64_C(" << orb_golden::cordic_degrees_q24[index] << "),";
    tables << "};\nstatic const int8_t kNextBriefOffsets[32][512][2] = {\n";
    for (int bin = 0; bin < 32; ++bin) {
        tables << "{\n";
        const int64_t cosine = orb_golden::trig32[bin][0];
        const int64_t sine = orb_golden::trig32[bin][1];
        for (int sample = 0; sample < 512; ++sample) {
            const int x = orb_golden::pattern[sample * 2];
            const int y = orb_golden::pattern[sample * 2 + 1];
            const int64_t dx = orb_golden::round_even(x * cosine - y * sine, INT64_C(1) << 30);
            const int64_t dy = orb_golden::round_even(x * sine + y * cosine, INT64_C(1) << 30);
            if (dx < -127 || dx > 127 || dy < -127 || dy > 127) return 2;
            tables << '{' << dx << ',' << dy << "},";
            if ((sample & 15) == 15) tables << '\n';
        }
        tables << "},\n";
    }
    tables << "};\n#endif\n";
    orb_golden::Config config;
    const auto input = orb_golden::read_pgm(argv[1]);
    const auto result = orb_golden::extract(input, config);
    std::ofstream blur_binary(argv[5], std::ios::binary);
    if (!blur_binary) return 2;
    for (const auto& layer : result.layers)
        blur_binary.write(reinterpret_cast<const char*>(layer.blurred.pixels.data()),
                          std::streamsize(layer.blurred.pixels.size()));
    blur_binary.close();
    if (!blur_binary) return 2;
    reference << "/* Generated from independent v1.0 golden.cpp; do not edit. */\n"
                 "static const uint64_t kExpectedBlurDigests[8] = {\n";
    for (const auto& layer : result.layers) {
        reference << "UINT64_C(0x" << std::hex << std::setw(16) << std::setfill('0')
                  << checksum(layer.blurred) << "),\n";
    }
    reference << std::dec << "};\nstatic const NextFeature kExpectedFeatures[8][256] = {\n";
    for (const auto& layer : result.layers) {
        if (layer.features.size() > 256) return 2;
        reference << "{\n";
        for (const auto& feature : layer.features) {
            reference << '{' << feature.point.x << ',' << feature.point.y << ',' << feature.point.score
                      << ',' << feature.level << ',' << feature.bin << ',' << feature.m10 << ','
                      << feature.m01 << ',' << feature.angle_q16 << ",{";
            for (int word = 0; word < 8; ++word) {
                uint32_t packed = 0;
                for (int lane = 0; lane < 4; ++lane) packed |= uint32_t(feature.descriptor[word * 4 + lane]) << (lane * 8);
                reference << "UINT32_C(0x" << std::hex << packed << ")," << std::dec;
            }
            reference << "}},\n";
        }
        reference << "},\n";
    }
    reference << "};\n";
    tables.close(); reference.close();
    if (!tables || !reference) return 2;
    std::cout << "NEXT_BACKEND_ROM_PASS bins=32 samples_per_bin=512 levels=8\n";
    return 0;
}
