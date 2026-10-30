#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
status_file="$experiment_root/logs/a1-runtime-runs.csv"
suite="${1:-$(date -u +%Y%m%dT%H%M%S)_$$}"
[[ "$suite" =~ ^[A-Za-z0-9_-]+$ ]] || { echo 'Invalid suite ID' >&2; exit 2; }
printf 'run,check,exit_code,status,smoke_id\n' > "$status_file"
for run in 1 2 3 4 5; do
    smoke_id="${suite}_${run}"
    set +e
    "$install_prefix/bin/opencv_version" > "$experiment_root/logs/opencv-final-version-$run.log" 2>&1
    version_exit=$?
    "$experiment_root/runtime/opencv_runtime_probe" parser > "$experiment_root/logs/opencv-final-parser-$run.log" 2>&1
    parser_exit=$?
    (cd "$experiment_root/runtime" && ./opencv_runtime_probe) > "$experiment_root/logs/opencv-final-image-orb-$run.log" 2>&1
    image_exit=$?
    bash "$experiment_root/scripts/smoke_a1.sh" "$smoke_id" > "$experiment_root/logs/a1-smoke-$smoke_id-driver.log" 2>&1
    smoke_exit=$?
    set -e
    for pair in "opencv_version:$version_exit" "opencv_parser:$parser_exit" "opencv_image_orb:$image_exit" "mono_euroc_synthetic:$smoke_exit"; do
        label="${pair%:*}"
        code="${pair##*:}"
        result=FAIL
        [[ "$code" == 0 ]] && result=PASS
        printf '%s,%s,%s,%s,%s\n' "$run" "$label" "$code" "$result" "$smoke_id" | tee -a "$status_file"
    done
done
cp "$status_file" "$experiment_root/logs/a1-runtime-runs-$suite.csv"
if grep -q ',FAIL$' "$status_file"; then
    echo 'A1 runtime verification failed; inspect per-run logs.' >&2
    exit 1
fi
echo 'A1_FIVE_RUNTIME_RUNS_PASS'
