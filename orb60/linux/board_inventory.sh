#!/bin/sh
set -eu
echo ORB60_BOARD_INVENTORY
uname -a
cat /sys/class/fpga_manager/fpga0/state
for p in /sys/bus/platform/devices/*; do
    n=$(readlink "$p/of_node" || true)
    case "$n" in
        *amba_pl*|*reserved*|*xlnx_snd_card*)
            printf '%s node=%s driver=%s\n' "${p##*/}" "$n" "$(readlink "$p/driver" || true)";;
    esac
done
cat /proc/iomem
cat /proc/interrupts
