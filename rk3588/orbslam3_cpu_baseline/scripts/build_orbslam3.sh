#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
source_root="$experiment_root/vendor/ORB_SLAM3"
for dependency in DBoW2 g2o Sophus; do
    run_logged "orb-$dependency-configure" cmake -S "$source_root/Thirdparty/$dependency" \
        -B "$source_root/Thirdparty/$dependency/build" -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_PREFIX_PATH="$install_prefix" -DOpenCV_DIR="$install_prefix/lib/cmake/opencv4"
    run_logged "orb-$dependency-build" cmake --build "$source_root/Thirdparty/$dependency/build" --parallel "$jobs"
done
if [[ ! -f "$source_root/Vocabulary/ORBvoc.txt" ]]; then
    run_logged orb-vocabulary tar -xzf "$source_root/Vocabulary/ORBvoc.txt.tar.gz" -C "$source_root/Vocabulary"
fi
run_logged orb-configure cmake -S "$source_root" -B "$source_root/build" \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="$install_prefix" \
    -DOpenCV_DIR="$install_prefix/lib/cmake/opencv4" -DPangolin_DIR="$install_prefix/lib/cmake/Pangolin"
run_logged orb-build cmake --build "$source_root/build" --target mono_euroc --parallel "$jobs"
