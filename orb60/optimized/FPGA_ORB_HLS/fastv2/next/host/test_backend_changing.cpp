/* GPL-3.0-or-later: independent v1.0 orientation/BRIEF regression. */
#include "next_backend.h"
#include "golden.hpp"
#include <algorithm>
#include <array>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>
#if defined(NEXT_TEST_BACKEND_PROFILE)
#include "next_backend_profile.h"
struct ProfileClock { uint64_t tick, calls; };

/**
 * @brief Supply deterministic seven-tick intervals, including uint64 wraparound.
 * @param context Caller-owned fake clock; no real host/ARM performance is inferred.
 * @return Tick before advancing the unsigned counter; increment read-call coverage.
 */
static uint64_t profile_clock(void* context) {
    auto& state = *static_cast<ProfileClock*>(context);
    const uint64_t tick = state.tick;
    state.tick += 7;
    ++state.calls;
    return tick;
}
static const auto describe_for_test = next_describe_profiled;
#elif defined(NEXT_TEST_PL_DESCRIPTOR)
#include "descriptor_test_adapter.hpp"
static const auto describe_for_test = pl_describe_for_test;
#else
static const auto describe_for_test = next_describe;
#endif

/** @brief Fail in Release builds with the current transaction context. */
static void require(bool valid, const char* message) {
    if (!valid) throw std::runtime_error(message);
}

/**
 * @brief Fill a changing layer without depending on PS offset/angle tables.
 * @param image Reused independent CPU image storage.
 * @param pattern Constant zero/255, horizontal/vertical ramp, checker or noise.
 * @param seed Fixed LCG state, advanced only for the noise pattern.
 */
static void fill_image(orb_golden::Image& image, int pattern, uint32_t& seed) {
    for (int y = 0; y < image.height; ++y) for (int x = 0; x < image.width; ++x) {
        uint8_t value = 0;
        switch (pattern) {
        case 1: value = 255; break;
        case 2: value = uint8_t(x * 3 + y / 7); break;
        case 3: value = uint8_t(y * 5 + x / 11); break;
        case 4: value = ((x / 3 + y / 5) & 1) ? 255 : 0; break;
        case 5:
            seed = seed * UINT32_C(1664525) + UINT32_C(1013904223);
            value = uint8_t(seed >> 24); break;
        default: break;
        }
        image.at(x, y) = value;
    }
}

/**
 * @brief Compare every serialized feature field and all 256 descriptor bits.
 * @param actual Actual C backend record, with no oracle-derived fields.
 * @param expected Independent v1.0 record using runtime rotated pattern sampling.
 */
static void compare_feature(const NextFeature& actual, const orb_golden::Feature& expected) {
    require(actual.x == expected.point.x && actual.y == expected.point.y &&
        actual.score == expected.point.score && actual.level == expected.level &&
        actual.bin == expected.bin && actual.m10 == expected.m10 && actual.m01 == expected.m01 &&
        actual.angle_q16 == expected.angle_q16, "Feature metadata/moment/angle mismatch");
    for (int word = 0; word < 8; ++word) {
        uint32_t bits = 0;
        for (int lane = 0; lane < 4; ++lane)
            bits |= uint32_t(expected.descriptor[word * 4 + lane]) << (lane * 8);
        require(actual.descriptor[word] == bits, "BRIEF descriptor word mismatch");
    }
}

/**
 * @brief Check changing inputs with the same guarded full-frame allocations.
 * @return Zero only if all records, guards, untouched tails and rejection cases match.
 * @note This is host/backend evidence, not ARM cache, RTL or changing-video board evidence.
 *       No input files or board connection are required.
 */
