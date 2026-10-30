#!/bin/sh
# Temporary experiment only; optional first argument is THIS camera's source-size calibration CSV.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
release=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
case "$release" in /opt/zynq-slam/experiments/*) ;; *) echo 'Refuse benchmark outside experiments' >&2; exit 1;; esac
baseline=/opt/zynq-slam/releases/sd_ssh_20261024_001751
test "$(readlink -f /opt/zynq-slam/current)" = "$baseline"
test -c /dev/video0
test -c /dev/uio0
test "$(cat /sys/class/uio/uio0/version)" = wc1
cd "$release"
sha256sum -c SHA256SUMS
chmod 755 bin/zynq-slam bin/test-zslam
if ps w | grep '[b]in/zynq-slam.*experiments'; then echo 'Another software experiment is active' >&2;exit 1;fi
# Do not overlap any other experiment, even a CPU-only camera benchmark.
lock=/run/zslam-usb-camera-bench.lock
mkdir "$lock"
stopped=0
pl_active=0
restore() {
    rc=$?;trap - EXIT HUP INT TERM
    rmdir "$lock"
    if test "$stopped" = 1; then
        if test "$rc" != 0 && test "$pl_active" = 1; then
            echo 'PL_RUN_FAILED; rebooting preserved SD baseline' >&2;sync;/sbin/reboot
        else sh "$baseline/scripts/zslamctl.sh" start;fi
    fi
    exit "$rc"
}
trap restore EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
scratch_root=$(readlink -f /tmp)
scratch=$(mktemp -d "$scratch_root/zslam-camera-selftest.XXXXXX")
./bin/test-zslam "$scratch" > selftest.log 2>&1
tar -czf cpu-selftest-output.tar.gz -C "$scratch" .
case "$scratch" in "$scratch_root"/zslam-camera-selftest.*) ;; *) exit 1;; esac
test "$(readlink -f "$scratch")" = "$scratch"
rm -r -- "$scratch"
sh "$baseline/scripts/zslamctl.sh" status | grep '^RUNNING'
stopped=1
sh "$baseline/scripts/zslamctl.sh" stop
./bin/zynq-slam --camera /dev/video0 --camera-format mjpeg --camera-width 1280 --camera-height 720 \
    --target-fps 30 --capture-only --frames 600 --output "$release/capture" < /dev/null > capture.log 2>&1
cat capture/camera.json
if test "$#" = 0; then
    echo 'CAMERA_CAPTURE_ONLY_COMPLETED; full SLAM requires calibration of this camera'
    exit 0
fi
test "$#" = 1
test -f "$1"
# Retain raw-input/PL identity regression separately from lossy MJPEG input.
pl_active=1
./bin/zynq-slam --raw /opt/zynq-slam/data/video_inputs_20261023/gray8.bin \
    --uio /dev/uio0 --hdmi-uio /dev/uio0 --target-fps 30 --frames 2273 --max-points 3000 --max-keyframes 16 \
    --calibration config/camera_handoff.csv --import-map /opt/zynq-slam/data/handoff_map_20261023 \
    --verify-golden /opt/zynq-slam/data/arm_replay_20261023_195434 \
    --output "$release/raw-regression" < /dev/null > raw-regression.log 2>&1
./bin/zynq-slam --camera /dev/video0 --camera-format mjpeg --camera-width 1280 --camera-height 720 \
    --calibration "$1" --target-fps 30 --uio /dev/uio0 --hdmi-uio /dev/uio0 \
    --frames 1800 --max-points 3000 --max-keyframes 16 --log-rows 3600 --log-keep 3 \
    --output "$release/live" < /dev/null > live.log 2>&1
pl_active=0
cat live/camera.json live/run.json live/display.json
echo 'USB_CAMERA_EXPERIMENT_COMPLETED; inspect throughput/gaps/latency/mapping quality before acceptance'
