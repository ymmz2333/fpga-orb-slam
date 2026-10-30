#!/bin/sh
# Temporary HDMI camera focus aid. No intrinsics, ORB extraction or SLAM pose.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin; export PATH
release=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
case "$release" in /opt/zynq-slam/experiments/*) ;; *) exit 1;; esac
frames=${1:-3600}; shots=${2:-0}; every=${3:-30}; tag=${4:-focus-preview}
for value in "$frames" "$shots" "$every"; do case "$value" in ''|*[!0-9]*) exit 2;; esac; done
test "$frames" -ge 1; test "$frames" -le 18000
test "$shots" -le 60; test "$every" -ge 1; test "$every" -le 300
case "$tag" in ''|*[!a-zA-Z0-9_-]*) exit 2;; esac
test "${#tag}" -le 64
baseline=/opt/zynq-slam/releases/sd_ssh_20261024_001751
test "$(readlink -f /opt/zynq-slam/current)" = "$baseline"
test -c /dev/video0; test -c /dev/uio0
test "$(cat /sys/class/uio/uio0/version)" = wc1
cd "$release"
sha256sum -c SHA256SUMS
if ps w | grep '[b]in/zynq-slam.*experiments'; then exit 1; fi
test ! -e "$tag"
lock=/run/zslam-usb-camera-bench.lock
mkdir "$lock"; stopped=0; pl_active=0; child=; stop_requested=0
stop() { stop_requested=1; if test -n "$child"; then kill -TERM "$child" 2>/dev/null || :; fi; }
restore() {
    rc=$?; trap - EXIT HUP INT TERM
    if test -n "$child"; then kill -TERM "$child" 2>/dev/null || :; wait "$child" 2>/dev/null || :; fi
    rm -f "$lock/child.pid"; rmdir "$lock"
    if test "$stopped" = 1; then
        if test "$rc" != 0 && test "$pl_active" = 1; then sync; /sbin/reboot
        else sh "$baseline/scripts/zslamctl.sh" start; fi
    fi
    exit "$rc"
}
trap restore EXIT
trap stop HUP INT TERM
chmod 755 bin/zynq-slam bin/test-zslam
scratch_root=$(readlink -f /tmp); scratch=$(mktemp -d "$scratch_root/zslam-focus-selftest.XXXXXX")
./bin/test-zslam "$scratch" < /dev/null > "$tag-selftest.log" 2>&1
tar -czf "$tag-cpu-selftest-output.tar.gz" -C "$scratch" .
case "$scratch" in "$scratch_root"/zslam-focus-selftest.*) ;; *) exit 1;; esac
test "$(readlink -f "$scratch")" = "$scratch"; rm -r -- "$scratch"
sh "$baseline/scripts/zslamctl.sh" status | grep '^RUNNING'
stopped=1; sh "$baseline/scripts/zslamctl.sh" stop
set -- --camera /dev/video0 --camera-preview --hdmi-uio /dev/uio0 --target-fps 30 --frames "$frames" --snapshot --output "$release/$tag"
if test "$shots" -gt 0; then set -- "$@" --calibration-shots "$shots" --calibration-every "$every"; fi
pl_active=1
./bin/zynq-slam "$@" < /dev/null > "$tag.log" 2>&1 &
child=$!; printf '%s\n' "$child" > "$lock/child.pid"
rc=0; wait "$child" || rc=$?
if test "$stop_requested" = 1; then rc=0; wait "$child" || rc=$?; fi
child=
test "$rc" = 0
pl_active=0
cat "$tag/preview.json" "$tag/camera.json" "$tag/display.json"
echo 'UNCALIBRATED_PREVIEW_COMPLETED; focus score is a guide, not calibration acceptance'
