#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
export ORB_PHASE=b1
bash "$experiment_root/scripts/apply_patches.sh"
source_root="$experiment_root/vendor/ORB_SLAM3"
run_logged b1-configure cmake -S "$source_root" -B "$source_root/build" \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="$install_prefix" \
    -DOpenCV_DIR="$install_prefix/lib/cmake/opencv4" -DPangolin_DIR="$install_prefix/lib/cmake/Pangolin"
run_logged b1-build cmake --build "$source_root/build" --target mono_euroc feature_io_check --parallel "$jobs"
