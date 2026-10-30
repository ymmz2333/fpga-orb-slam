#include "fastv2.hpp"

#include <cstdint>
#include <iostream>
#include <vector>

namespace {

/** Reference coordinate pair for one bilinear interpolation axis. */
struct Axis {
    int source_a;
    int source_b;
    int weight;
};

/**
 * @brief Divide with round-to-nearest and ties-to-even semantics.
 * @param value Nonnegative dividend.
 * @param divisor Positive divisor.
 * @return Rounded integer quotient.
 */
int64_t round_even(int64_t value, int64_t divisor) {
    int64_t quotient = value / divisor;
    const int64_t remainder = value % divisor;
    if (remainder > divisor - remainder ||
        (remainder == divisor - remainder && (quotient & 1) != 0)) {
        ++quotient;
    }
    return quotient;
}

/**
 * @brief Compute one independent v1.0 half-pixel resize coordinate.
 * @param target Destination coordinate.
 * @param source_size Source-axis extent.
 * @param destination_size Destination-axis extent.
 * @return Replicated-edge indices and Q0.11 interpolation weight.
 */
Axis reference_axis(int target, int source_size, int destination_size) {
    const int64_t numerator =
        int64_t(2 * target + 1) * source_size - destination_size;
    const int64_t denominator = int64_t(2) * destination_size;
    int64_t source_a = numerator / denominator;
    int64_t remainder = numerator % denominator;
    if (remainder < 0) {
        --source_a;
        remainder += denominator;
    }
    if (source_a < 0) return {0, 0, 0};
    if (source_a >= source_size - 1) {
        return {source_size - 1, source_size - 1, 0};
    }
    return {int(source_a), int(source_a + 1),
            int(round_even(remainder * 2048, denominator))};
}

/**
 * @brief Pack bytes into the fastv2 little-endian AXI representation.
 * @param pixels Row-major grayscale bytes.
 * @return Packed 64-bit storage.
 */
std::vector<uint64_t> pack_pixels(const std::vector<uint8_t>& pixels) {
    std::vector<uint64_t> packed((pixels.size() + 7u) / 8u, 0);
    for (size_t index = 0; index < pixels.size(); ++index) {
        packed[index >> 3] |= uint64_t(pixels[index]) << ((index & 7u) * 8u);
    }
    return packed;
}

/**
 * @brief Read one valid byte from packed output storage.
 * @param packed Packed storage.
 * @param index Linear byte index.
 * @return Selected grayscale byte.
 */
uint8_t unpack_pixel(const std::vector<uint64_t>& packed, size_t index) {
    return uint8_t(packed[index >> 3] >> ((index & 7u) * 8u));
}

/**
 * @brief Compute one exact reference output pixel.
 * @param source Source image bytes.
 * @param source_width Source width.
 * @param x_axis Horizontal interpolation coordinate.
 * @param y_axis Vertical interpolation coordinate.
 * @return Exact v1.0 output byte.
 */
uint8_t reference_pixel(const std::vector<uint8_t>& source, int source_width,
                        const Axis& x_axis, const Axis& y_axis) {
    const uint8_t row_a0 = source[size_t(y_axis.source_a * source_width + x_axis.source_a)];
    const uint8_t row_a1 = source[size_t(y_axis.source_a * source_width + x_axis.source_b)];
    const uint8_t row_b0 = source[size_t(y_axis.source_b * source_width + x_axis.source_a)];
    const uint8_t row_b1 = source[size_t(y_axis.source_b * source_width + x_axis.source_b)];
    const int64_t row0 = int64_t(row_a0) * (2048 - x_axis.weight) +
                         int64_t(row_a1) * x_axis.weight;
    const int64_t row1 = int64_t(row_b0) * (2048 - x_axis.weight) +
                         int64_t(row_b1) * x_axis.weight;
    const int64_t value = ((row0 >> 4) * (2048 - y_axis.weight) >> 16) +
                          ((row1 >> 4) * y_axis.weight >> 16);
    return uint8_t((value + 2) >> 2);
}

/**
 * @brief Verify one adjacent fixed pyramid transition pixel by pixel.
 * @param level Source level in 0..6.
 * @param source_width Source width.
 * @param source_height Source height.
 * @param destination_width Destination width.
 * @param destination_height Destination height.
 * @return True when every valid output byte matches the independent model.
 */
bool run_transition(int level, int source_width, int source_height,
                    int destination_width, int destination_height) {
    std::vector<uint8_t> source(size_t(source_width) * size_t(source_height));
    for (int y = 0; y < source_height; ++y) {
        for (int x = 0; x < source_width; ++x) {
            source[size_t(y * source_width + x)] = uint8_t(
                (x * 37 + y * 53 + x * y * 3 + level * 19 + 17) & 255);
        }
    }
    const std::vector<uint64_t> packed_source = pack_pixels(source);
    std::vector<uint64_t> actual(
        (size_t(destination_width) * size_t(destination_height) + 7u) / 8u, 0);
    const int status = fastv2_resize_hls(
        packed_source.data(), actual.data(), level);
    if (status != fastv2::kOk) {
        std::cerr << "FASTV2_RESIZE_FAIL level=" << level
                  << " status=" << status << '\n';
        return false;
    }
    for (int y = 0; y < destination_height; ++y) {
        const Axis y_axis = reference_axis(y, source_height, destination_height);
        for (int x = 0; x < destination_width; ++x) {
            const Axis x_axis = reference_axis(x, source_width, destination_width);
            const uint8_t expected = reference_pixel(
                source, source_width, x_axis, y_axis);
            const size_t index = size_t(y * destination_width + x);
            const uint8_t observed = unpack_pixel(actual, index);
            if (observed != expected) {
                std::cerr << "FASTV2_RESIZE_FAIL level=" << level
                          << " pixel=" << x << ',' << y
                          << " actual=" << int(observed)
                          << " expected=" << int(expected) << '\n';
                return false;
            }
        }
    }
    std::cout << "FASTV2_RESIZE_CASE_PASS level=" << level
              << " size=" << source_width << 'x' << source_height
              << "->" << destination_width << 'x' << destination_height << '\n';
    return true;
}

} // namespace

/**
 * @brief Verify all seven fixed fastv2 resize transitions.
 * @return Zero when every transition is pixel-exact.
 */
int main() {
    const int widths[8] = {960, 800, 667, 556, 463, 386, 322, 268};
    const int heights[8] = {720, 600, 500, 417, 347, 289, 241, 201};
#ifdef FASTV2_HLS_CSIM
    const int first_level = 6;
#else
    const int first_level = 0;
#endif
    for (int level = first_level; level < 7; ++level) {
        if (!run_transition(level, widths[level], heights[level],
                            widths[level + 1], heights[level + 1])) {
            return 1;
        }
    }
#ifndef FASTV2_HLS_CSIM
    if (fastv2_resize_hls(nullptr, nullptr, -1) != fastv2::kInvalidArgument ||
        fastv2_resize_hls(nullptr, nullptr, 7) != fastv2::kInvalidArgument) {
        std::cerr << "FASTV2_RESIZE_FAIL invalid-level contract\n";
        return 1;
    }
#endif
    std::cout << "FASTV2_RESIZE_PASS\n";
    return 0;
}
