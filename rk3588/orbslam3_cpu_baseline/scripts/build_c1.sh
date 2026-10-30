#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
export ORB_PHASE=c1
source_root="$experiment_root/vendor/ORB_SLAM3"
if git -C "$source_root" show-ref --verify --quiet refs/heads/c1/tello-observability; then
    # Reuse the committed C1 source. Earlier patches no longer reverse-apply
    # cleanly once B1/C1 have changed their inserted lines.
    git -C "$source_root" checkout c1/tello-observability
    git -C "$source_root" diff --exit-code HEAD --
else
    bash "$experiment_root/scripts/apply_patches.sh"
fi
git -C "$source_root" rev-parse HEAD > "$experiment_root/logs/c1-source-commit.txt"
run_logged c1-configure cmake -S "$source_root" -B "$source_root/build" \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="$install_prefix" \
    -DOpenCV_DIR="$install_prefix/lib/cmake/opencv4" -DPangolin_DIR="$install_prefix/lib/cmake/Pangolin"
# Do not use clean-first: g2o is a required runtime library and is also removed
# by that target. Build it explicitly before the application, retaining any
# valid objects from an interrupted build.
run_logged c1-g2o-build cmake --build "$source_root/build" --target g2o --parallel "$jobs"
run_logged c1-build cmake --build "$source_root/build" --target mono_euroc --parallel "$jobs"
strings "$source_root/Examples/Monocular/mono_euroc" > "$experiment_root/logs/c1-binary-strings.txt"
grep -q 'MapStateStats.csv' "$experiment_root/logs/c1-binary-strings.txt"
nm -D "$source_root/lib/libORB_SLAM3.so" | grep 'SaveMapDiagnostics' > "$experiment_root/logs/c1-symbols.txt"
