#pragma once

// SDK 2018.3 GCC 7.3 exposes the Filesystem TS; newer compilers use C++17.
#if __has_include(<filesystem>)
#include <filesystem>
namespace zslam { namespace fs = std::filesystem; }
#else
#include <experimental/filesystem>
namespace zslam { namespace fs = std::experimental::filesystem; }
#endif
