#include "next_gaussian.hpp"
#include "fastv2.hpp"
#include "image_test_reference.hpp"
#include <cstdio>

/**
 * @brief Publish flushed host-only progress to distinguish startup from kernel stalls.
 * @param stage Completed/next test stage, never a numerical acceptance result.
 * @param index Transaction index, or -1 at entry before the first transaction.
 * @note Vendor C/RTL simulation and synthesized logic are not changed.
 */
static void host_progress(const char* stage, int index) {
#if !defined(__SYNTHESIS__) && !defined(FASTV2_HLS_CSIM)
    std::fprintf(stderr, "NEXT_GAUSSIAN_HOST_PROGRESS case=%d stage=%s\n", index, stage);
    std::fflush(stderr);
#else
    (void)stage;
    (void)index;
#endif
}

/**
 * @brief Check one Gaussian transaction against direct CPU-validated convolution.
 * @param index Index in the frozen fourteen-transaction sequence.
 * @return True only when status, pixels, padding and untouched output words match.
 * @note Uses the full 86400-word AXI depth, with poisoned input padding/tail.
 */
static bool run_case(int index) {
    using namespace next_image_test;
    const ImageCase test = kGaussianCases[index];
    host_progress("reference", index);
    const bool valid = test.level >= 0 && test.level < 8;
    const std::vector<uint8_t> input = valid ? pixels(test) : std::vector<uint8_t>();
    const std::vector<uint8_t> reference = valid ? gaussian(input, test.level) : std::vector<uint8_t>();
    const std::vector<uint64_t> source = pack(input, false);
    const std::vector<uint64_t> expected = pack(reference, true);
    std::vector<uint64_t> actual(kPortWords, kPoison);
    host_progress("kernel", index);
    const int status = fastv2_gaussian_hls(source.data(), actual.data(), test.level);
    host_progress("compare", index);
    return check("NEXT_GAUSSIAN_RTL", index, test, status,
                 valid ? fastv2::kOk : fastv2::kInvalidArgument, actual, expected);
}

/**
 * @brief Exercise eight geometries, reflected borders and repeated FIFO startup/drain.
 * @return Zero only when all fourteen transactions pass; continue after mismatches.
 * @note Includes small-to-large geometry changes, zero/255/random data, two
 *       invalid levels and normal restart; it does not inject reset or AXI stalls.
 */
int main() {
    host_progress("main", -1);
    bool passed = true;
    for (int index = 0; index < next_image_test::kGaussianCaseCount; ++index)
        if (!run_case(index)) passed = false;
    if (!passed) return 1;
    std::cout << "NEXT_GAUSSIAN_STREAM_PASS cases=" << next_image_test::kGaussianCaseCount << '\n';
    return 0;
}
