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
scratch=$(mktemp -d "$scratch_root/slam60-retrieval-test.XXXXXX")
./bin/test-zslam "$scratch" > "$release/selftest.log" 2>&1
tail -n 16 "$release/selftest.log"
tar -czf "$release/cpu-selftest-output.tar.gz" -C "$scratch" .
case "$scratch" in "$scratch_root"/slam60-retrieval-test.*) ;; *) exit 1;; esac
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
        --no-trajectory-cache --output "$run" "$@" > "$run.log" 2>&1
    cat "$run/run.json" "$run/display.json"
}
run_test legacy-sd /opt/zynq-slam/data/video_inputs_20261023/gray8.bin 2273 --legacy-retrieval-invalidation
run_test precise-sd /opt/zynq-slam/data/video_inputs_20261023/gray8.bin 2273 --precise-retrieval-invalidation
tmp_free=$(df -k /tmp | awk 'NR==2 {print $4}')
mem_available=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
if test "$tmp_free" -lt 190000 || test "$mem_available" -lt 190000; then
    echo "RESIDENT_TEST_NOT_RUN_MEMORY tmp_free_kib=$tmp_free available_kib=$mem_available"
    exit 0
fi
#240 unique original frames, unchanged30Hz identity. Extra158MiB is only
# diagnostic input RAM, not production RSS or physical-camera acceptance.
resident=$(mktemp /tmp/slam60-retrieval-resident240.XXXXXX)
dd if=/opt/zynq-slam/data/video_inputs_20261023/gray8.bin of="$resident" bs=691200 count=240 2> "$release/resident-copy.log"
test "$(wc -c < "$resident")" = 165888000
run_test legacy-resident240 "$resident" 240 --legacy-retrieval-invalidation
run_test precise-resident240 "$resident" 240 --precise-retrieval-invalidation
echo RETRIEVAL_AB_COMPLETED_BASELINE_WILL_RESUME
