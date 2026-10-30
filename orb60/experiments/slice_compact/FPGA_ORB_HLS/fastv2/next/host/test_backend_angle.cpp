#include "next_backend.h"
#include "golden.hpp"
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#if defined(NEXT_TEST_PL_DESCRIPTOR)
#include "descriptor.hpp"
#define next_angle_q16 orb60_descriptor_angle_q16
#endif

/**
 * @brief Compare the PS CORDIC result against untouched v1.0 CPU arithmetic.
 * @param x Signed horizontal moment, including full int32 boundaries.
 * @param y Signed vertical moment, including axes and all four quadrants.
 * @param cases Receives the number of exactly compared input pairs.
 * @throws std::runtime_error on the first mismatch with input/result diagnostics.
 */
static void check_angle(int32_t x, int32_t y, uint32_t& cases) {
    const uint32_t actual = next_angle_q16(x, y);
    const uint32_t expected = orb_golden::angle_q16(x, y);
    if (actual != expected) {
        std::cerr << "moments=" << x << ',' << y << " actual=" << actual
                  << " expected=" << expected << '\n';
        throw std::runtime_error("Exact CORDIC mismatch");
    }
    ++cases;
}

/**
 * @brief Advance a fixed-seed unsigned LCG and map it portably to signed int32.
 * @param state In/out deterministic generator state, wrapping in uint32 arithmetic.
 * @return Full-range signed moment without out-of-range unsigned-to-signed casts.
 */
static int32_t next_moment(uint32_t& state) {
    state = state * UINT32_C(1664525) + UINT32_C(1013904223);
    return static_cast<int32_t>(static_cast<int64_t>(state) - INT64_C(2147483648));
}

/**
 * @brief Run bounded exact regression for the R11 division-free CORDIC shift.
 * @return Zero only when boundary, small-grid and 100000 random pairs match v1.0.
 * @note Software elapsed time does not predict Cortex-A9 or FPGA performance.
 */
int main() {
    try {
        uint32_t cases = 0, seed = UINT32_C(0x523131);
        const int32_t boundaries[] = {
            std::numeric_limits<int32_t>::min(), -2147483647, -1073741824,
            -1000000, -65537, -65536, -32769, -257, -256, -255, -2, -1,
            0, 1, 2, 255, 256, 257, 32769, 65536, 65537, 1000000,
            1073741824, 2147483646, std::numeric_limits<int32_t>::max()
        };
        for (int32_t x : boundaries) for (int32_t y : boundaries) check_angle(x, y, cases);
        for (int32_t x = -64; x <= 64; ++x)
            for (int32_t y = -64; y <= 64; ++y) check_angle(x, y, cases);
        for (int index = 0; index < 100000; ++index) {
            const int32_t x = next_moment(seed), y = next_moment(seed);
            check_angle(x, y, cases);
        }
        std::cout << "NEXT_BACKEND_ANGLE_PASS cases=" << cases << " random=100000\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "NEXT_BACKEND_ANGLE_FAIL: " << error.what() << '\n';
        return 1;
    }
}
