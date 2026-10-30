#!/bin/sh
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
release=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
baseline=/opt/zynq-slam/releases/sd_ssh_20261024_001751
cd "$release"
sha256sum -c SHA256SUMS
chmod 755 bin/*
scratch_root=$(readlink -f /tmp)
case "$scratch_root" in /*) ;; *) exit 1;; esac
scratch=$(mktemp -d "$scratch_root/slam60-trajectory-test.XXXXXX")
./bin/test-zslam "$scratch" > "$release/selftest.log" 2>&1
tail -n 15 "$release/selftest.log"
# Retain synthetic self-test evidence on SD, free this run's temporary RAM.
tar -czf "$release/cpu-selftest-output.tar.gz" -C "$scratch" .
case "$scratch" in "$scratch_root"/slam60-trajectory-test.*) ;; *) exit 1;; esac
test "$(readlink -f "$scratch")" = "$scratch"
rm -r -- "$scratch"
resident=
restore() {
    rc=$?;trap - EXIT HUP INT TERM
    if test -n "$resident"; then rm -f -- "$resident";fi
    if test "$rc" = 0; then sh "$baseline/scripts/zslamctl.sh" start
    else echo 'EXPERIMENT_FAILED; rebooting preserved baseline' >&2;sync;/sbin/reboot;fi
}
trap restore EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
sh "$baseline/scripts/zslamctl.sh" stop
run_test() {
    run=$release/$1;input=$2;frames=$3;shift 3
    ./bin/zynq-slam --raw "$input" --uio /dev/uio0 --hdmi-uio /dev/uio0 \
        --calibration config/camera_handoff.csv --import-map /opt/zynq-slam/data/handoff_map_20261023 \
        --verify-golden /opt/zynq-slam/data/arm_replay_20261023_195434 --target-fps 60 \
        --orb-poll-us 50 --max-points 3000 --max-keyframes 16 --frames "$frames" \
        --output "$run" "$@" > "$run.log" 2>&1
    cat "$run/run.json" "$run/display.json"
}
run_test trajectory-off-sd /opt/zynq-slam/data/video_inputs_20261023/gray8.bin 2273 --no-trajectory-cache
run_test trajectory-on-sd /opt/zynq-slam/data/video_inputs_20261023/gray8.bin 2273 --trajectory-cache
tmp_free=$(df -k /tmp | awk 'NR==2 {print $4}')
mem_available=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
if test "$tmp_free" -lt 190000 || test "$mem_available" -lt 190000; then
    echo "RESIDENT_TEST_NOT_RUN_MEMORY tmp_free_kib=$tmp_free available_kib=$mem_available"
    exit 0
fi
#240 unique original frames once; unchanged30Hz identity/time. Extra158MiB
# test-input RAM is separate from the production application's RSS/mapping.
resident=$(mktemp /tmp/slam60-trajectory-resident240.XXXXXX)
dd if=/opt/zynq-slam/data/video_inputs_20261023/gray8.bin of="$resident" bs=691200 count=240 2> "$release/resident-copy.log"
test "$(wc -c < "$resident")" = 165888000
run_test trajectory-off-resident240 "$resident" 240 --no-trajectory-cache
run_test trajectory-on-resident240 "$resident" 240 --trajectory-cache
echo TRAJECTORY_AB_COMPLETED_BASELINE_WILL_RESUME
