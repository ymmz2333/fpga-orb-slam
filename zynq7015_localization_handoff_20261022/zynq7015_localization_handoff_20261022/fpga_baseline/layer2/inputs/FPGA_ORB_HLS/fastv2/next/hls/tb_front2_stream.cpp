#include "fastv2.hpp"
#include "front2_cases.hpp"
#include "front2_vectors.inc"
#include <cstring>
#include <iostream>

/**
 * @brief Check an actual DUT transaction against independent frozen CPU outputs.
 * @param index Deterministic test case index.
 * @return True only when status, all 64 summary bytes and all output bytes match.
 * @note Buffers cover declared AXI depths even for small layers. Unwritten point
 *       slots retain a poison value, checking empty/error paths and output bounds.
 */
static bool run_case(int index) {
    const FrontCase& test = kFront2Cases[index];
    const auto& p = fastv2_profile::kProfiles[test.level];
    const auto pixels = front_case_pixels(test);
    std::vector<uint64_t> image(86400, UINT64_C(0xc35a0f1e55229988));
    std::memcpy(image.data(), pixels.data(), pixels.size());
    std::vector<uint64_t> actual(2000), expected(2000);
    std::memset(actual.data(), 0xa5, actual.size() * sizeof(actual[0]));
    std::memset(expected.data(), 0xa5, expected.size() * sizeof(expected[0]));
    const fastv2::Result& reference = kFrontExpectedSummary[index];
    if (reference.status == fastv2::kOk)
        std::memcpy(expected.data(), kFrontExpectedPoints[index], size_t(reference.selected_count) * sizeof(fastv2::Point));
    fastv2::Result summary;
    std::memset(&summary, 0xa5, sizeof(summary));
    uint64_t summary_words[8] = {};
    const int status = fastv2_front2_hls(image.data(), actual.data(), summary_words,
        p.width, p.height, p.budget + test.budget_delta, test.high, test.low, test.dual, test.capacity);
    std::memcpy(&summary, summary_words, sizeof(summary));
    const bool summary_matches = std::memcmp(&summary, &reference, sizeof(summary)) == 0;
    const bool points_match = std::memcmp(actual.data(), expected.data(), actual.size() * sizeof(actual[0])) == 0;
    if (status != reference.status || !summary_matches || !points_match) {
        std::cerr << "NEXT_FRONT2_RTL_CASE_FAIL case=" << index << " level=" << test.level
                  << " status=" << status << '/' << reference.status
                  << " DDR_status=" << summary.status << '/' << reference.status
                  << " summary_bytes_match=" << summary_matches << " point_bytes_match=" << points_match
                  << " candidates=" << summary.candidate_count << '/' << reference.candidate_count
                  << " selected=" << summary.selected_count << '/' << reference.selected_count << '\n';
        return false;
    }
    std::cout << "NEXT_FRONT2_RTL_CASE_PASS case=" << index << " level=" << test.level
              << " candidates=" << summary.candidate_count << " status=" << status << '\n';
    return true;
}

/**
 * @brief Exercise finite-FIFO processing, changing geometry and transaction restart.
 * @return Zero only after every exact reference comparison completes.
 * @note Native RTL FIFO behavior is checked by co-simulation, not the host run;
 *       completion alone does not prove a FIFO-full stall was exercised.
 */
int main() {
    bool passed = true;
    // Keep checking after a mismatch so dense/restart cases are not left unreported.
    for (int index = 0; index < kFront2CaseCount; ++index) if (!run_case(index)) passed = false;
    if (!passed) return 1;
    std::cout << "NEXT_FRONT2_STREAM_PASS cases=" << kFront2CaseCount << '\n';
    return 0;
}
