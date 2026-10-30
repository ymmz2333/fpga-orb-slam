#!/bin/sh
# User requested camera-only operation. Never fall back to a recorded demo.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin; export PATH
release=/opt/zynq-slam/experiments/slam60_camera_20261024_180726
baseline=/opt/zynq-slam/releases/sd_ssh_20261024_001751
cd "$release"
test "$(readlink -f /opt/zynq-slam/current)" = "$baseline"
test -c /dev/video0; test -c /dev/input/event0
test "$(cat /sys/class/uio/uio0/version)" = wc1
sha256sum -c SHA256SUMS
sha256sum -c s1-controls/SHA256SUMS
./s1-controls/s1-reset-bridge --selftest
test ! -e camera-s1
lock=/run/zslam-usb-camera-bench.lock
mkdir "$lock"; child=; bridge=; rc=0
cleanup() {
 code=$?; trap - EXIT HUP INT TERM
 if test -n "$bridge"; then kill -TERM "$bridge" 2>/dev/null || :; wait "$bridge" 2>/dev/null || :; fi
 if test -n "$child"; then kill -TERM "$child" 2>/dev/null || :; wait "$child" 2>/dev/null || :; fi
 rm -f "$lock/child.pid" "$lock/bridge.pid"; rmdir "$lock"
 echo 'CAMERA_ONLY_STOPPED; recorded baseline remains stopped by user request'
 if test "$code" != 0; then touch camera-s1/STOPPED_REQUIRES_INSPECTION; fi
 exit "$code"
}
trap cleanup EXIT
trap 'exit 143' HUP INT TERM
mkdir camera-s1; mkfifo -m 600 camera-s1/control.fifo
printf '%s\n' "$0" > camera-s1/controller.txt
sh "$baseline/scripts/zslamctl.sh" stop
exec 3<>camera-s1/control.fifo
./bin/zynq-slam --camera /dev/video0 --camera-format mjpeg --camera-width 1280 --camera-height 720 --calibration "$release/q12_calibration/camera_source.csv" --target-fps 30 --uio /dev/uio0 --hdmi-uio /dev/uio0 --frames 0 --max-points 3000 --max-keyframes 16 --log-rows 3600 --log-keep 3 --snapshot --save "$release/camera-s1/run/map.zmap" --output "$release/camera-s1/run" <&3 > /dev/null 2>camera-s1/app.stderr &
child=$!; printf '%s\n' "$child" > "$lock/child.pid"; printf '%s\n' "$child" > camera-s1/app.pid
n=0
while :; do
 count=0; target=; candidates=0
 for status in /proc/"$child"/task/*/status; do
  test -f "$status" || continue
  count=$((count+1)); tid=${status%/status}; tid=${tid##*/}; mask=$(awk '/^Cpus_allowed_list:/ {print $2}' "$status")
  if test "$tid" != "$child" && test "$mask" = 0; then target=$tid; candidates=$((candidates+1)); fi
 done
 if test "$count" = 4 && test "$candidates" = 1; then break; fi
 n=$((n+1)); test "$n" -le 40; kill -0 "$child"; sleep 0.05
done
./s1-controls/capture-affinity --set-capture "$child" "$target" > camera-s1/capture-affinity.json
./s1-controls/s1-reset-bridge /dev/input/event0 "$release/camera-s1/control.fifo" "$release/camera-s1/reset-status.json" > /dev/null 2>camera-s1/key.stderr &
bridge=$!; printf '%s\n' "$bridge" > "$lock/bridge.pid"; printf '%s\n' "$bridge" > camera-s1/bridge.pid
n=0
while test ! -s camera-s1/reset-status.json; do n=$((n+1)); test "$n" -le 30; kill -0 "$bridge"; sleep 0.1; done
echo 'LIVE_CAMERA_S1_READY; S1 clears map/trajectory, no recorded playback'
# A key-reader failure stops this session for inspection rather than silently
# advertising a reset key that no longer works. CPU/PL faults are not restarted.
while kill -0 "$child" 2>/dev/null; do
 if ! kill -0 "$bridge" 2>/dev/null; then echo 'S1_READER_FAILED' >&2; exit 1; fi
 sleep 1
done
wait "$child" || rc=$?; child=
exit "$rc"
