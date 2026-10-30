#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
pangolin_source="${PANGOLIN_SOURCE_DIR:-$experiment_root/vendor/Pangolin}"
run_logged pangolin-configure cmake -S "$pangolin_source" -B "$experiment_root/build/Pangolin" \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$install_prefix" \
    -DBUILD_EXAMPLES=OFF -DBUILD_TOOLS=OFF -DBUILD_PANGOLIN_PYTHON=OFF -DBUILD_TESTS=OFF
run_logged pangolin-build cmake --build "$experiment_root/build/Pangolin" --parallel "$jobs"
run_logged pangolin-install cmake --install "$experiment_root/build/Pangolin"
