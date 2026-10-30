#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
run_logged opencv-probe-build g++ -std=c++14 -O2 -g \
    -I"$install_prefix/include/opencv4" "$experiment_root/scripts/opencv_runtime_probe.cc" \
    -L"$install_prefix/lib" -Wl,-rpath,"$install_prefix/lib" \
    -lopencv_features2d -lopencv_imgcodecs -lopencv_imgproc -lopencv_core \
    -o "$experiment_root/runtime/opencv_runtime_probe"
cd "$experiment_root/runtime"
set +e
./opencv_runtime_probe > "$experiment_root/logs/opencv-image-orb-probe.log" 2>&1
image_exit=$?
./opencv_runtime_probe parser > "$experiment_root/logs/opencv-parser-probe.log" 2>&1
parser_exit=$?
printf 'probe,exit_code\nimage_orb,%s\nparser,%s\n' "$image_exit" "$parser_exit" | tee "$experiment_root/logs/opencv-runtime-probe.csv"
cat "$experiment_root/logs/opencv-image-orb-probe.log" "$experiment_root/logs/opencv-parser-probe.log"
[[ "$image_exit" == 0 && "$parser_exit" == 0 ]]
