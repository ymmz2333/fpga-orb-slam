#!/bin/sh
# Camera-free demonstration: original GRAY8 recording -> physical ORB -> SLAM -> HDMI_2.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
release=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
data=/opt/zynq-slam/data/video_inputs_20261023/gray8.bin
runroot=/opt/zynq-slam/runs
test -r "$data"
test -f /run/zynq-slam.uio || sh "$release/scripts/bind_wc.sh"
uio=$(cat /run/zynq-slam.uio)
test -c "$uio"
mkdir /run/zynq-slam.lock
printf '%s\n' "$$" > /run/zynq-slam.lock/pid
mkfifo /run/zynq-slam.lock/control
exec 3<>/run/zynq-slam.lock/control
child=
stop_requested=0
stop() {
    stop_requested=1
    if test -n "$child"; then kill -TERM "$child" 2>/dev/null || :; fi
}
cleanup() {
    rm -f /run/zynq-slam.lock/pid /run/zynq-slam.lock/control
    rmdir /run/zynq-slam.lock
}
trap stop INT TERM
trap cleanup EXIT
mkdir -p "$runroot"
boot_id=$(cat /proc/sys/kernel/random/boot_id)
while test "$stop_requested" = 0; do
    read -r cycle_start ignored < /proc/uptime
    session=$(date +%Y%m%d_%H%M%S)-$$-$boot_id
    run=$runroot/session-$session
    test ! -e "$run"
    # The app creates the new directory and refuses to overwrite existing runs/maps.
    set -- --raw "$data" --uio "$uio" --hdmi-uio "$uio" \
        --calibration "$release/config/camera_handoff.csv" --max-points 3000 \
        --max-keyframes 16 --output "$run" --save "$run/map.zmap"
    if test "${ZSLAM_SNAPSHOT:-0}" = 1; then set -- "$@" --snapshot; fi
    if test -f "$runroot/latest/map.zmap"; then
        set -- "$@" --load "$runroot/latest/map.zmap"
    elif test -f /opt/zynq-slam/data/handoff_map_20261023/points.csv; then
        set -- "$@" --import-map /opt/zynq-slam/data/handoff_map_20261023
    fi
    "$release/bin/zynq-slam" "$@" <&3 > "$runroot/app-$session.log" 2>&1 &
    child=$!
    rc=0
    wait "$child" || rc=$?
    # wait can be interrupted by a supervisor signal; reap the app before unlocking UIO.
    if test "$stop_requested" = 1; then wait "$child" 2>/dev/null || :; fi
    child=
    if test -d "$run"; then
        mv "$runroot/app-$session.log" "$run/console.log"
        ln -sfn "$run" "$runroot/latest"
    fi
    test "$rc" = 0 || exit "$rc"
    # Keep three completed task-owned runs. Never follow a symlink for removal.
    count=0
    for old in $(find "$runroot" -maxdepth 1 -type d -name 'session-*' | sort -r); do
        count=$((count+1))
        if test "$count" -gt 3; then
            case "$old" in "$runroot"/session-*) test ! -L "$old" && rm -rf -- "$old";; *) exit 1;; esac
        fi
    done
    read -r cycle_end ignored < /proc/uptime
    echo "CYCLE start=$cycle_start end=$cycle_end run=$run"
    test "$stop_requested" = 0 || break
done
