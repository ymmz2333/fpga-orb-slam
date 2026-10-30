#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
python3 "$experiment_root/scripts/make_smoke_sequence.py"
source_root="$experiment_root/vendor/ORB_SLAM3"
input="$experiment_root/runtime/smoke_input"
output="$experiment_root/runtime/smoke_a1_${1:-1}"
if [[ -e "$output" ]]; then
    echo "Refusing to reuse smoke output: $output" >&2
    exit 1
fi
mkdir "$output"
cd "$output"
unset DISPLAY
run_logged "a1-smoke-${1:-1}" timeout 120 "$source_root/Examples/Monocular/mono_euroc" \
    "$source_root/Vocabulary/ORBvoc.txt" "$input/smoke.yaml" "$input" "$input/timestamps.txt" \
    smoke --no-viewer
python3 "$experiment_root/scripts/verify_smoke.py" "$output"
