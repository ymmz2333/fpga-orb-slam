#!/bin/sh
set -eu
PATH=/sbin:/usr/sbin:/bin:/usr/bin
export PATH
state=/tmp/orb60-wc-experiment-state
test -d "$state" || { echo WC_NOT_ACTIVE;exit 0; }
test ! -f "$state/restored" || { echo WC_ALREADY_RESTORED;exit 0; }
device=$(cat "$state/device")
driver=$(cat "$state/original_driver")
override=$(cat "$state/original_override")
case "$override" in ''|'(null)'|uio_pdrv_genirq) ;; *) echo invalid-saved-override;exit 1;; esac
case "$device" in /sys/devices/platform/*orb60*) ;; *) echo invalid-saved-device;exit 1;; esac
test "$driver" = /sys/bus/platform/drivers/uio_pdrv_genirq
current=$(readlink -f "$device/driver" || true)
if test "$current" != "$driver";then
    if awk '$4 == "01" && $2 ~ /:15E0$/ {active=1} END {exit !active}' /proc/net/tcp /proc/net/tcp6;then
        echo active-client-close-before-restore;exit 1
    fi
    /tmp/orb60-150/board-probe --loaded
    if test -f /tmp/orb60-150/server.pid;then
        pid=$(cat /tmp/orb60-150/server.pid)
        case "$pid" in ''|*[!0-9]*) exit 1;; esac
        if test -e "/proc/$pid/exe";then
            executable=$(readlink "/proc/$pid/exe")
            case "$executable" in /tmp/orb60-server-pipeline|/var/volatile/tmp/orb60-server-pipeline) ;; *) exit 1;; esac
            kill -TERM "$pid"
            for attempt in 1 2 3 4 5;do test -e "/proc/$pid/exe" || break;sleep 1;done
            test ! -e "/proc/$pid/exe"
        fi
    fi
    case "$current" in
        /sys/bus/platform/drivers/orb60_wc_uio)
            printf '%s' "${device##*/}" > "$current/unbind";;
        "$device/driver"|'') ;;
        *) echo unexpected-current-driver;exit 1;;
    esac
    case "$override" in
        ''|'(null)') printf '\n' > "$device/driver_override";;
        *) printf '%s\n' "$override" > "$device/driver_override";;
    esac
    printf '%s' "${device##*/}" > "$driver/bind"
    test "$(readlink -f /sys/class/uio/uio0/device/driver)" = "$driver"
    sh /tmp/orb60-switch-server.sh /tmp/orb60-server-pipeline /tmp/orb60-pipeline-wc-restored.log --profile --pipeline
fi
test ! -d /sys/module/orb60_wc_uio || rmmod orb60_wc_uio
touch "$state/restored"
echo WC_ORIGINAL_DRIVER_AND_SERVER_RESTORED
