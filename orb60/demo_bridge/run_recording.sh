#!/bin/sh
# Explicit recorded-input mode. Pixels still pass through the physical PL core.
set -eu
test "$#" -ge 4 || { echo 'Usage: run_recording.sh RAW INDEX CAMERA MAP_STORE [FRAMES]'; exit 64; }
release=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test -c /dev/uio0
test "$(cat /sys/class/uio/uio0/version)" = wc1
cd "$release";sha256sum -c SHA256SUMS
lock=/run/orb-demo.lock
mkdir "$lock"
cleanup(){ rmdir "$lock"; }
trap cleanup EXIT
run="$release/runs/recording-$(date -u +%Y%m%dT%H%M%S)-$$"
mkdir -p "$run"
echo "RECORDED_PL_RUN=$run"
"$release/bin/zynq-demo" --raw "$1" --raw-index "$2" --source-calibration "$3" --calibration "$3" --maps "$4" --frames "${5:-0}" --uio /dev/uio0 --output "$run/app" </dev/null >"$run/stdout.log" 2>"$run/stderr.log"
cat "$run/stdout.log"
test ! -s "$run/stderr.log" || cat "$run/stderr.log"
