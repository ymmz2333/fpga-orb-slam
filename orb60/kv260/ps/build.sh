#!/usr/bin/env bash
set -euo pipefail
src="$(cd "${1:?Usage: build.sh SLAM_SOURCE [BUILD_DIR]}" && pwd)"
build="${2:-$src/build_kv260}"
test "$(uname -m)" = aarch64 || { echo 'Native KV260 AArch64 build required' >&2; exit 2; }
cmake -S "$src" -B "$build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$build" --target mono_kv260 --parallel 1
test -x "$build/bin/mono_kv260"
sha256sum "$build/bin/mono_kv260" "$build/lib/libORB_SLAM3.so"
