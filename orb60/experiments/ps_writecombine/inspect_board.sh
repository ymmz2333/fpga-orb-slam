#!/bin/sh
set -eu
uname -a
zcat /proc/config.gz | grep -E 'CONFIG_(MODULES|MODVERSIONS|MODULE_UNLOAD|ARM_LPAE|SMP|PREEMPT|LOCALVERSION|LOCALVERSION_AUTO|UIO|DEVMEM|STRICT_DEVMEM|IKCONFIG|DEBUG_INFO|DEBUG_FS)='
ls -l /lib/modules/4.14.0-xilinx
ps | grep -E 'orb60|mono_euroc|SLAM' | head -12
ls /sys/kernel/debug/arm_pagetables /sys/kernel/debug/page_tables 2>/dev/null || true
printf 'taint='
cat /proc/sys/kernel/tainted
cat /tmp/orb60-switch-server.sh
for f in /sys/class/uio/uio0/maps/map*/*; do
    printf '%s=' "$f"
    cat "$f"
done
