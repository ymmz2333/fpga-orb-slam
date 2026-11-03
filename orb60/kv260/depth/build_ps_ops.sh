#!/usr/bin/env bash
set -euo pipefail
root=$(realpath "${1:?PROJECT_ROOT required}")
run=$(realpath -m "${2:?FRESH_RUN_DIRECTORY required}")
test ! -e "$run"
test "$(uname -m)" = aarch64
mkdir -p "$run"
source_dir=$(cd "$(dirname "$0")/ps_ops" && pwd)
cd "$root/sources"
bash orb60/kv260/depth/runtime_exec.sh "$root" python -m orb60.kv260.depth.ps_ops.prepare "$root" "$run/policy"
cmake -S "$source_dir" -B "$root/build_vai25/ps_ops" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$root/runtime_vai25" -DKV_RUNTIME="$root/runtime_vai25" \
    -DKV_POLICY_DIR="$run/policy" > "$run/configure.log" 2>&1
cmake --build "$root/build_vai25/ps_ops" --parallel 1 > "$run/build.log" 2>&1
cmake --install "$root/build_vai25/ps_ops" > "$run/install.log" 2>&1
sha256sum "$root/runtime_vai25/lib/libvart_op_imp_relu.so" > "$run/plugin_sha256.txt"
