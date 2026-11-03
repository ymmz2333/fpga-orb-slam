// PS publication handoff; independent of map geometry and optimization policy.
#pragma once
#include <cstddef>
#include <cstdint>
namespace KvMapperProgress {
void submitted(const void* keyframe);
void published(const void* keyframe);
double wait(unsigned timeout_ms);
struct Counts {uint64_t submitted,published;size_t pending;};
Counts counts();
#ifdef KV_MAPPER_PROGRESS_TEST
void reset_for_test();
#endif
}
