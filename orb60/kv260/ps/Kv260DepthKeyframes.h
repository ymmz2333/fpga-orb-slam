// Read-only depth scheduling instrumentation. No SLAM decisions are changed.
#pragma once
#include <cstdint>
#include <string>
namespace ORB_SLAM3 { class KeyFrame; }
namespace KvDepth {
void begin(uint64_t source_frame, uint64_t timestamp_ns, uint32_t gray_crc);
void publish(ORB_SLAM3::KeyFrame* keyframe);
bool enabled();
std::string ack();
}
