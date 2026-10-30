#include "image_test_reference.hpp"
#include "golden.hpp"
#include <stdexcept>

/**
 * @brief Validate an HLS-compatible image oracle against independent v1.0 CPU code.
 * @param blur True for Gaussian, false for adjacent resize.
 * @param index Transaction index in the corresponding fixed table.
 * @return One for a checked valid case, zero for an invalid-level interface case.
 * @throws std::runtime_error On any reference pixel disagreement.
 * @note Never calls either DUT. This prevents a locally incorrect oracle from
 *       accepting identical errors in host and RTL testbench output checks.
 */
static int check_oracle(bool blur, int index) {
    using namespace next_image_test;
    const ImageCase test = blur ? kGaussianCases[index] : kResizeCases[index];
    if (test.level < 0 || test.level >= (blur ? 8 : 7)) return 0;
    orb_golden::Image image(kWidths[test.level], kHeights[test.level]);
    image.pixels = pixels(test);
    const orb_golden::Image expected = blur ? orb_golden::gaussian7(image) :
        orb_golden::resize_linear(image, kWidths[test.level + 1], kHeights[test.level + 1]);
    const std::vector<uint8_t> actual = blur ? gaussian(image.pixels, test.level) : resize(image.pixels, test.level);
    if (actual.size() != expected.pixels.size()) throw std::runtime_error("image oracle size mismatch");
    for (size_t pixel = 0; pixel < actual.size(); ++pixel) if (actual[pixel] != expected.pixels[pixel]) {
        std::cerr << "NEXT_IMAGE_ORACLE_FAIL blur=" << blur << " case=" << index
                  << " pixel=" << pixel << " actual=" << unsigned(actual[pixel])
                  << " expected=" << unsigned(expected.pixels[pixel]) << '\n';
        throw std::runtime_error("HLS image oracle differs from independent CPU");
    }
    return 1;
}

/**
 * @brief Require every valid RTL image-test oracle to match v1.0 before launch.
 * @return Zero only when all twenty-three valid case oracles match exactly.
 */
int main() {
    try {
        int checked = 0;
        for (int index = 0; index < next_image_test::kResizeCaseCount; ++index) checked += check_oracle(false, index);
        for (int index = 0; index < next_image_test::kGaussianCaseCount; ++index) checked += check_oracle(true, index);
        std::cout << "NEXT_IMAGE_ORACLE_PASS cases=" << checked << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "NEXT_IMAGE_ORACLE_FAIL " << error.what() << '\n';
        return 1;
    }
}
