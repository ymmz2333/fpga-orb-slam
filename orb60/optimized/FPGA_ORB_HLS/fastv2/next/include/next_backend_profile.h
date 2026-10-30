/* GPL-3.0-or-later: optional instrumentation, not part of the PL/mailbox ABI. */
#ifndef NEXT_BACKEND_PROFILE_H
#define NEXT_BACKEND_PROFILE_H
#include "next_backend.h"
#ifdef __cplusplus
extern "C" {
#endif

typedef uint64_t (*NextBackendClock)(void* context);
typedef struct {
    uint64_t moment_ticks, cordic_ticks, brief_ticks;
    uint32_t completed_features;
} NextBackendProfile;

/**
 * @brief Configure the separately compiled profiled backend, or disable its clock.
 * @param profile Caller-owned statistics; reset on successful nonnull configuration.
 * @param clock Monotonic uint64 tick callback; four reads per completed feature.
 * @param context Opaque clock state; must remain valid until disabled.
 * @return Zero on success, -1 if exactly one of profile/clock is null.
 * @note Both null disable instrumentation. Single-threaded, non-reentrant use only;
 *       callbacks must not modify configuration. Unsigned deltas allow counter wrap.
 *       Intervals include timestamp boundary overhead; CORDIC includes A32 binning.
 *       Aborted BRIEF samples are not counted as completed features. This interface
 *       requires NEXT_BACKEND_PROFILE=1 and is absent from the default PS object.
 */
int next_backend_profile_configure(NextBackendProfile* profile, NextBackendClock clock, void* context);

/**
 * @brief Profile the same exact backend arithmetic in an independently named build.
 * @copydetails next_describe
 * @note Compile next_backend.c with next_describe=next_describe_profiled and
 *       next_angle_q16=next_angle_q16_profiled, as specified in CMakeLists.txt.
 *       No Cortex-A9 clock binding or mailbox publication is implied by this API.
 */
int next_describe_profiled(const uint8_t* raw, const uint8_t* blurred, int width, int height,
    const NextPoint* points, int count, int level, NextFeature* features, int capacity);

#ifdef __cplusplus
}
#endif
#endif
