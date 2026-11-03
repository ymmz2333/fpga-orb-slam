// GPL-3.0-or-later. Read-only copy of the actual consumed 7015 result.
#pragma once
#include <cstdint>
#include <vector>
#include <opencv2/features2d.hpp>
namespace KvNetwork {
struct Record {
    uint64_t timestamp=0,engine_ns=0;
    uint32_t count=0,records_crc=0;
    std::vector<cv::KeyPoint> keys;
};
// GCC unique inline storage is shared by the private SLAM DSO and its caller.
// The caller checks the timestamp/count every frame; an ABI mismatch fails.
inline Record& current() {static thread_local Record value;return value;}
inline void observe(uint64_t stamp,const std::vector<uint8_t>& payload,unsigned count,
                    const std::vector<cv::KeyPoint>& keys) {
    auto& r=current();r.timestamp=stamp;r.count=count;r.keys=keys;
    r.engine_ns=orb_get64(payload.data()+64);
    r.records_crc=orb_crc32(payload.data()+128,count*64);
}
}
