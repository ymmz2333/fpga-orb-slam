#!/bin/sh
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
release=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
baseline=/opt/zynq-slam/releases/sd_ssh_20261024_001751
cd "$release"
sha256sum -c SHA256SUMS
chmod 755 bin/*
scratch=$(mktemp -d /tmp/slam60-render-test.XXXXXX)
./bin/test-zslam "$scratch" > "$release/selftest.log" 2>&1
tail -n 10 "$release/selftest.log"
sh "$baseline/scripts/zslamctl.sh" stop
restore() {
    rc=$?;trap - EXIT INT TERM
    if test "$rc" = 0; then sh "$baseline/scripts/zslamctl.sh" start
    else echo 'EXPERIMENT_FAILED; rebooting preserved baseline' >&2;sync;/sbin/reboot;fi
}
trap restore EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# First a complete unique physical sequence, then a short RAM-input compute test.
# RAM test uses the first 240 distinct frames once, original30Hz timestamps.
# The 158MiB tmpfs input is not a camera or a production memory footprint.
run=$release/async-sd
./bin/zynq-slam --raw /opt/zynq-slam/data/video_inputs_20261023/gray8.bin \
    --uio /dev/uio0 --hdmi-uio /dev/uio0 --calibration config/camera_handoff.csv \
    --import-map /opt/zynq-slam/data/handoff_map_20261023 \
    --verify-golden /opt/zynq-slam/data/arm_replay_20261023_195434 \
    --target-fps 60 --orb-poll-us 50 --max-points 3000 --max-keyframes 16 \
    --frames 2273 --output "$run" > "$release/async-sd.log" 2>&1
cat "$run/run.json" "$run/display.json"
tmp_free=$(df -k /tmp | awk 'NR==2 {print $4}')
mem_available=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
if test "$tmp_free" -lt 190000 || test "$mem_available" -lt 190000; then
    echo "RESIDENT_TEST_NOT_RUN_MEMORY tmp_free_kib=$tmp_free available_kib=$mem_available"
    exit 0
fi
resident=$(mktemp /tmp/slam60-resident240.XXXXXX)
dd if=/opt/zynq-slam/data/video_inputs_20261023/gray8.bin of="$resident" bs=691200 count=240 2> "$release/resident-copy.log"
test "$(wc -c < "$resident")" = 165888000
for mode in sync async; do
    set --
    test "$mode" != sync || set -- --sync-ui
    run=$release/$mode-resident240
    ./bin/zynq-slam --raw "$resident" --uio /dev/uio0 --hdmi-uio /dev/uio0 \
        --calibration config/camera_handoff.csv --import-map /opt/zynq-slam/data/handoff_map_20261023 \
        --verify-golden /opt/zynq-slam/data/arm_replay_20261023_195434 --target-fps 60 \
        --orb-poll-us 50 --max-points 3000 --max-keyframes 16 --frames 240 \
        --output "$run" "$@" > "$release/$mode-resident240.log" 2>&1
    cat "$run/run.json" "$run/display.json"
done
rm -f -- "$resident"
echo RENDER_AB_COMPLETED_BASELINE_WILL_RESUME
