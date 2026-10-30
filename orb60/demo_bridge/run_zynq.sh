#!/bin/sh
# New isolated release only; no bit loading, old service restart or boot-file changes.
set -eu
release=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test -x "$release/bin/zynq-demo"
test -c /dev/video0
test -c /dev/uio0
test "$(cat /sys/class/uio/uio0/version)" = wc1
test -x "$release/bin/s1-reset-bridge"
test -c /dev/input/event0
cd "$release"
sha256sum -c SHA256SUMS
maps=${DEMO_MAP_STORE:-/opt/orb-demo/maps}
mkdir -p "$maps" "$release/runs"
lock=/run/orb-demo.lock
mkdir "$lock"
child=; key=; rc=0
cleanup() {
 trap - EXIT HUP INT TERM
 if test -n "$key"; then kill -TERM "$key" 2>/dev/null || :; wait "$key" 2>/dev/null || :; fi
 if test -n "$child"; then kill -TERM "$child" 2>/dev/null || :; wait "$child" 2>/dev/null || :; fi
 rm -f "$lock/control.fifo"; rmdir "$lock"
}
trap cleanup EXIT
trap 'exit 143' HUP INT TERM
mkfifo -m 600 "$lock/control.fifo"
exec 3<>"$lock/control.fifo"
run="$release/runs/$(date -u +%Y%m%dT%H%M%S)-$$"
mkdir "$run"
"$release/bin/zynq-demo" --camera /dev/video0 --uio /dev/uio0 \
 --source-calibration "$release/config/camera_source.csv" \
 --calibration "$release/config/camera_orb.csv" --maps "$maps" \
 --output "$run/app" <&3 >"$run/stdout.log" 2>"$run/stderr.log" &
child=$!
"$release/bin/s1-reset-bridge" /dev/input/event0 "$lock/control.fifo" "$run/relocalize-key.json" > /dev/null 2>"$run/key.log" &
key=$!
echo 'DEMO_STARTED; S1 requests relocalization and preserves the installed map'
while kill -0 "$child" 2>/dev/null; do
 if ! kill -0 "$key" 2>/dev/null; then echo 'S1 reader failed; stopping this demo' >&2; exit 1; fi
 sleep 1
done
wait "$child" || rc=$?
child=
exit "$rc"
