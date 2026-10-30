#!/bin/sh
# Temporary binding only. The caller must run restore_board.sh in a finally block.
set -eu
PATH=/sbin:/usr/sbin:/bin:/usr/bin
export PATH
state=/tmp/orb60-wc-experiment-state
module=/tmp/orb60-wc-uio.ko
test -s "$module"
if test -f "$state/restored";then
    mv "$state" "$state.previous.$(date +%s).$$"
fi
test ! -e "$state"
test ! -d /sys/module/orb60_wc_uio
device=$(readlink -f /sys/class/uio/uio0/device)
driver=$(readlink -f "$device/driver")
test "${driver##*/}" = uio_pdrv_genirq
test -w "$device/driver_override"
override=$(cat "$device/driver_override")
case "$override" in ''|'(null)'|uio_pdrv_genirq) ;; *) echo unexpected-driver-override;exit 1;; esac
old=$(cat /tmp/orb60-150/server.pid)
case "$old" in ''|*[!0-9]*) exit 1;; esac
old_exe=$(readlink "/proc/$old/exe")
case "$old_exe" in /tmp/orb60-server-pipeline|/var/volatile/tmp/orb60-server-pipeline) ;; *) exit 1;; esac
tr '\000' '\n' < "/proc/$old/cmdline" > /tmp/orb60-wc-prior-args
printf '%s\n' /tmp/orb60-server-pipeline --uio /dev/uio0 --profile --pipeline > /tmp/orb60-wc-expected-args
cmp /tmp/orb60-wc-prior-args /tmp/orb60-wc-expected-args
if awk '$4 == "01" && $2 ~ /:15E0$/ {active=1} END {exit !active}' /proc/net/tcp /proc/net/tcp6; then
    echo active-feature-client-refusing-test;exit 1
fi
/tmp/orb60-150/board-probe --loaded
mkdir "$state"
printf '%s\n' "$device" > "$state/device"
printf '%s\n' "$driver" > "$state/original_driver"
printf '%s\n' "$override" > "$state/original_override"
on_error() {
    trap - EXIT HUP INT TERM
    sh /tmp/orb60-wc-restore.sh || echo WC_RESTORE_FAILED
    exit 1
}
trap on_error EXIT HUP INT TERM
# Let the kernel check every symbol CRC normally. No force/ignore-vermagic flags.
insmod "$module" write_combine=1
kill -TERM "$old"
for attempt in 1 2 3 4 5;do test -e "/proc/$old/exe" || break;sleep 1;done
test ! -e "/proc/$old/exe"
printf '%s' "${device##*/}" > "$driver/unbind"
printf '%s\n' orb60_wc_uio > "$device/driver_override"
printf '%s' "${device##*/}" > /sys/bus/platform/drivers/orb60_wc_uio/bind
test "$(cat /sys/class/uio/uio0/name)" = orb60-writecombine-experiment
test "$(cat /sys/class/uio/uio0/version)" = wc1
cat /sys/module/orb60_wc_uio/parameters/write_combine
/tmp/orb60-wc-ddr-bench-arm /dev/uio0 24 32768
/tmp/orb60-wc-ddr-bench-arm /dev/uio0 24 691200
sh /tmp/orb60-switch-server.sh /tmp/orb60-server-pipeline /tmp/orb60-wc-pipeline.log --profile --pipeline
touch "$state/active"
trap - EXIT HUP INT TERM
echo WC_EXPERIMENT_ACTIVE
