#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <algorithm>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
#include "board_contract.h"
#include "board_mock.hpp"
#define NEXT_BOARD_HOST_TEST
#define next_describe board_mock_describe
#define main next_board_test_entry
#if defined(ORB60_FROZEN_PS)
#include "../frozen_ps/board_benchmark.c"
#else
#include "../ps/board_benchmark.c"
#endif
#undef main
#undef next_describe

/** @brief Fail deterministic Release-mode assertions with relevant diagnostics. */
static void require(bool valid, const char* message) { if (!valid) throw std::runtime_error(message); }
/** @brief Run the same checker and, in Profile builds, validate its DDR sidecar independently. */
static int run_board_entry() {
    const int status=next_board_test_entry();
#if defined(NEXT_BOARD_PROFILE) && NEXT_BOARD_PROFILE
    const auto* words=profile_words();
    require(words[PH_MAGIC]==NEXT_PROFILE_MAGIC && words[PH_SCHEMA]==1 &&
        words[PH_STATUS]==mailbox()[MB_STATUS] && words[PH_COUNT]==mailbox()[MB_COMPLETED] &&
        words[PH_MODE]==mailbox()[MB_MODE] && words[PH_SCHEDULE]==mailbox()[MB_SCHEDULE],
        "Profile terminal status/count/mode differs from mailbox");
    std::vector<uint64_t> processing,wall;
    for (uint32_t frame=0;frame<words[PH_COUNT];++frame) {
        const auto* record=words+64+frame*32;
        const auto ticks=[&](uint32_t offset) { return uint64_t(record[offset])|(uint64_t(record[offset+1])<<32); };
        require(record[PF_INDEX]==frame && record[PF_SELECTED]==280 && record[PF_FEATURES]==280 &&
            record[PF_CLOCK_READS]==1120 && record[PF_CANDIDATES]==11078 &&
            ticks(PF_WALL)==ticks(PF_PROCESS)+ticks(PF_VERIFY) &&
            ticks(PF_MOMENTS)+ticks(PF_CORDIC)+ticks(PF_BRIEF)<=ticks(PF_BACKEND),
            "Profile frame counts/stage accounting differ");
        processing.push_back(ticks(PF_PROCESS)); wall.push_back(ticks(PF_WALL));
    }
    if (!processing.empty()) {
        std::sort(processing.begin(),processing.end()); std::sort(wall.begin(),wall.end());
        const auto ticks=[&](uint32_t offset) { return uint64_t(words[offset])|(uint64_t(words[offset+1])<<32); };
        const size_t p95=(processing.size()*95+99)/100-1,p99=(processing.size()*99+99)/100-1;
        require(ticks(PH_PROCESS_P95)==processing[p95] && ticks(PH_PROCESS_P99)==processing[p99] &&
            ticks(PH_WALL_P95)==wall[p95] && ticks(PH_WALL_P99)==wall[p99],"Profile percentile mismatch");
    }
#endif
    return status;
}
/**
 * @brief Independently compare every production backend result against CPU records.
 * @param features Completed records, before any injected corruption.
 * @param count Number of active records in this level.
 * @param level Frozen level index in 0..7.
 * @note This host-only observer does not add oracle checks to production firmware.
 */
void board_check_features(const NextFeature* features, int count, int level) {
    require(count == kExpectedSummaries[level].selected_count, "Production feature count differs");
    require(std::memcmp(features, kExpectedFeatures[level], size_t(count)*sizeof(*features)) == 0,
            "Production skipped or changed descriptor computation");
}
/** @brief Sum mock cache API bytes excluding mailbox publication and input upload. */
static uint64_t cache_bytes() {
    uint64_t bytes = 0;
    for (const auto& call : board_cache_calls)
        if (call.address != NEXT_MAILBOX && call.address != NEXT_INPUT_PGM &&
            call.address != NEXT_REFERENCE_RAW && call.address != NEXT_REFERENCE_BLUR
#if defined(NEXT_BOARD_PROFILE) && NEXT_BOARD_PROFILE
            && call.address!=NEXT_PROFILE_DDR
#endif
            ) bytes += call.bytes;
    return bytes;
}
/**
 * @brief Upload exactly one CPU-generated file into isolated mock DDR.
 * @param path Binary input path.
 * @param address Fixed mapped destination.
 * @param bytes Exact expected size; extra or missing bytes are rejected.
 */
