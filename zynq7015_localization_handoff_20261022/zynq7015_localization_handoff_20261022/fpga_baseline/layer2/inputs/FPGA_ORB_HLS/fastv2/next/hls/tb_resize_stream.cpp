#include "fastv2.hpp"
#include "image_test_reference.hpp"

/**
 * @brief Check one resize transaction against the CPU-validated independent model.
 * @param index Index in the frozen thirteen-transaction sequence.
 * @return True only when status, pixels, padding and untouched words match.
 * @note Buffers always match the 86400-word HLS AXI depth, even for invalid levels.
 */
static bool run_case(int index) {
    using namespace next_image_test;
    const ImageCase test = kResizeCases[index];
    const bool valid = test.level >= 0 && test.level < 7;
    const std::vector<uint8_t> input = valid ? pixels(test) : std::vector<uint8_t>();
    const std::vector<uint8_t> reference = valid ? resize(input, test.level) : std::vector<uint8_t>();
    const std::vector<uint64_t> source = pack(input, false);
    const std::vector<uint64_t> expected = pack(reference, true);
    std::vector<uint64_t> actual(kPortWords, kPoison);
    const int status = fastv2_resize_hls(source.data(), actual.data(), test.level);
    return check("NEXT_RESIZE_RTL", index, test, status,
                 valid ? fastv2::kOk : fastv2::kInvalidArgument, actual, expected);
}

/**
 * @brief Exercise all seven transitions, changing geometry and failure recovery.
 * @return Zero only when all thirteen transactions pass; continue after mismatches.
 * @note Includes odd-width carry, nonzero input padding, zero/255/random data,
 *       negative/upper invalid levels and a normal restart after both errors.
 */
int main() {
    bool passed = true;
    for (int index = 0; index < next_image_test::kResizeCaseCount; ++index)
        if (!run_case(index)) passed = false;
    if (!passed) return 1;
    std::cout << "NEXT_RESIZE_STREAM_PASS cases=" << next_image_test::kResizeCaseCount << '\n';
    return 0;
}
