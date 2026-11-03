#!/bin/sh
# Explicit saved-video input, real7015 PL ORB and PS fixed-map localization.
# The same-map RGB environment is display-only; no hardware loading/recovery.
set -eu
release=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
frames=${1:-2273}
case "$frames" in ''|*[!0-9]*) echo 'Frame count must be an integer' >&2; exit 64;; esac
test "$frames" -ge 1 && test "$frames" -le 2273
set --
case "${ORB60_FIXED_MAP_MULTIVIEW:-0}" in 0) ;; 1) set -- --fixed-map-multiview;; *) exit 64;; esac
raw=${KV260_REPLAY_RAW:-/opt/zynq-slam/data/video_inputs_20261023/gray8.bin}
index=${KV260_REPLAY_INDEX:-/opt/zynq-slam/data/video_inputs_20261023/frames.csv}
test -f "$raw" && test -f "$index"
test -c /dev/uio0
test "$(cat /sys/class/uio/uio0/version)" = wc1
test -f "$release/maps/current" && test -f "$release/map/dense_environment.bin"
cd "$release"
sha256sum -c SHA256SUMS
lock=/run/orb-demo.lock
mkdir "$lock"
child=
cleanup() {
    trap - EXIT HUP INT TERM
    if test -n "$child"; then kill -TERM "$child" 2>/dev/null || :; wait "$child" 2>/dev/null || :; fi
    rmdir "$lock"
}
trap cleanup EXIT
trap 'exit 143' HUP INT TERM
boot=$(cat /proc/sys/kernel/random/boot_id)
mkdir -p "$release/runs"
run=$(mktemp -d "$release/runs/recording-$boot-XXXXXX")
cp "$release/maps/current" "$run/map_before.txt"
begin=$(cut -d ' ' -f 1 /proc/uptime)
"$release/bin/zynq-demo" --raw "$raw" --raw-index "$index" \
    --source-calibration "$release/map/camera_orb.csv" \
    --calibration "$release/map/camera_orb.csv" --maps "$release/maps" \
    --frames "$frames" --uio /dev/uio0 --output "$run/app" "$@" \
    </dev/null >"$run/stdout.log" 2>"$run/stderr.log" &
child=$!
rc=0
wait "$child" || rc=$?
child=
end=$(cut -d ' ' -f 1 /proc/uptime)
printf '%s %s\n' "$begin" "$end" >"$run/monotonic_bounds.txt"
printf '%s\n' "$rc" >"$run/exit_code"
cmp "$release/maps/current" "$run/map_before.txt"
echo "RECORDED_COLOR_LOCALIZATION_RUN=$run"
tail -n 3 "$run/stdout.log"
test ! -s "$run/stderr.log" || tail -n 8 "$run/stderr.log"
exit "$rc"