static void upload(const char* path, uintptr_t address, size_t bytes) {
    std::ifstream input(path, std::ios::binary);
    require(bool(input), "Missing mock DDR input");
    input.read(reinterpret_cast<char*>(address), std::streamsize(bytes));
    require(size_t(input.gcount()) == bytes && input.peek() == EOF, "Wrong mock DDR input size");
}
/**
 * @brief Run real three-core PS scheduling/checking against real C models and fault injection.
 * @param argc Must be four.
 * @param argv Program name, archived PGM, raw pyramid binary and Gaussian pyramid binary.
 * @return Zero only for repeated-frame PASS and all injected terminal FAIL states.
 * @note Register/cache/timer mocks cannot establish hardware timing or concurrency.
 */
int main(int argc, char** argv) {
    if (argc != 4) return 2;
    std::vector<void*> mappings;
    try {
#if defined(NEXT_BOARD_PROFILE) && NEXT_BOARD_PROFILE
        void* profile_allocation=VirtualAlloc(reinterpret_cast<void*>(NEXT_PROFILE_DDR),
            NEXT_PROFILE_BYTES+64,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
        require(profile_allocation==reinterpret_cast<void*>(NEXT_PROFILE_DDR),"Cannot map Profile DDR");
        mappings.push_back(profile_allocation);
#endif
        const uintptr_t addresses[] = {NEXT_MAILBOX, NEXT_INPUT_PGM, NEXT_PYRAMID0, NEXT_PYRAMID1,
            NEXT_ALIGNED_INPUT, NEXT_BLURRED, NEXT_POINTS, NEXT_SUMMARY, NEXT_FEATURES,
            NEXT_REFERENCE_RAW, NEXT_REFERENCE_BLUR, NEXT_PIPE_RAW2, NEXT_PIPE_BLUR1,
            NEXT_PIPE_POINTS1, NEXT_PIPE_SUMMARY1};
        const size_t sizes[] = {512, NEXT_MAX_PIXELS+15, NEXT_MAX_PIXELS+128, NEXT_MAX_PIXELS+128,
            NEXT_MAX_PIXELS+128, NEXT_MAX_PIXELS+128, 256*sizeof(OrbPoint)+128,
            128, 256*sizeof(NextFeature), NEXT_REFERENCE_PIXELS, NEXT_REFERENCE_PIXELS,
            NEXT_MAX_PIXELS+128, NEXT_MAX_PIXELS+128, 256*sizeof(OrbPoint)+128, 128};
        for (int index = 0; index < 15; ++index) {
            void* target = reinterpret_cast<void*>(addresses[index]);
            void* allocation = VirtualAlloc(target, sizes[index], MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
            require(allocation == target, "Cannot map isolated next DDR workspace"); mappings.push_back(allocation);
        }
        upload(argv[1], NEXT_INPUT_PGM, NEXT_MAX_PIXELS+15);
        upload(argv[2], NEXT_REFERENCE_RAW, NEXT_REFERENCE_PIXELS);
        upload(argv[3], NEXT_REFERENCE_BLUR, NEXT_REFERENCE_PIXELS);
        volatile uint32_t* result = mailbox();
        uint64_t legacy_bytes = 0, verified_bytes = 0;
        uint32_t serial_digest[2] = {};
        for (uint32_t mode : {uint32_t(NEXT_MODE_LEGACY), uint32_t(NEXT_MODE_VERIFIED), uint32_t(NEXT_MODE_PRODUCTION)}) {
        for (uint32_t requested : {1u,3u,1001u}) {
            reset_board_mock(BoardFault::none);
            board_check_backend_outputs = true;
            result[MB_COMMAND] = NEXT_COMMAND_MAGIC; result[MB_ITERATIONS] = requested;
            result[MB_MODE] = mode;
            result[MB_SCHEDULE] = NEXT_SCHEDULE_SERIAL;
            const uint32_t expected = requested == 1001 ? 1 : requested;
            require(run_board_entry() == 0, "Unexpected three-core PS failure");
            require(result[MB_STATUS] == (mode == NEXT_MODE_PRODUCTION ? NEXT_COMPLETE_UNVERIFIED : NEXT_PASS) &&
                    result[MB_SCHEMA] == 5 && result[MB_COMPLETED] == expected && result[MB_MODE] == mode,
                    "Incorrect schema-5 mode-tagged completion");
            require(result[MB_CANDIDATES] == 11078 && result[MB_SELECTED] == 280, "Incorrect complete-frame totals");
            require(board_calls[0] == 8*expected && board_calls[1] == 7*expected && board_calls[2] == 8*expected,
                    "Incorrect three-core launch counts");
            require(board_backend_calls == 8*expected, "Backend omitted from timed mode");
            require(result[MB_WALL_US] == result[MB_PROCESS_US]+result[MB_VERIFY_US],
                    "Verification/processing timing accounting is inconsistent");
            require(result[MB_PROCESS_US] == result[MB_PREP_US]+result[MB_CACHE_US]+result[MB_WAIT_US]+
                    result[MB_CONFIG_US]+result[MB_BACKEND_US]+result[MB_OTHER_US], "Stage timing does not reconcile");
            require(result[MB_BACKEND_US] != 0 && result[MB_WAIT_US] != 0, "Missing processing work");
            if (mode == NEXT_MODE_PRODUCTION) {
                require(result[MB_VERIFIED_FRAMES] == 0 && result[MB_VERIFY_US] == 0 && result[MB_PREP_US] == 0 &&
                        result[MB_DIGEST_HI] == 0 && result[MB_DIGEST_LO] == 0, "Production misrepresented as verified");
            } else require(result[MB_VERIFIED_FRAMES] == expected && result[MB_VERIFY_US] != 0 &&
                           result[MB_PREP_US] != 0, "Verified coverage omitted");
            if (mode != NEXT_MODE_LEGACY) {
                unsigned input_flushes = 0;
                for (const auto& call : board_cache_calls)
                    if (call.flush && call.address == NEXT_ALIGNED_INPUT) ++input_flushes;
                require(input_flushes == 1, "Read-only input redundantly flushed inside frames");
            }
            if (requested == 1 && mode == NEXT_MODE_LEGACY) legacy_bytes = cache_bytes();
            if (requested == 1 && mode == NEXT_MODE_VERIFIED) {
                verified_bytes = cache_bytes(); serial_digest[0] = result[MB_DIGEST_HI]; serial_digest[1] = result[MB_DIGEST_LO];
            }
        }
        }
        require(verified_bytes < legacy_bytes, "Optimized verified cache traffic not reduced");
        const BoardFault faults[] = {BoardFault::resize_pixel, BoardFault::blur_pixel, BoardFault::summary,
            BoardFault::point, BoardFault::gaussian_guard, BoardFault::front_return,
            BoardFault::gaussian_timeout, BoardFault::backend_descriptor, BoardFault::gaussian_no_write,
            BoardFault::gaussian_padding, BoardFault::unused_point, BoardFault::bad_count};
        const int expected_errors[] = {ERR_RAW,ERR_BLUR,ERR_SUMMARY,ERR_POINTS,ERR_GUARD,ERR_RETURN,ERR_TIMEOUT,ERR_FEATURE,
                                       ERR_BLUR,ERR_GUARD,ERR_GUARD,ERR_SUMMARY};
        for (uint32_t mode : {uint32_t(NEXT_MODE_LEGACY), uint32_t(NEXT_MODE_VERIFIED)}) {
        for (int index = 0; index < 12; ++index) {
            reset_board_mock(faults[index]);
            result[MB_COMMAND] = NEXT_COMMAND_MAGIC; result[MB_ITERATIONS] = 1;
            result[MB_MODE] = mode;
            result[MB_SCHEDULE] = NEXT_SCHEDULE_SERIAL;
            require(run_board_entry() == expected_errors[index], "Wrong injected three-core error");
            require(result[MB_STATUS] == NEXT_FAIL && result[MB_ERROR] == uint32_t(expected_errors[index]),
                    "Injected fault did not commit FAIL");
        }
        }
        /* Production retains transport/runtime error handling, not exact data acceptance. */
        for (int index : {5,6}) {
            reset_board_mock(faults[index]);
            result[MB_COMMAND] = NEXT_COMMAND_MAGIC; result[MB_ITERATIONS] = 1;
            result[MB_MODE] = NEXT_MODE_PRODUCTION;
            result[MB_SCHEDULE] = NEXT_SCHEDULE_SERIAL;
            require(run_board_entry() == expected_errors[index] && result[MB_STATUS] == NEXT_FAIL,
                    "Production ignored a runtime error");
        }
        reset_board_mock(BoardFault::backend_descriptor);
        result[MB_COMMAND] = NEXT_COMMAND_MAGIC; result[MB_ITERATIONS] = 1;
        result[MB_MODE] = NEXT_MODE_PRODUCTION;
        result[MB_SCHEDULE] = NEXT_SCHEDULE_SERIAL;
        require(run_board_entry() == 0 && result[MB_STATUS] == NEXT_COMPLETE_UNVERIFIED &&
                result[MB_VERIFIED_FRAMES] == 0, "Unverified descriptor incorrectly published PASS");
        reset_board_mock(BoardFault::none);
        result[MB_COMMAND] = NEXT_COMMAND_MAGIC; result[MB_ITERATIONS] = 1; result[MB_MODE] = 99;
        result[MB_SCHEDULE] = NEXT_SCHEDULE_SERIAL;
        require(run_board_entry() == ERR_COMMAND && result[MB_STATUS] == NEXT_FAIL && board_calls[0] == 0,
                "Unknown mode launched hardware");
        reset_board_mock(BoardFault::none);
        result[MB_COMMAND] = 0; result[MB_ITERATIONS] = 99; result[MB_MODE] = 99;
        require(run_board_entry() == 0 && result[MB_STATUS] == NEXT_PASS && result[MB_MODE] == NEXT_MODE_VERIFIED &&
                result[MB_COMPLETED] == 1, "Standalone default did not select verified one-frame mode");
        for (uintptr_t address : {uintptr_t(NEXT_INPUT_PGM), uintptr_t(NEXT_REFERENCE_RAW), uintptr_t(NEXT_REFERENCE_BLUR)}) {
            auto* byte = reinterpret_cast<uint8_t*>(address); byte[0] ^= 1;
            reset_board_mock(BoardFault::none);
            result[MB_COMMAND] = NEXT_COMMAND_MAGIC; result[MB_ITERATIONS] = 1;
            result[MB_MODE] = NEXT_MODE_VERIFIED;
            result[MB_SCHEDULE] = NEXT_SCHEDULE_SERIAL;
            require(run_board_entry() == (address == NEXT_INPUT_PGM ? ERR_INPUT : ERR_REFERENCE), "Bad upload accepted");
            require(result[MB_STATUS] == NEXT_FAIL, "Bad upload did not commit FAIL"); byte[0] ^= 1;
        }
        /* Exercise late/early completions and DDR reuse with real C models, not fake pixels. */
        unsigned pipeline_frames = 0, pipeline_faults = 0;
        const uint64_t delays[3][3] = {{50000,30000,60000},{30000,70000,40000},{70000,20000,30000}};
        for (uint32_t mode : {uint32_t(NEXT_MODE_VERIFIED), uint32_t(NEXT_MODE_PRODUCTION)}) {
        for (int order = 0; order < 3; ++order) {
            reset_board_mock(BoardFault::none); board_async = true; board_check_backend_outputs = true;
            for (int core = 0; core < 3; ++core) board_delay[core] = delays[order][core];
            board_backend_delay = order == 1 ? 90000 : 1000;
            result[MB_COMMAND] = NEXT_COMMAND_MAGIC; result[MB_ITERATIONS] = 3;
            result[MB_MODE] = mode; result[MB_SCHEDULE] = NEXT_SCHEDULE_PIPELINE;
            require(run_board_entry() == 0, "Deferred pipeline failed");
            require(result[MB_STATUS] == (mode == NEXT_MODE_PRODUCTION ? NEXT_COMPLETE_UNVERIFIED : NEXT_PASS) &&
                    result[MB_COMPLETED] == 3 && result[MB_SCHEDULE] == NEXT_SCHEDULE_PIPELINE &&
                    result[MB_BACKEND_AHEAD_LAUNCHES] == 21 && result[MB_PL_OBSERVATION_UPPER_BOUND] == 1 &&
                    result[MB_ABORT_DRAIN_ERROR] == 0 && result[MB_PENDING_CORE_MASK] == 0, "Pipeline result metadata differs");
            require(result[MB_CANDIDATES] == 11078 && result[MB_SELECTED] == 280 &&
                    board_calls[0] == 24 && board_calls[1] == 21 && board_calls[2] == 24 && board_backend_calls == 24,
                    "Pipeline omitted a core or backend");
            require(board_backend_with_pending == 21, "Backend did not run with next-level transaction pending");
            require(board_completion_order.size() == 69 && board_completion_order[0] == (order == 0 ? 1 : order == 1 ? 0 : 1),
                    "Deferred completion order was not exercised");
            require(result[MB_WALL_US] == result[MB_PROCESS_US]+result[MB_VERIFY_US] &&
                    result[MB_PROCESS_US] == result[MB_PREP_US]+result[MB_CACHE_US]+result[MB_WAIT_US]+
                    result[MB_CONFIG_US]+result[MB_BACKEND_US]+result[MB_OTHER_US], "Pipeline timing double-counted overlap");
            if (mode == NEXT_MODE_VERIFIED) require(result[MB_VERIFIED_FRAMES] == 3 &&
                result[MB_DIGEST_HI] == serial_digest[0] && result[MB_DIGEST_LO] == serial_digest[1],
                "Pipeline exact feature digest differs from serial");
            else require(result[MB_VERIFIED_FRAMES] == 0 && result[MB_VERIFY_US] == 0 && result[MB_PREP_US] == 0 &&
                result[MB_DIGEST_HI] == 0 && result[MB_DIGEST_LO] == 0, "Pipeline production falsely verified");
            pipeline_frames += 3;
        }
        }
        for (int fault_level : {0,3}) {
        for (int index = 0; index < 12; ++index) {
            reset_board_mock(faults[index]); board_async = true;
            board_fault_level = index == 9 ? 2 : fault_level;
            result[MB_COMMAND] = NEXT_COMMAND_MAGIC; result[MB_ITERATIONS] = 1;
            result[MB_MODE] = NEXT_MODE_VERIFIED; result[MB_SCHEDULE] = NEXT_SCHEDULE_PIPELINE;
            require(run_board_entry() == expected_errors[index] && result[MB_STATUS] == NEXT_FAIL &&
                    result[MB_ERROR] == uint32_t(expected_errors[index]), "Pipeline injected error not preserved");
            require(!board_pending[0] && !board_pending[1] && !board_pending[2], "Verification failure left queued mock DMA");
            if (index == 6) require(result[MB_PENDING_CORE_MASK] == 4, "Timeout omitted unquiesced Gaussian mask");
            ++pipeline_faults;
        }
        }
        for (uint32_t mode : {uint32_t(NEXT_MODE_VERIFIED), uint32_t(NEXT_MODE_PRODUCTION)}) {
            reset_board_mock(BoardFault::backend_invalid_point); board_async = true; board_fault_level = 3;
            result[MB_COMMAND] = NEXT_COMMAND_MAGIC; result[MB_ITERATIONS] = 1;
            result[MB_MODE] = mode; result[MB_SCHEDULE] = NEXT_SCHEDULE_PIPELINE;
            require(run_board_entry() == ERR_BACKEND && result[MB_STATUS] == NEXT_FAIL &&
                    result[MB_ABORT_DRAIN_ERROR] == 0 && !board_pending[0] && !board_pending[1] && !board_pending[2],
                    "Backend failure did not drain launched next-level work");
            ++pipeline_faults;
        }
        for (uint32_t schedule : {99u, uint32_t(NEXT_SCHEDULE_PIPELINE)}) {
            reset_board_mock(BoardFault::none);
            result[MB_COMMAND] = NEXT_COMMAND_MAGIC; result[MB_ITERATIONS] = 1;
            result[MB_MODE] = schedule == 99 ? NEXT_MODE_VERIFIED : NEXT_MODE_LEGACY; result[MB_SCHEDULE] = schedule;
            require(run_board_entry() == ERR_COMMAND && result[MB_STATUS] == NEXT_FAIL && board_calls[0] == 0,
                    "Invalid scheduling request launched hardware"); ++pipeline_faults;
        }
#if defined(NEXT_BOARD_PROFILE) && NEXT_BOARD_PROFILE
        // Capacity and restart coverage without running 1000 expensive C-model frames.
        // These ticks are deliberately synthetic; never reported as board performance.
        {
            auto* tail=reinterpret_cast<uint8_t*>(NEXT_PROFILE_DDR+NEXT_PROFILE_BYTES);
            std::memset(tail,0xa5,64);
            profile_initialize();
            uint64_t backend_fixture[8]={100},stage_fixture[3][8]={{0}};
            std::memset(profile_previous,0,sizeof(profile_previous));
            profile_stages={10,20,30,1}; profile_reads=4;
            for (uint32_t frame=0;frame<1000;++frame)
                require(profile_record(100+frame,200+frame,1,1,backend_fixture,stage_fixture,0)==0,
                    "1000-record Profile capacity rejected");
            const std::vector<uint32_t> before(profile_words(),profile_words()+NEXT_PROFILE_BYTES/4);
            require(profile_record(1,1,1,1,backend_fixture,stage_fixture,0)==-1 &&
                std::equal(before.begin(),before.end(),profile_words()),"Profile capacity overflow wrote DDR");
            result[MB_COMPLETED]=1000; result[MB_MODE]=NEXT_MODE_VERIFIED; result[MB_SCHEDULE]=NEXT_SCHEDULE_SERIAL;
            result[MB_ERROR]=0; result[MB_FAILING_ITERATION]=0;
            require(profile_finish(NEXT_PASS)==0 && profile_words()[PH_COUNT]==1000 &&
                profile_words()[PH_PROCESS_P95]==1049 && profile_words()[PH_PROCESS_P99]==1089 &&
                profile_words()[PH_WALL_P95]==1149,"1000-record Profile percentile/commit failure");
            for (int i=0;i<64;++i) require(tail[i]==0xa5,"Profile DDR tail guard overwritten");
            profile_initialize();
            require(profile_words()[PH_COUNT]==0 && profile_words()[PH_STATUS]==NEXT_RUNNING,
                "Profile restart retained stale committed records");
            profile_reads=3;
            require(profile_record(1,1,1,1,backend_fixture,stage_fixture,0)==-1 && profile_count==0,
                "Profile clock accounting error committed record");
        }
        std::cout << "NEXT_BOARD_PROFILE_HOST_PASS terminal_pairing=1 exact_outputs=1 failure_prefix=1 capacity=1000 overflow_guard=1 restart=1 physical_test=0\n";
#endif
        for (void* allocation : mappings) VirtualFree(allocation, 0, MEM_RELEASE);
        std::cout << "NEXT_BOARD_PS_HOST_PASS modes=3 nominal_frames=16 injected_failures=30 pipeline_frames=" << pipeline_frames
                  << " pipeline_injected_failures=" << pipeline_faults << " production_never_PASS=1"
                  << " cache_api_bytes_legacy=" << legacy_bytes << " cache_api_bytes_verified=" << verified_bytes
                  << " cores_per_frame=8/7/8 features=280 mock_not_hardware_FPS=1\n";
        return 0;
    } catch (const std::exception& error) {
        for (void* allocation : mappings) VirtualFree(allocation, 0, MEM_RELEASE);
        std::cerr << "NEXT_BOARD_PS_HOST_FAIL " << error.what() << '\n'; return 1;
    }
}
