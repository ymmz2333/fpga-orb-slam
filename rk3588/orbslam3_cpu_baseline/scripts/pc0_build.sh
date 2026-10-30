#!/usr/bin/env bash
# Generated WSL build checkout; authoritative scripts and patches remain on D:\pld.
source "$(dirname -- "$0")/common.sh"
[[ "$(uname -m)" == x86_64 ]]
[[ "$(gcc -dumpfullversion)" == 9.4.0 ]]
[[ "$(g++ -dumpfullversion)" == 9.4.0 ]]
bundle="${1:?Supply the PC-local bundle read from the existing B2 repository}"
expected=d3e50c03fc194272c70cb482fd807a025cf7a5cf
source_root="$experiment_root/vendor/ORB_SLAM3"
mkdir -p "$experiment_root/vendor"
if [[ ! -d "$source_root/.git" ]]; then
    run_logged pc-orb-clone git clone "$bundle" "$source_root"
    git -C "$source_root" checkout -b pc/b3-base "$expected"
fi
[[ "$(git -C "$source_root" rev-parse HEAD)" == "$expected" ]]
git -C "$source_root" diff --exit-code
if [[ ! -d "$experiment_root/vendor/opencv/.git" ]]; then
    run_logged pc-opencv-clone git clone --depth 1 --branch 4.5.5 https://github.com/opencv/opencv.git "$experiment_root/vendor/opencv"
fi
[[ "$(git -C "$experiment_root/vendor/opencv" describe --tags --exact-match)" == 4.5.5 ]]
if [[ ! -d "$experiment_root/vendor/Pangolin/.git" ]]; then
    run_logged pc-pangolin-clone git clone --depth 1 --branch v0.8 https://github.com/stevenlovegrove/Pangolin.git "$experiment_root/vendor/Pangolin"
fi
[[ "$(git -C "$experiment_root/vendor/Pangolin" describe --tags --exact-match)" == v0.8 ]]
run_logged pc-opencv bash "$experiment_root/scripts/build_opencv.sh"
run_logged pc-pangolin bash "$experiment_root/scripts/build_pangolin.sh"
run_logged pc-orb bash "$experiment_root/scripts/build_orbslam3.sh"
reference="$experiment_root/runtime/b2/original_reference"
mkdir -p "$reference/include" "$reference/src"
for path in include/ORBextractor.h src/ORBextractor.cc; do
    git -C "$source_root" show "de62fc00196dc286b5a61b8a1cee57a8cdb6b7c4:$path" > "$reference/$path"
done
for profile in corrected legacy; do
    upper=1000; [[ "$profile" != legacy ]] || upper=0
    run_logged "pc-candidates-$profile-configure" cmake -S "$experiment_root/tools/b2_candidates" \
        -B "$experiment_root/build/b2_candidates_$profile" -DCMAKE_BUILD_TYPE=Release \
        -DORB_SOURCE="$source_root" -DORB_REFERENCE="$reference" \
        -DORB_CANDIDATE_LAPPING_UPPER="$upper" -DOpenCV_DIR="$install_prefix/lib/cmake/opencv4"
    run_logged "pc-candidates-$profile-build" cmake --build "$experiment_root/build/b2_candidates_$profile" --parallel "$jobs"
done
python3 "$experiment_root/scripts/record_pc_environment.py" --output "$experiment_root/runtime/pc/environment"
echo 'PC0_BUILD_PASS; PC1/P2/P3 and B3 have not run'
