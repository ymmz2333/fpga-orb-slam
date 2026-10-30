#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

#define FASTV2_PS_HOST_TEST
#define main fastv2_ps_test_entry
#include "../ps/fastv2_benchmark.c"
#undef main

/** @brief Throw on a failed assertion, including Release builds. */
static void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

/**
 * @brief Run the actual PS control/verification logic against real HLS C models.
 * @param argc Must be three including the program name.
 * @param argv Program name, fixed binary PGM, and reference-pyramid binary.
 * @return Zero for successful repeated frames and every injected failure case.
 * @note Driver/caches/timer are mocks: this does not establish AXI, cache or FPS.
 */
int main(int argc, char** argv) {
    if (argc != 3) return 2;
    std::vector<void*> mappings;
    try {
        const uintptr_t addresses[] = {kMailboxAddress, kInputPgmAddress,
            kPyramidBuffer0Address, kPyramidBuffer1Address, kAlignedInputAddress,
            kSelectedAddress, kSummaryAddress, kReferencePyramidAddress};
        const size_t bytes[] = {512, kMaximumPixels + kPgmHeaderBytes,
            kMaximumPixels + 64, kMaximumPixels + 64, kMaximumPixels + 64,
            kSelectedCapacity * sizeof(OrbPoint), kLevels * sizeof(Fastv2Summary), kReferencePixels};
        for (int index = 0; index < 8; ++index) {
            auto* address = reinterpret_cast<void*>(addresses[index]);
            void* mapping = VirtualAlloc(address, bytes[index], MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
            require(mapping == address, "Cannot map isolated mock DDR address");
            mappings.push_back(mapping);
        }
        std::ifstream input(argv[1], std::ios::binary);
        require(bool(input), "Missing PGM input");
        input.read(reinterpret_cast<char*>(UINTPTR(kInputPgmAddress)), kMaximumPixels + kPgmHeaderBytes);
        require(input.gcount() == kMaximumPixels + kPgmHeaderBytes, "Short PGM input");
        std::ifstream reference(argv[2], std::ios::binary);
        require(bool(reference), "Missing reference pixels");
        reference.read(reinterpret_cast<char*>(UINTPTR(kReferencePyramidAddress)), kReferencePixels);
        require(reference.gcount() == kReferencePixels, "Short reference pyramid");

        volatile OrbFastMailbox* const mailbox = benchmark_mailbox();
        /* One and 100 frames cover all eight levels and ping-pong reuse. */
        for (uint32_t iterations : {1u, 100u, 1001u}) {
            mock_fault = MockFault::none;
            mock_front_calls = mock_resize_calls = 0;
            mailbox->command_magic = kMailboxCommandMagic;
            mailbox->requested_iterations = iterations;
            const uint32_t expected = iterations == 1001 ? 1 : iterations;
            require(fastv2_ps_test_entry() == 0, "PS benchmark unexpectedly failed");
            require(mailbox->status == kMailboxPass && mailbox->schema_version == 2,
                    "Missing committed schema-2 PASS");
            require(mailbox->completed_iterations == expected, "Wrong iteration bounds");
            require(mailbox->candidates == 11078 && mailbox->reserved[40] == 280,
                    "Wrong eight-level candidate/selected totals");
            require(mock_front_calls == 8 * expected && mock_resize_calls == 7 * expected,
                    "Incorrect driver transaction count");
        }
        const MockFault faults[] = {MockFault::summary, MockFault::point, MockFault::image,
            MockFault::front_timeout, MockFault::resize_timeout, MockFault::front_return,
            MockFault::resize_return, MockFault::front_initialize, MockFault::resize_initialize,
            MockFault::front_no_summary, MockFault::front_no_points, MockFault::resize_no_output};
        const int expected_errors[] = {kErrorSummary, kErrorSelectedRecord, kErrorImageDigest,
            kErrorFastTimeout, kErrorResizeTimeout, kErrorFastAccelerator,
            kErrorResizeAccelerator, kErrorFastInitialize, kErrorResizeInitialize,
            kErrorSummary, kErrorSelectedRecord, kErrorImageDigest};
        for (int index = 0; index < 12; ++index) {
            mock_fault = faults[index];
            mailbox->command_magic = kMailboxCommandMagic;
            mailbox->requested_iterations = 1;
            require(fastv2_ps_test_entry() == expected_errors[index], "Wrong injected error code");
            require(mailbox->status == kMailboxFail && mailbox->error_code == u32(expected_errors[index]),
                    "Injected error did not commit FAIL");
        }
        mock_fault = MockFault::none;
        auto* reference_pixels = reinterpret_cast<uint8_t*>(UINTPTR(kReferencePyramidAddress));
        reference_pixels[0] ^= 1;
        require(fastv2_ps_test_entry() == kErrorInputReference && mailbox->status == kMailboxFail,
                "Corrupt reference did not fail");
        reference_pixels[0] ^= 1;
        *reinterpret_cast<uint8_t*>(UINTPTR(kInputPgmAddress)) = 'X';
        require(fastv2_ps_test_entry() == kErrorInputPgm && mailbox->status == kMailboxFail,
                "Invalid PGM did not fail");
        for (void* mapping : mappings) VirtualFree(mapping, 0, MEM_RELEASE);
        std::cout << "FASTV2_PS_HOST_PASS repeated_frames=100 injected_failures=14\n";
        return 0;
    } catch (const std::exception& error) {
        for (void* mapping : mappings) VirtualFree(mapping, 0, MEM_RELEASE);
        std::cerr << "FASTV2_PS_HOST_FAIL: " << error.what() << '\n';
        return 1;
    }
}
