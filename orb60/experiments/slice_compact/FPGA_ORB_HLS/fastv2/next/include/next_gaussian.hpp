#pragma once
#include <cstdint>
/**
 * @brief Generate exact v1.0 Gaussian7 bytes for one frozen pyramid level.
 * @param source Row-major input bytes packed little-endian in 64-bit words.
 * @param destination Packed Gaussian bytes in a disjoint output buffer.
 * @param level Frozen profile 0..7.
 * @return fastv2::kOk or fastv2::kInvalidArgument.
 * @note Horizontal and vertical single-pixel stages overlap through DATAFLOW
 *       FIFOs. II=1 and finite-FIFO liveness require HLS/RTL verification;
 *       host models do not establish hardware throughput or backpressure safety.
 */
extern "C" int fastv2_gaussian_hls(const uint64_t* source, uint64_t* destination, int level);
