#!/usr/bin/env bash
set -euo pipefail
experiment_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
jobs="${BUILD_JOBS:-2}"
install_prefix="$experiment_root/install"
mkdir -p "$experiment_root/logs" "$experiment_root/build" "$install_prefix" "$experiment_root/runtime"
export CMAKE_PREFIX_PATH="$install_prefix${CMAKE_PREFIX_PATH:+:$CMAKE_PREFIX_PATH}"
export LD_LIBRARY_PATH="$install_prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
run_logged() {
    local label="$1"
    shift
    printf '[%s] %s\n' "$(date -Is)" "$label"
    "$@" 2>&1 | tee "$experiment_root/logs/$label.log"
}
