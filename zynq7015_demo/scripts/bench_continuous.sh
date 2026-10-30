#!/bin/sh
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
release=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
baseline=/opt/zynq-slam/releases/sd_ssh_20261024_001751
cd "$release"
sha256sum -c SHA256SUMS
chmod 755 bin/*
scratch=$(mktemp -d /tmp/slam60-continuous-test.XXXXXX)
./bin/test-zslam "$scratch" > "$release/selftest.log" 2>&1
tail -n 13 "$release/selftest.log"
# Missing camera fails before opening the paired PL device; baseline stays active.
if ./bin/zynq-slam --camera /dev/video-zslam-not-present --uio /dev/uio0 \
    --calibration config/camera_handoff.csv --output "$release/no-camera" > "$release/no-camera.log" 2>&1; then
    echo 'Missing camera unexpectedly accepted' >&2;exit 1
fi
grep -q 'Cannot open V4L2 camera' "$release/no-camera.log"
restore() {
    rc=$?;trap - EXIT HUP INT TERM
    if test "$rc" = 0; then sh "$baseline/scripts/zslamctl.sh" start
    else echo 'EXPERIMENT_FAILED; rebooting preserved baseline' >&2;sync;/sbin/reboot;fi
}
trap restore EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
sh "$baseline/scripts/zslamctl.sh" stop
./bin/zynq-slam --raw /opt/zynq-slam/data/video_inputs_20261023/gray8.bin \
    --uio /dev/uio0 --hdmi-uio /dev/uio0 --calibration config/camera_handoff.csv \
    --import-map /opt/zynq-slam/data/handoff_map_20261023 \
    --verify-golden /opt/zynq-slam/data/arm_replay_20261023_195434 \
    --target-fps 60 --orb-poll-us 50 --max-points 3000 --max-keyframes 16 \
    --frames 240 --log-rows 30 --log-keep 3 --output "$release/rotating240" \
    > "$release/rotating240.log" 2>&1
cat "$release/rotating240/run.json" "$release/rotating240/display.json"
test "$(find "$release/rotating240" -name 'timing.part*.csv' | wc -l)" = 3
test "$(find "$release/rotating240" -name 'trajectory.part*.csv' | wc -l)" = 3
echo CONTINUOUS_LOG_ROTATION_COMPLETED_BASELINE_WILL_RESUME
