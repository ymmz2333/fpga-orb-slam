#!/bin/sh
# Physical7015 PL ORB, native7015 PS localization and fixed colored HDMI.
set -eu
release=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mode=${1:?live_camera or recorded_diagnostic required}
frames=${2:?finite frame count required}
probe=${3:-}
case "$frames" in ''|*[!0-9]*) exit 64;; esac
if test "${ORB60_NETWORK_MANUAL:-0}" = 1; then
    test "$frames" -eq 0 && test "$mode" = live_camera
else
    test "${ORB60_NETWORK_MANUAL:-0}" = 0
    test "$frames" -ge 1 && test "$frames" -le 36000
fi
set --
case "${ORB60_FIXED_MAP_MULTIVIEW:-0}" in 0) ;; 1) set -- --fixed-map-multiview;; *) exit 64;; esac
if test "${ORB60_NETWORK_MANUAL:-0}" = 1; then set -- "$@" --network-manual; fi
case "$mode" in
  live_camera) maps="$release/maps_live"; calibration="$release/camera_live.csv";;
  recorded_diagnostic) maps="$release/maps_recorded"; calibration="$release/camera_recorded.csv";;
  *) echo 'Explicit camera or recorded diagnostic required' >&2; exit 64;;
esac
if test "$probe" = --allow-unmapped-input-probe; then
    test "$mode" = live_camera
    test ! -f "$maps/current"
    echo 'INPUT_ONLY_PROBE: no installed map, no localization success will be claimed'
else
    test -z "$probe"
    test -f "$maps/current" || { echo 'Install the matching camera map before localization' >&2; exit 1; }
fi
test -c /dev/uio0
test "$(cat /sys/class/uio/uio0/version)" = wc1
cd "$release"
sha256sum -c SHA256SUMS
lock=/run/orb-demo.lock
mkdir "$lock"
child=
cleanup(){
    trap - EXIT HUP INT TERM
    if test -n "$child"; then kill -TERM "$child" 2>/dev/null || :; wait "$child" 2>/dev/null || :; fi
    rmdir "$lock"
}
trap cleanup EXIT
trap 'exit 143' HUP INT TERM
boot=$(cat /proc/sys/kernel/random/boot_id)
mkdir -p "$release/runs"
run=$(mktemp -d "$release/runs/network-$boot-XXXXXX")
if test -f "$maps/current"; then cat "$maps/current" >"$run/map_before.txt"; else echo NO_FIXED_MAP >"$run/map_before.txt"; fi
begin=$(cut -d ' ' -f 1 /proc/uptime)
"$release/bin/zynq-demo" --calibration "$calibration" --maps "$maps" --output "$run/app" \
    --network-camera-port 5605 --network-input-mode "$mode" --frames "$frames" --color-fps 0 --uio /dev/uio0 "$@" \
    </dev/null >"$run/stdout.log" 2>"$run/stderr.log" &
child=$!
echo "NETWORK_LOCALIZATION_RUN=$run"
attempt=0
while ! grep -q '^NETWORK_CAMERA_READY ' "$run/stdout.log"; do
    kill -0 "$child" 2>/dev/null || { tail -n 5 "$run/stderr.log" >&2; exit 1; }
    attempt=$((attempt+1));test "$attempt" -lt 200 || { echo 'Network receiver startup timed out' >&2; exit 1; }
    sleep .1
done
echo "NETWORK_LOCALIZER_READY mode=$mode port=5605 frames=$frames"
rc=0;wait "$child" || rc=$?;child=
end=$(cut -d ' ' -f 1 /proc/uptime)
printf '%s %s\n' "$begin" "$end" >"$run/monotonic_bounds.txt"
printf '%s\n' "$rc" >"$run/exit_code"
if test -f "$maps/current"; then cat "$maps/current" >"$run/map_after.txt"; else echo NO_FIXED_MAP >"$run/map_after.txt"; fi
cmp "$run/map_before.txt" "$run/map_after.txt"
echo "NETWORK_LOCALIZATION_FINISHED=$run"
tail -n 3 "$run/stdout.log"
test ! -s "$run/stderr.log" || tail -n 5 "$run/stderr.log"
exit "$rc"
