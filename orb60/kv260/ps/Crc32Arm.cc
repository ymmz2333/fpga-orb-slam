// IEEE CRC-32, not CRC-32C. Only this translation unit requires Arm CRC ISA.
// https://arm-software.github.io/acle/main/acle.html#crc32-intrinsics
#include <arm_acle.h>
#include <cstddef>
#include <cstdint>
#include <cstring>
extern "C" uint32_t orb_crc32_arm(const void* data, size_t length) {
    const auto* p=static_cast<const uint8_t*>(data);
    uint32_t crc=~uint32_t(0);
    while(length>=8) {
        uint64_t word;std::memcpy(&word,p,8);
        crc=__crc32d(crc,word);p+=8;length-=8;
    }
    while(length--)crc=__crc32b(crc,*p++);
    return ~crc;
}
