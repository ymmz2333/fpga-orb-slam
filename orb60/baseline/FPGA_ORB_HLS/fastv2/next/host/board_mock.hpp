#pragma once
#include "fastv2.hpp"
#include "next_gaussian.hpp"
#include <cstring>
#include <stdexcept>
#include <vector>
#include <utility>
#if defined(NEXT_BOARD_PROFILE) && NEXT_BOARD_PROFILE
#include "next_backend_profile.h"
#endif
using UINTPTR = uintptr_t;
using INTPTR = intptr_t;
using XTime = uint64_t;
#define COUNTS_PER_SECOND UINT64_C(1000000)
#define XPAR_PS7_DDR_0_S_AXI_HIGHADDR UINT32_C(0x3fffffff)
#define NEXT_PROGRAM_END UINTPTR(0x00100000)
/** Faults exercise the real PS mailbox/checker, not physical AXI/cache timing. */
enum class BoardFault { none, resize_pixel, blur_pixel, summary, point, gaussian_guard,
                        front_return, gaussian_timeout, backend_descriptor,
                        gaussian_no_write, gaussian_padding, unused_point, bad_count, backend_invalid_point };
inline BoardFault board_fault = BoardFault::none;
inline uint64_t board_ticks = 0;
inline uint32_t board_registers[3][32] = {};
inline unsigned board_calls[3] = {};
/** Observed cache API calls, not a cache-line coherence or timing simulation. */
struct BoardCacheCall { bool flush; uintptr_t address; uint32_t bytes; };
inline std::vector<BoardCacheCall> board_cache_calls;
inline unsigned board_backend_calls = 0;
inline bool board_check_backend_outputs = false;
inline bool board_async = false;
inline bool board_pending[3] = {};
inline uint64_t board_due[3] = {};
inline uint32_t board_jobs[3][32] = {};
inline uint64_t board_delay[3] = {50000,30000,60000};
inline uint64_t board_backend_delay = 40000;
inline int board_fault_level = -1;
inline unsigned board_backend_with_pending = 0;
inline std::vector<int> board_completion_order;
/** @brief Execute due C models in completion-time order, never physical threads/AXI. */
inline void board_complete_due();
/** @brief Check that cache calls never touch a still-owned DMA destination. */
inline void board_check_cache_ownership(uintptr_t address, uint32_t bytes);

/** @brief Advance a deterministic software-only clock; never a hardware FPS source. */
inline void XTime_GetTime(XTime* ticks) {
    board_ticks += 1000; board_complete_due(); *ticks = board_ticks;
}
/** @brief Mock flush: checks software sequencing only, not cache coherence. */
inline void Xil_DCacheFlushRange(INTPTR address, uint32_t bytes) {
    board_check_cache_ownership(uintptr_t(address), bytes);
    board_cache_calls.push_back({true, uintptr_t(address), bytes});
}
/** @brief Mock invalidate: does not emulate cache lines or AXI visibility. */
inline void Xil_DCacheInvalidateRange(INTPTR address, uint32_t bytes) {
    board_check_cache_ownership(uintptr_t(address), bytes);
    board_cache_calls.push_back({false, uintptr_t(address), bytes});
}
/**
 * @brief Decode one of the fixed MMIO windows, rejecting unexpected addresses.
 * @param address Absolute control-register address.
 * @return Index in front/resize/Gaussian register storage.
 */
inline int board_core(uint32_t address) {
    if (address >= NEXT_FRONT_BASE && address < NEXT_FRONT_BASE + 128u) return 0;
    if (address >= NEXT_RESIZE_BASE && address < NEXT_RESIZE_BASE + 128u) return 1;
    if (address >= NEXT_GAUSSIAN_BASE && address < NEXT_GAUSSIAN_BASE + 128u) return 2;
    throw std::runtime_error("Unexpected PS MMIO address");
}
/**
 * @brief Read mocked registers with the actual ap_done clear-on-read behavior.
 * @param address Absolute register address, word aligned.
 * @return Current register value before side effects.
 */
