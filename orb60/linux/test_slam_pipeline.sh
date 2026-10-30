#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
slam="$(realpath "$1")"
output="$(realpath "$2")"
install="$(realpath "$slam/../../install")"
g++ -std=c++14 -O2 -Wall -Wextra -pthread -I"$slam/include" -I"$install/include/opencv4" \
    "$root/linux/test_slam_pipeline.cc" -L"$slam/lib" -L"$install/lib" \
    -Wl,-rpath,"$slam/lib:$install/lib" -lORB_SLAM3 -lopencv_core -lopencv_features2d \
    -o "$output/test-slam-pipeline"
export LD_LIBRARY_PATH="$install/lib:$slam/lib:${LD_LIBRARY_PATH:-}"
python3 "$root/linux/test_slam_pipeline.py" --driver "$output/test-slam-pipeline"
