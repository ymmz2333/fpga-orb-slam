#!/usr/bin/env bash
set -euo pipefail
project="$(cd -- "$(dirname -- "$0")/.." && pwd)"
output="$project/install-demo/lib"
build="$project/runtime/gtk-plugin-build"
mkdir -p "$output" "$build"
# Official standalone plugin: one GTK source; existing OpenCV libraries untouched.
cmake -S "$project/vendor/opencv/modules/highgui/misc/plugins/plugin_gtk" -B "$build" \
    -DCMAKE_BUILD_TYPE=Release -DOPENCV_PLUGIN_NAME=opencv_highgui_gtk3 \
    -DOPENCV_PLUGIN_DESTINATION="$output" -DWITH_GTK_2_X=OFF
cmake --build "$build" --parallel 2
test -f "$output/libopencv_highgui_gtk3.so"
sha256sum "$output/libopencv_highgui_gtk3.so"
echo GTK_PLUGIN_BUILD_PASS
