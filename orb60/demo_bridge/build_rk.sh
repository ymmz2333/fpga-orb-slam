#!/bin/sh
# Run natively on RK3588 with the retained dependency environment. Never WSL.
set -eu
test "$#" = 2 || { echo 'Usage: build_rk.sh ISOLATED_SOURCE NEW_BUILD_DIRECTORY' >&2; exit 64; }
test "$(uname -m)" = aarch64 || { echo 'Use native RK3588 aarch64 Linux' >&2; exit 1; }
source_dir=$(CDPATH= cd -- "$1" && pwd)
mkdir -p "$2"
build_dir=$(CDPATH= cd -- "$2" && pwd)
test -f "$source_dir/DEMO_BRIDGE_SOURCE.json"
export CMAKE_BUILD_PARALLEL_LEVEL=1
cmake -S "$source_dir/Thirdparty/DBoW2" -B "$build_dir/dbow" -DCMAKE_BUILD_TYPE=Release
cmake --build "$build_dir/dbow" --parallel 1
cmake -S "$source_dir" -B "$build_dir" -DCMAKE_BUILD_TYPE=Release -DORB_SLAM3_REGISTER_TIMES=ON
cmake --build "$build_dir" --target g2o --parallel 1
cmake --build "$build_dir" --target mono_bridge --parallel 1
sha256sum "$build_dir/demo_bin/mono_bridge" "$source_dir/lib/libORB_SLAM3.so" > "$build_dir/DEMO_SHA256SUMS"
echo 'RK_BUILD_COMPLETED; actual camera/FPGA/handover acceptance still required'
