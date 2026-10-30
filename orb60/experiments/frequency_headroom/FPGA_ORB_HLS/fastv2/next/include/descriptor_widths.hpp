#pragma once
#include <cstdint>

// Build-time experiments only; no register, address or record-layout changes.
#ifndef ORB60_DESCRIPTOR_WIDTH_MODE
#define ORB60_DESCRIPTOR_WIDTH_MODE 0
#endif
#if ORB60_DESCRIPTOR_WIDTH_MODE < 0 || ORB60_DESCRIPTOR_WIDTH_MODE > 2
#error Unsupported descriptor width mode
#endif
#if ORB60_DESCRIPTOR_WIDTH_MODE > 0 && (defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM))
#include <ap_int.h>
typedef ap_int<21> MomentValue;
#else
typedef int32_t MomentValue;
#endif
#if ORB60_DESCRIPTOR_WIDTH_MODE == 2 && (defined(__SYNTHESIS__) || defined(FASTV2_HLS_CSIM))
typedef ap_int<43> CordicValue;
typedef ap_int<34> CordicAngle;
#else
typedef int64_t CordicValue;
typedef int64_t CordicAngle;
#endif