inline uint32_t Xil_In32(uint32_t address) {
    board_complete_due();
    const int core = board_core(address);
    const unsigned word = (address & 127u) / 4u;
    const uint32_t value = board_registers[core][word];
    if (word == 0) board_registers[core][word] &= ~2u;
    return value;
}
/**
 * @brief Complete one frozen register transaction using the real HLS C model.
 * @param core Front/resize/Gaussian index in 0..2.
 * @param r Immutable register snapshot or immediate-model register bank.
 * @note Deferred completion checks scheduling, not physical AXI/cache concurrency.
 */
inline void board_execute_core(int core, const uint32_t* r) {
    const int widths[] = {960,800,667,556,463,386,322,268};
    int level = int(r[NEXT_LEVEL/4]);
    if (core == 0) {
        level = 0; while (level < 8 && widths[level] != int(r[NEXT_WIDTH/4])) ++level;
    }
    const BoardFault fault = board_fault_level < 0 || board_fault_level == level ? board_fault : BoardFault::none;
    const uint64_t* source = reinterpret_cast<const uint64_t*>(UINTPTR(r[NEXT_SOURCE/4]));
    uint64_t* output = reinterpret_cast<uint64_t*>(UINTPTR(r[NEXT_DESTINATION/4]));
    int status;
    if (core == 0) {
        status = fastv2_front_hls(source, reinterpret_cast<fastv2::Point*>(output),
            reinterpret_cast<fastv2::Result*>(UINTPTR(r[NEXT_FRONT_RESULT/4])),
            int(r[NEXT_WIDTH/4]), int(r[NEXT_HEIGHT/4]), int(r[NEXT_BUDGET/4]),
            int(r[NEXT_HIGH/4]), int(r[NEXT_LOW/4]), int(r[NEXT_DUAL/4]), int(r[NEXT_CAPACITY/4]));
        if (fault == BoardFault::summary) reinterpret_cast<uint8_t*>(UINTPTR(r[NEXT_FRONT_RESULT/4]))[0] ^= 1;
        if (fault == BoardFault::point) reinterpret_cast<uint8_t*>(output)[0] ^= 1;
        if (fault == BoardFault::backend_invalid_point) reinterpret_cast<NextPoint*>(output)[0].x = 1000;
        if (fault == BoardFault::unused_point) {
            const auto* summary = reinterpret_cast<const fastv2::Result*>(UINTPTR(r[NEXT_FRONT_RESULT/4]));
            reinterpret_cast<uint8_t*>(output)[summary->selected_count*sizeof(NextPoint)] ^= 1;
        }
        if (fault == BoardFault::bad_count)
            reinterpret_cast<fastv2::Result*>(UINTPTR(r[NEXT_FRONT_RESULT/4]))->selected_count = 257;
        if (fault == BoardFault::front_return) status = 4;
    } else if (core == 1) {
        status = fastv2_resize_hls(source, output, int(r[NEXT_LEVEL/4]));
        if (fault == BoardFault::resize_pixel) reinterpret_cast<uint8_t*>(output)[0] ^= 1;
    } else {
        status = fault == BoardFault::gaussian_no_write ? 0 :
                 fastv2_gaussian_hls(source, output, int(r[NEXT_LEVEL/4]));
        if (fault == BoardFault::blur_pixel) reinterpret_cast<uint8_t*>(output)[0] ^= 1;
        if (fault == BoardFault::gaussian_guard) {
            const int level = int(r[NEXT_LEVEL/4]);
            const int widths[] = {960,800,667,556,463,386,322,268};
            const int heights[] = {720,600,500,417,347,289,241,201};
            reinterpret_cast<uint8_t*>(output)[(widths[level]*heights[level]+7)&~7] ^= 1;
        }
        if (fault == BoardFault::gaussian_padding && r[NEXT_LEVEL/4] == 2)
            reinterpret_cast<uint8_t*>(output)[667*500] ^= 1;
    }
    board_registers[core][NEXT_RETURN/4] = uint32_t(status); board_registers[core][0] = 6;
    if (core == 2 && fault == BoardFault::gaussian_timeout) board_registers[core][0] = 0;
    board_completion_order.push_back(core);
}
/** @brief Finish deferred transactions in deterministic, configurable order. */
inline void board_complete_due() {
    for (;;) {
        int next = -1;
        for (int core = 0; core < 3; ++core) if (board_pending[core] && board_due[core] <= board_ticks &&
            (next < 0 || board_due[core] < board_due[next])) next = core;
        if (next < 0) return;
        board_pending[next] = false;
        board_execute_core(next, board_jobs[next]);
    }
}
/** @brief Decide whether two mapped DDR byte ranges overlap. */
inline bool board_ranges_overlap(uintptr_t a, size_t as, uintptr_t b, size_t bs) {
    return a < b + bs && b < a + as;
}
/** @brief Reject touching pending PL destinations; this is not cache coherence proof. */
inline void board_check_cache_ownership(uintptr_t address, uint32_t bytes) {
    for (int core = 0; core < 3; ++core) if (board_pending[core]) {
        const auto* r = board_jobs[core];
        const size_t size = core == 0 ? 256*sizeof(NextPoint) : size_t(NEXT_MAX_PIXELS);
        if (board_ranges_overlap(address, bytes, r[NEXT_DESTINATION/4], size) ||
            (core == 0 && board_ranges_overlap(address, bytes, r[NEXT_FRONT_RESULT/4], 64)))
            throw std::runtime_error("Cache operation on pending DMA destination");
    }
}
/** @brief Start immediate or deferred C-model transactions; reject busy reconfiguration. */
inline void Xil_Out32(uint32_t address, uint32_t value) {
    const int core = board_core(address); const unsigned word = (address & 127u)/4u;
    if (board_pending[core] || !(board_registers[core][0] & 4u))
        throw std::runtime_error("PS reconfigured busy mock core");
    board_registers[core][word] = value;
    if (word != 0 || !(value & 1u)) return;
    ++board_calls[core];
    if (board_async) {
        std::memcpy(board_jobs[core], board_registers[core], sizeof(board_jobs[core]));
        board_pending[core] = true; board_due[core] = board_ticks + board_delay[core];
        board_registers[core][0] = 0;
    } else board_execute_core(core, board_registers[core]);
}
/** @brief Reset mock control state without touching independently loaded DDR data. */
inline void reset_board_mock(BoardFault fault) {
    board_fault = fault; board_ticks = 0; board_backend_calls = 0;
    board_check_backend_outputs = false; board_cache_calls.clear();
    board_async = false; board_fault_level = -1; board_backend_with_pending = 0;
    board_completion_order.clear(); std::memset(board_pending, 0, sizeof(board_pending));
    std::memset(board_registers, 0, sizeof(board_registers));
    std::memset(board_calls, 0, sizeof(board_calls));
    for (int core = 0; core < 3; ++core) board_registers[core][0] = 4;
}
/** @brief Call the actual PS backend, optionally corrupting a completed descriptor. */
inline int board_mock_describe(const uint8_t* raw, const uint8_t* blurred, int width, int height,
                               const NextPoint* points, int count, int level,
                               NextFeature* features, int capacity) {
    ++board_backend_calls;
    if (board_async) {
        if (board_pending[0] || board_pending[1] || board_pending[2]) ++board_backend_with_pending;
        for (int core = 0; core < 3; ++core) if (board_pending[core]) {
            const auto* r = board_jobs[core]; const size_t bytes = core == 0 ? 256*sizeof(NextPoint) : size_t(NEXT_MAX_PIXELS);
            for (const auto& input : {std::make_pair(uintptr_t(raw), size_t(width)*height),
                                    std::make_pair(uintptr_t(blurred), size_t(width)*height),
                                    std::make_pair(uintptr_t(points), size_t(count)*sizeof(NextPoint))}) {
                if (board_ranges_overlap(input.first, input.second, r[NEXT_DESTINATION/4], bytes))
                    throw std::runtime_error("PS backend input aliases next-level PL writer");
            }
        }
        board_ticks += board_backend_delay; board_complete_due();
    }
#if defined(NEXT_BOARD_PROFILE) && NEXT_BOARD_PROFILE
    const int status = next_describe_profiled(raw, blurred, width, height, points, count, level, features, capacity);
#else
    const int status = next_describe(raw, blurred, width, height, points, count, level, features, capacity);
#endif
    if (board_check_backend_outputs && status == 0) {
        /* Independent tables are checked by the test callback defined below. */
        extern void board_check_features(const NextFeature*, int, int);
        board_check_features(features, count, level);
    }
    if (status == 0 && count && board_fault == BoardFault::backend_descriptor &&
        (board_fault_level < 0 || board_fault_level == level)) features[0].descriptor[0] ^= 1;
    return status;
}
