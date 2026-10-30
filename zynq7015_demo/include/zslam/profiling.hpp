#pragma once
#if defined(__linux__)
#include <time.h>
#endif
namespace zslam {
inline double threadCpuMs(){
#if defined(__linux__)
    timespec t{};if(!clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t))return double(t.tv_sec)*1000+double(t.tv_nsec)*1e-6;
#endif
    return 0;
}
}
