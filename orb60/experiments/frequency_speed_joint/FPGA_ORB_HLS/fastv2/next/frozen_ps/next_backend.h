/* GPL-3.0-or-later: exact ORB-SLAM3-derived A32 descriptor semantics. */
#ifndef FASTV2_NEXT_BACKEND_H
#define FASTV2_NEXT_BACKEND_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct { int32_t x, y, score, tile; } NextPoint;
typedef struct {
    int32_t x, y, score, level, bin, m10, m01;
    uint32_t angle_q16;
    uint32_t descriptor[8];
} NextFeature;
typedef char NextFeatureMustBe64[(sizeof(NextFeature) == 64) ? 1 : -1];
/**
 * @brief Compute the reference IC/CORDIC precise orientation without floating point.
 * @param m10 Horizontal intensity moment.
 * @param m01 Vertical intensity moment.
 * @return Unsigned Q16.16 angle in [0,360) degrees before A32 quantization.
 */
uint32_t next_angle_q16(int32_t m10, int32_t m01);
/**
 * @brief Compute exact A32 moments, orientation and rotated 256-bit BRIEF on PS.
 * @param raw Raw row-major grayscale layer.
 * @param blurred Exact gaussian7 row-major 8-bit layer produced by PL.
 * @param width Layer stride, at most 960.
 * @param height Layer height, at most 720.
 * @param points Selected effective-coordinate records, before adding border 16.
 * @param count Number of records to describe; zero is legal.
 * @param level Pyramid-level metadata.
 * @param features Output records in unchanged input order.
 * @param capacity Available output record count.
 * @return Zero on success, -1 invalid argument, -2 out-of-bounds sample.
 */
int next_describe(const uint8_t* raw, const uint8_t* blurred, int width, int height,
                  const NextPoint* points, int count, int level,
                  NextFeature* features, int capacity);
#ifdef __cplusplus
}
#endif
#endif
