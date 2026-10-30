#!/bin/sh
# Compare exact JPEG paths; full RAW golden regression uses frozen3000/16 bounds.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin; export PATH
release=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
case "$release" in /opt/zynq-slam/experiments/*) ;; *) exit 1;; esac
baseline=/opt/zynq-slam/releases/sd_ssh_20261024_001751
test "$(readlink -f /opt/zynq-slam/current)" = "$baseline"
test -c /dev/video0; test -c /dev/uio0
test "$(cat /sys/class/uio/uio0/version)" = wc1
test -x /usr/bin/time
cd "$release"
sha256sum -c SHA256SUMS
if ps w | grep '[b]in/zynq-slam.*experiments'; then exit 1; fi
lock=/run/zslam-usb-camera-bench.lock
mkdir "$lock"; stopped=0; pl_active=0
restore() {
    rc=$?; trap - EXIT HUP INT TERM; rmdir "$lock"
    if test "$stopped" = 1; then
        if test "$rc" != 0 && test "$pl_active" = 1; then
            echo 'PL_RUN_FAILED; reboot preserved SD' >&2; sync; /sbin/reboot
        else sh "$baseline/scripts/zslamctl.sh" start; fi
    fi
    exit "$rc"
}
trap restore EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
chmod 755 bin/zynq-slam bin/test-zslam
scratch_root=$(readlink -f /tmp)
scratch=$(mktemp -d "$scratch_root/zslam-region-selftest.XXXXXX")
./bin/test-zslam "$scratch" < /dev/null > selftest.log 2>&1
tar -czf cpu-selftest-output.tar.gz -C "$scratch" .
case "$scratch" in "$scratch_root"/zslam-region-selftest.*) ;; *) exit 1;; esac
test "$(readlink -f "$scratch")" = "$scratch"
rm -r -- "$scratch"
sh "$baseline/scripts/zslamctl.sh" status | grep '^RUNNING'
stopped=1; sh "$baseline/scripts/zslamctl.sh" stop
for mode in full region; do
    if test "$mode" = full; then option=--full-jpeg-decode; else option=--jpeg-region-decode; fi
    /usr/bin/time -v ./bin/zynq-slam --camera /dev/video0 --camera-format mjpeg --camera-width 1280 --camera-height 720 \
        --target-fps 30 --capture-only --frames 600 "$option" --output "$release/capture-$mode" \
        < /dev/null > "capture-$mode.log" 2>&1
    cat "capture-$mode/camera.json"
done
pl_active=1
/usr/bin/time -v ./bin/zynq-slam --raw /opt/zynq-slam/data/video_inputs_20261023/gray8.bin \
    --uio /dev/uio0 --hdmi-uio /dev/uio0 --target-fps 30 --frames 2273 --max-points 3000 --max-keyframes 16 \
    --calibration config/camera_handoff.csv --import-map /opt/zynq-slam/data/handoff_map_20261023 \
    --verify-golden /opt/zynq-slam/data/arm_replay_20261023_195434 --output "$release/raw-regression" \
    < /dev/null > raw-regression.log 2>&1
pl_active=0
cat raw-regression/run.json raw-regression/display.json
echo 'REGION_EXPERIMENT_COMPLETED: camera capture and recorded RAW tests; live SLAM calibration still pending'
