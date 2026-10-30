#pragma once
#include "fastv2.hpp"
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <stdexcept>

using u32 = uint32_t;
using UINTPTR = uintptr_t;
using INTPTR = intptr_t;
using XTime = uint64_t;
#define COUNTS_PER_SECOND UINT64_C(1000000)
#define XPAR_PS7_DDR_0_S_AXI_HIGHADDR UINT32_C(0x1fffffff)
#define XPAR_FASTV2_FRONT_DEVICE_ID 0
#define XPAR_FASTV2_RESIZE_DEVICE_ID 0
#define XST_SUCCESS 0
#define FASTV2_PROGRAM_END UINTPTR(0x00100000)
#define xil_printf std::printf

/** @brief Select the deliberately injected software-model fault. */
enum class MockFault { none, summary, point, image, front_timeout, resize_timeout,
                       front_return, resize_return, front_initialize, resize_initialize,
                       front_no_summary, front_no_points, resize_no_output };
inline MockFault mock_fault = MockFault::none;
inline uint64_t mock_ticks = 0;
inline unsigned mock_front_calls = 0;
inline unsigned mock_resize_calls = 0;

/** @brief Host register model for the front accelerator; not a timing model. */
struct XFastv2_front_hls {
    u32 image_r = 0, selected = 0, result = 0, width = 0, height = 0, budget = 0;
    u32 high_threshold = 0, low_threshold = 0, dual_threshold = 0, selected_capacity = 0;
    int status = 0;
    bool done = false;
};
/** @brief Host register model for the resize accelerator. */
struct XFastv2_resize_hls {
    u32 source = 0, destination = 0, source_level = 0;
    int status = 0;
    bool done = false;
};

/** @brief Write one scalar driver register to the host model. */
#define MOCK_SETTER(type, field) \
    inline void type##_Set_##field(type* accelerator, u32 value) { accelerator->field = value; }
MOCK_SETTER(XFastv2_front_hls, image_r)
MOCK_SETTER(XFastv2_front_hls, selected)
MOCK_SETTER(XFastv2_front_hls, result)
MOCK_SETTER(XFastv2_front_hls, width)
MOCK_SETTER(XFastv2_front_hls, height)
MOCK_SETTER(XFastv2_front_hls, budget)
MOCK_SETTER(XFastv2_front_hls, high_threshold)
MOCK_SETTER(XFastv2_front_hls, low_threshold)
MOCK_SETTER(XFastv2_front_hls, dual_threshold)
MOCK_SETTER(XFastv2_front_hls, selected_capacity)
MOCK_SETTER(XFastv2_resize_hls, source)
MOCK_SETTER(XFastv2_resize_hls, destination)
MOCK_SETTER(XFastv2_resize_hls, source_level)
#undef MOCK_SETTER

/** @brief Check cache-call arguments; this cannot emulate physical coherency. */
inline void Xil_DCacheFlushRange(INTPTR address, u32 bytes) {
    if (address <= 0 || bytes == 0) throw std::runtime_error("Invalid cache flush");
}
/** @brief Check invalidate arguments without simulating ARM cache hardware. */
inline void Xil_DCacheInvalidateRange(INTPTR address, u32 bytes) {
    if (address <= 0 || bytes == 0) throw std::runtime_error("Invalid cache invalidate");
}
/** @brief Supply deterministic timer ticks; inject watchdog expiration cheaply. */
inline void XTime_GetTime(XTime* result) {
    mock_ticks += (mock_fault == MockFault::front_timeout || mock_fault == MockFault::resize_timeout)
        ? 31000000 : 100;
    *result = mock_ticks;
}
/** @brief Initialize a front mock, optionally injecting driver lookup failure. */
inline int XFastv2_front_hls_Initialize(XFastv2_front_hls* accelerator, int) {
    *accelerator = XFastv2_front_hls{};
    return mock_fault == MockFault::front_initialize ? 102 : 0;
}
/** @brief Initialize a resize mock, optionally injecting lookup failure. */
inline int XFastv2_resize_hls_Initialize(XFastv2_resize_hls* accelerator, int) {
    *accelerator = XFastv2_resize_hls{};
    return mock_fault == MockFault::resize_initialize ? 101 : 0;
}
/** @brief Execute the actual front C model using the PS-supplied registers. */
inline void XFastv2_front_hls_Start(XFastv2_front_hls* accelerator) {
    ++mock_front_calls;
    auto* summary = reinterpret_cast<fastv2::Result*>(UINTPTR(accelerator->result));
    auto* points = reinterpret_cast<fastv2::Point*>(UINTPTR(accelerator->selected));
    if (mock_fault == MockFault::front_no_summary) {
        accelerator->status = 0;
        accelerator->done = true;
        return;
    }
    accelerator->status = fastv2_front_hls(
        reinterpret_cast<const uint64_t*>(UINTPTR(accelerator->image_r)), points, summary,
        accelerator->width, accelerator->height, accelerator->budget,
        accelerator->high_threshold, accelerator->low_threshold,
        accelerator->dual_threshold, accelerator->selected_capacity);
    if (mock_fault == MockFault::summary) ++summary->fallback_cells;
    if (mock_fault == MockFault::point && summary->selected_count > 0) ++points[0].score;
    if (mock_fault == MockFault::front_no_points) {
        std::memset(points, 0xa5, accelerator->selected_capacity * sizeof(fastv2::Point));
    }
    if (mock_fault == MockFault::front_return) accelerator->status = 2;
    accelerator->done = mock_fault != MockFault::front_timeout;
}
/** @brief Execute the actual resize C model using PS ping-pong addresses. */
inline void XFastv2_resize_hls_Start(XFastv2_resize_hls* accelerator) {
    ++mock_resize_calls;
    auto* destination = reinterpret_cast<uint64_t*>(UINTPTR(accelerator->destination));
    if (mock_fault == MockFault::resize_no_output) {
        accelerator->status = 0;
        accelerator->done = true;
        return;
    }
    accelerator->status = fastv2_resize_hls(
        reinterpret_cast<const uint64_t*>(UINTPTR(accelerator->source)),
        destination, accelerator->source_level);
    if (mock_fault == MockFault::image) destination[0] ^= 1;
    if (mock_fault == MockFault::resize_return) accelerator->status = 2;
    accelerator->done = mock_fault != MockFault::resize_timeout;
}
/** @brief Observe and clear ap_done, matching the generated HLS driver contract. */
#define MOCK_DONE(type) \
    inline u32 type##_IsDone(type* accelerator) { \
        const bool result = accelerator->done; accelerator->done = false; return result; } \
    inline u32 type##_Get_return(type* accelerator) { return u32(accelerator->status); }
MOCK_DONE(XFastv2_front_hls)
MOCK_DONE(XFastv2_resize_hls)
#undef MOCK_DONE
