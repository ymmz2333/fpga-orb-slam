#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
source_root="$experiment_root/vendor/ORB_SLAM3"
reference="$experiment_root/runtime/b2/original_reference"
mkdir -p "$reference/include" "$reference/src"
# C1 accepted source is the independent, unmodified feature reference.
base="$(git -C "$source_root" rev-parse c1/tello-observability)"
for path in include/ORBextractor.h src/ORBextractor.cc; do
    git -C "$source_root" show "$base:$path" > "$reference/$path"
done
printf '%s\n' "$base" > "$reference/commit.txt"
sha256sum "$source_root/Examples/Monocular/mono_euroc" "$source_root/lib/libORB_SLAM3.so" > "$experiment_root/logs/b2_slam_before.sha256"
if git -C "$source_root" show-ref --verify --quiet refs/heads/b2/design-candidates; then
    git -C "$source_root" checkout b2/design-candidates
else
    git -C "$source_root" checkout -b b2/design-candidates "$base"
fi
patch="$experiment_root/patches/0011-orb-design-candidate-extractor.patch"
if ! git -C "$source_root" apply --reverse --check "$patch" 2>/dev/null; then
    git -C "$source_root" diff --exit-code "$base" -- include/ORBextractor.h src/ORBextractor.cc src/FeatureIO.cc
    git -C "$source_root" apply --check "$patch"
    git -C "$source_root" apply "$patch"
    git -C "$source_root" add include/ORBextractor.h src/ORBextractor.cc
    git -C "$source_root" -c user.name='RK3588 Baseline' -c user.email='rk3588-baseline@local' \
        commit -m 'B2: add configurable ORB design candidate rules for standalone producer'
fi
run_logged b2-configure cmake -S "$experiment_root/tools/b2_candidates" -B "$experiment_root/build/b2_candidates" \
    -DCMAKE_BUILD_TYPE=Release -DORB_SOURCE="$source_root" -DORB_REFERENCE="$reference" \
    -DOpenCV_DIR="$install_prefix/lib/cmake/opencv4"
run_logged b2-build cmake --build "$experiment_root/build/b2_candidates" -j 1
sha256sum -c "$experiment_root/logs/b2_slam_before.sha256"
ldd "$experiment_root/build/b2_candidates/orb_candidates" > "$experiment_root/logs/b2_ldd.txt"
! grep -E 'opencv.*4\.2|not found' "$experiment_root/logs/b2_ldd.txt"
mkdir -p "$experiment_root/runtime/b2/fixture"
"$experiment_root/build/b2_candidates/candidate_fixture" "$experiment_root/runtime/b2/fixture"
python3 "$experiment_root/scripts/check_b2_fixture.py" "$experiment_root/runtime/b2/fixture"
printf 'B2_BUILD_PASS: independent producer only; accepted SLAM binary hashes unchanged\n'