int main() {
    try {
        constexpr size_t guard = 32, full = 960u * 720u;
        const int widths[] = {960,800,667,556,463,386,322,268};
        const int heights[] = {720,600,500,417,347,289,241,201};
        const int counts[] = {256,1,31,128,32,255};
        std::vector<uint8_t> raw(full + 2 * guard), blurred(raw.size());
        std::array<NextPoint,256> points{};
        std::array<NextFeature,258> output;
        std::array<bool,32> bins{};
        uint32_t seed = UINT32_C(0x523132), features = 0;
        int transactions = 0, rejections = 0;
#if defined(NEXT_TEST_BACKEND_PROFILE)
        NextBackendProfile profile{};
        ProfileClock clock{UINT64_MAX - 14,0};
        require(next_backend_profile_configure(&profile,profile_clock,&clock) == 0,
            "Profile configure failed");
        require(next_backend_profile_configure(nullptr,profile_clock,&clock) == -1 &&
            next_backend_profile_configure(&profile,nullptr,&clock) == -1,
            "Invalid profile pair accepted");
#endif
        for (int level = 0; level < 8; ++level) {
            const int width = widths[level], height = heights[level];
            orb_golden::Image image(width, height);
            for (int pattern = 0; pattern < 6; ++pattern) {
                std::cerr << "BACKEND_CHANGING level=" << level << " pattern=" << pattern << '\n';
                fill_image(image, pattern, seed);
                const auto reference_blur = orb_golden::gaussian7(image);
                std::fill(raw.begin(), raw.end(), uint8_t(0xa5 ^ pattern));
                std::fill(blurred.begin(), blurred.end(), uint8_t(0x5a ^ pattern));
                std::memcpy(raw.data() + guard, image.pixels.data(), image.pixels.size());
                std::memcpy(blurred.data() + guard, reference_blur.pixels.data(), image.pixels.size());
                const auto before_raw = raw, before_blur = blurred;
                const int count = counts[pattern];
                for (int index = 0; index < count; ++index) {
                    // Different order/coordinates on successive frames; random-angle
                    // points have a 24-pixel margin, including rotated BRIEF samples.
                    const int order = (pattern & 1) ? count - 1 - index : index;
                    points[index] = {8 + (order * 37 + level * 11 + pattern * 13) % (width - 48),
                        8 + (order * 53 + level * 7 + pattern * 17) % (height - 48),
                        (order * 19 + pattern * 31) & 255, index % 204};
                }
                if (pattern == 0) {
                    // A constant image has bin 0, whose pattern is safe at all four
                    // legal effective-coordinate extrema. Do not exclude edge points.
                    points[0] = {0,0,0,0}; points[1] = {width-33,0,255,1};
                    points[2] = {0,height-33,1,2}; points[3] = {width-33,height-33,254,3};
                }
                std::memset(output.data(), 0xc3, sizeof(output));
                const auto before_output = output;
                require(describe_for_test(raw.data()+guard, blurred.data()+guard, width,height,
                    points.data(),count,level,output.data()+1,256) == 0, "Changing backend status");
                for (int index = 0; index < count; ++index) {
                    const auto& point = points[index];
                    const auto expected = orb_golden::describe(image, reference_blur,
                        {point.x+16,point.y+16,point.score,point.tile}, level, 32);
                    compare_feature(output[index+1], expected);
                    bins[size_t(expected.bin)] = true;
                    ++features;
                }
                require(std::memcmp(output.data(),before_output.data(),sizeof(NextFeature)) == 0 &&
                    std::memcmp(output.data()+count+1,before_output.data()+count+1,
                        (output.size()-count-1)*sizeof(NextFeature)) == 0,
                    "Output guard or unused feature tail overwritten");
                require(raw == before_raw && blurred == before_blur, "Image/guard/tail mutated");
                ++transactions;
                std::cout << "BACKEND_CHANGING_CASE_PASS level=" << level << " pattern=" << pattern
                          << " features=" << count << '\n';
            }
            const auto empty_before = output;
            require(describe_for_test(raw.data()+guard,blurred.data()+guard,width,height,
                nullptr,0,level,output.data()+1,0) == 0 &&
                std::memcmp(output.data(),empty_before.data(),sizeof(output)) == 0,
                "Empty point list changed reused output");
            ++transactions;
        }
        // Reject before writing the first record; no assumption of rollback of
        // already completed records when a later point is invalid.
        std::memset(output.data(),0xc3,sizeof(output));
        const auto rejected_before = output;
        const NextPoint invalid[] = {{-1,0,0,0},{928,0,0,0},{0,-1,0,0},{0,688,0,0}};
        for (const auto& point : invalid) {
            require(describe_for_test(raw.data()+guard,blurred.data()+guard,960,720,&point,1,0,
                output.data()+1,256) == -2, "Illegal point not rejected");
            ++rejections;
        }
        require(describe_for_test(raw.data()+guard,blurred.data()+guard,960,720,points.data(),256,0,
            output.data()+1,255) == -1, "Insufficient capacity not rejected"); ++rejections;
        require(describe_for_test(raw.data()+guard,blurred.data()+guard,960,720,points.data(),257,0,
            output.data()+1,256) == -1, "Excess count not rejected"); ++rejections;
        require(describe_for_test(raw.data()+guard,blurred.data()+guard,960,720,points.data(),1,8,
            output.data()+1,256) == -1, "Illegal level not rejected"); ++rejections;
        require(describe_for_test(raw.data()+guard,blurred.data()+guard,32,720,points.data(),1,0,
            output.data()+1,256) == -1, "Illegal geometry not rejected"); ++rejections;
        require(std::memcmp(output.data(),rejected_before.data(),sizeof(output)) == 0,
            "Rejected first record changed output");
        const int covered_bins = int(std::count(bins.begin(),bins.end(),true));
        require(covered_bins == 32, "Not all A32 bins exercised");
#if defined(NEXT_TEST_BACKEND_PROFILE)
        require(profile.completed_features == features && clock.calls == uint64_t(features)*4 &&
            profile.moment_ticks == uint64_t(features)*7 &&
            profile.cordic_ticks == uint64_t(features)*7 &&
            profile.brief_ticks == uint64_t(features)*7,
            "Profile stage boundaries/read count/wrap/empty/invalid accounting mismatch");
        const auto before_disable = profile;
        const uint64_t calls_before_disable = clock.calls;
        require(next_backend_profile_configure(nullptr,nullptr,nullptr) == 0, "Profile disable failed");
        NextFeature baseline{}, disabled{};
        require(next_describe(raw.data()+guard,blurred.data()+guard,268,201,points.data(),1,7,&baseline,1) == 0 &&
            next_describe_profiled(raw.data()+guard,blurred.data()+guard,268,201,points.data(),1,7,&disabled,1) == 0 &&
            std::memcmp(&baseline,&disabled,sizeof(baseline)) == 0 && clock.calls == calls_before_disable &&
            profile.completed_features == before_disable.completed_features &&
            profile.moment_ticks == before_disable.moment_ticks &&
            profile.cordic_ticks == before_disable.cordic_ticks && profile.brief_ticks == before_disable.brief_ticks,
            "Disabled profile changed features, statistics or clock reads");
        std::cout << "NEXT_BACKEND_PROFILE_PASS features=" << features
                  << " clock_reads=" << clock.calls << " stages=3 wrap=1 disabled_exact=1\n";
#endif
        std::cout << "NEXT_BACKEND_CHANGING_PASS transactions=" << transactions << " features=" << features
                  << " bins=" << covered_bins << " rejections=" << rejections << " seed=0x523132\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "NEXT_BACKEND_CHANGING_FAIL: " << error.what() << '\n';
        return 1;
    }
}
