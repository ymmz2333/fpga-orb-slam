#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
label="${1:?unique diagnostic ID required}"
[[ "$label" =~ ^[A-Za-z0-9_-]+$ ]] || exit 2
base="$experiment_root/runtime/c/compiler_diagnostics/$label"
[[ ! -e "$base" ]] || { echo 'Refusing reused diagnostic directory'; exit 2; }
mkdir -p "$base"
repo="$experiment_root/vendor/ORB_SLAM3"
for item in a2 c1; do
    if [[ "$item" == a2 ]]; then ref=cf36b062177b6a14d7f8e120411c9ef491f65c84; else ref=c1/tello-observability; fi
    tree="$base/$item-source"
    git -C "$repo" worktree add -b "diag/$label-$item" "$tree" "$ref" > "$base/$item-worktree.log" 2>&1
    mkdir -p "$tree/Thirdparty/DBoW2/lib" "$tree/Thirdparty/g2o/lib"
    cp "$repo/Thirdparty/DBoW2/lib/libDBoW2.so" "$tree/Thirdparty/DBoW2/lib/"
    git -C "$tree" rev-parse HEAD > "$base/$item-commit.txt"
    cmake -S "$tree" -B "$base/$item-build" -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_C_COMPILER=/usr/bin/gcc -DCMAKE_CXX_COMPILER=/usr/bin/g++ \
        -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DCMAKE_PREFIX_PATH="$install_prefix" \
        -DOpenCV_DIR="$install_prefix/lib/cmake/opencv4" -DPangolin_DIR="$install_prefix/lib/cmake/Pangolin" \
        > "$base/$item-configure.log" 2>&1
    set +e
    python3 "$experiment_root/scripts/measure_compile.py" --output "$base/$item-g2o-measurement" \
        -- cmake --build "$base/$item-build" --target g2o --parallel 1
    code=$?
    set -e
    if (( code != 0 )); then echo "DIAGNOSTIC_STOP $item g2o compile failed; inspect environment before more builds"; exit "$code"; fi
    set +e
    python3 "$experiment_root/scripts/measure_compile.py" --output "$base/$item-measurement" \
        -- cmake --build "$base/$item-build" --target mono_euroc --parallel 1
    code=$?
    set -e
    if (( code != 0 )); then echo "DIAGNOSTIC_STOP $item compile failed; inspect environment before more builds"; exit "$code"; fi
done
echo 'OLD_AND_NEW_GCC9_SERIAL_BUILD_PASS'
