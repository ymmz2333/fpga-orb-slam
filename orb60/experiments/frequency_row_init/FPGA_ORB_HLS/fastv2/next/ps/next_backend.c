/* GPL-3.0-or-later: exact arithmetic port of the existing v1.0 backend. */
#include "next_backend.h"
#include "backend_tables.h"
#include <string.h>

#if defined(NEXT_BACKEND_PROFILE) && NEXT_BACKEND_PROFILE
#include "next_backend_profile.h"
static NextBackendProfile* next_profile;
static NextBackendClock next_profile_clock;
static void* next_profile_context;

/** @copydoc next_backend_profile_configure */
int next_backend_profile_configure(NextBackendProfile* profile, NextBackendClock clock, void* context) {
    if ((!profile) != (!clock)) return -1;
    if (profile) memset(profile, 0, sizeof(*profile));
    next_profile = profile;
    next_profile_clock = clock;
    next_profile_context = context;
    return 0;
}
#endif

/** @brief Signed round-to-nearest, ties-to-even for bounded CORDIC values. */
static int64_t next_round_even(int64_t value, int64_t divisor) {
    const int negative = value < 0;
    const uint64_t magnitude = negative ? (uint64_t)(-(value + 1)) + 1u : (uint64_t)value;
    const uint64_t d = (uint64_t)divisor;
    uint64_t q = magnitude / d;
    const uint64_t remainder = magnitude % d;
    if (remainder > d - remainder || (remainder == d - remainder && (q & 1u))) ++q;
    return negative ? -(int64_t)q : (int64_t)q;
}

/**
 * @brief Divide by a power of two with exact negative floor semantics, without division.
 * @param value Signed CORDIC accumulator; the formula also handles INT64_MIN.
 * @param amount Shift count in 0..31, supplied by the fixed CORDIC loop.
 * @return floor(value / 2^amount), identical to the frozen CPU reference.
 * @note Shift only unsigned nonnegative magnitudes, avoiding implementation-defined
 *       negative right shifts. For value<0, floor(value/2^k)=-1-floor((-value-1)/2^k).
 */
static int64_t next_signed_shift(int64_t value, int amount) {
    if (value >= 0) return (int64_t)((uint64_t)value >> amount);
    return -INT64_C(1) - (int64_t)((uint64_t)(-(value + INT64_C(1))) >> amount);
}

/** @copydoc next_angle_q16 */
uint32_t next_angle_q16(int32_t m10, int32_t m01) {
    int64_t x, y, z = 0;
    int k;
    const int64_t full = INT64_C(360) << 24;
    if (m10 == 0 && m01 == 0) return 0;
    if (m01 == 0) return m10 < 0 ? 180u * 65536u : 0;
    if (m10 == 0) return m01 < 0 ? 270u * 65536u : 90u * 65536u;
    x = (int64_t)m10 * (INT64_C(1) << 20);
    y = (int64_t)m01 * (INT64_C(1) << 20);
    if (x < 0) { x = -x; y = -y; z = INT64_C(180) << 24; }
    for (k = 0; k < 32 && y != 0; ++k) {
        const int64_t old_x = x;
        if (y > 0) {
            x += next_signed_shift(y, k); y -= next_signed_shift(old_x, k);
            z += kNextCordicDegrees[k];
        } else {
            x -= next_signed_shift(y, k); y += next_signed_shift(old_x, k);
            z -= kNextCordicDegrees[k];
        }
    }
    z = (z % full + full) % full;
    return (uint32_t)(next_round_even(z, 256) % (INT64_C(360) << 16));
}

/** @copydoc next_describe */
int next_describe(const uint8_t* raw, const uint8_t* blurred, int width, int height,
                  const NextPoint* points, int count, int level,
                  NextFeature* features, int capacity) {
    int index;
    if (!raw || !blurred || width < 33 || width > 960 || height < 33 || height > 720 ||
        count < 0 || count > 256 || capacity < count || level < 0 || level > 7 ||
        (count && (!points || !features))) return -1;
    for (index = 0; index < count; ++index) {
        NextFeature feature;
        const NextPoint point = points[index];
        int u, v, bit;
        uint32_t precise;
#if defined(NEXT_BACKEND_PROFILE) && NEXT_BACKEND_PROFILE
        const int profile_active = next_profile != NULL;
        uint64_t moment_start = 0, cordic_start = 0, brief_start = 0;
#endif
        const uint64_t full = UINT64_C(360) << 16;
        if (point.x < 0 || point.x >= width - 32 || point.y < 0 || point.y >= height - 32) return -2;
        memset(&feature, 0, sizeof(feature));
        feature.x = point.x + 16; feature.y = point.y + 16;
        feature.score = point.score; feature.level = level;
#if defined(NEXT_BACKEND_PROFILE) && NEXT_BACKEND_PROFILE
        if (profile_active) moment_start = next_profile_clock(next_profile_context);
#endif
        for (u = -15; u <= 15; ++u) feature.m10 += u * raw[feature.y * width + feature.x + u];
        for (v = 1; v <= 15; ++v) {
            int vertical_sum = 0;
            for (u = -kNextUmax[v]; u <= kNextUmax[v]; ++u) {
                const int plus = raw[(feature.y + v) * width + feature.x + u];
                const int minus = raw[(feature.y - v) * width + feature.x + u];
                vertical_sum += plus - minus;
                feature.m10 += u * (plus + minus);
            }
            feature.m01 += v * vertical_sum;
        }
#if defined(NEXT_BACKEND_PROFILE) && NEXT_BACKEND_PROFILE
        if (profile_active) cordic_start = next_profile_clock(next_profile_context);
#endif
        precise = next_angle_q16(feature.m10, feature.m01);
        feature.bin = (int)(((uint64_t)precise * 32u + full / 2u) / full % 32u);
        feature.angle_q16 = (uint32_t)((uint64_t)feature.bin * full / 32u);
#if defined(NEXT_BACKEND_PROFILE) && NEXT_BACKEND_PROFILE
        if (profile_active) brief_start = next_profile_clock(next_profile_context);
#endif
        for (bit = 0; bit < 256; ++bit) {
            const int ax = feature.x + kNextBriefOffsets[feature.bin][bit * 2][0];
            const int ay = feature.y + kNextBriefOffsets[feature.bin][bit * 2][1];
            const int bx = feature.x + kNextBriefOffsets[feature.bin][bit * 2 + 1][0];
            const int by = feature.y + kNextBriefOffsets[feature.bin][bit * 2 + 1][1];
            if (ax < 0 || ax >= width || bx < 0 || bx >= width ||
                ay < 0 || ay >= height || by < 0 || by >= height) return -2;
            if (blurred[ay * width + ax] < blurred[by * width + bx]) {
                feature.descriptor[bit >> 5] |= UINT32_C(1) << (bit & 31);
            }
        }
#if defined(NEXT_BACKEND_PROFILE) && NEXT_BACKEND_PROFILE
        if (profile_active) {
            const uint64_t finish = next_profile_clock(next_profile_context);
            next_profile->moment_ticks += cordic_start - moment_start;
            next_profile->cordic_ticks += brief_start - cordic_start;
            next_profile->brief_ticks += finish - brief_start;
            ++next_profile->completed_features;
        }
#endif
        features[index] = feature;
    }
    return 0;
}
