/** @file backend_profile_sdk.c @brief Independently named exact instrumented backend. */
#define NEXT_BACKEND_PROFILE 1
#define next_describe next_describe_profiled
#define next_angle_q16 next_angle_q16_profiled
#include "next_backend.c"
