#!/bin/sh
# Read-only SD-boot/SSH inventory. No MMIO, driver changes or PL loading.
set -u
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
section() { printf '\n=== %s ===\n' "$1"; }
section identity
uname -a
id
for p in model compatible; do
    f=/sys/firmware/devicetree/base/$p
    if test -r "$f"; then printf '%s: ' "$p"; tr '\000' '\n' < "$f"; fi
done
section sd_boot
cat /proc/cmdline
cat /proc/mounts
for p in /run/media/mmcblk0p1 /boot; do
    if test -d "$p"; then ls -la "$p"; fi
done
section runtime
if command -v getconf >/dev/null 2>&1; then getconf GNU_LIBC_VERSION 2>/dev/null || true; fi
ls -l /lib/ld-linux-armhf.so.3 /lib/libc.so.6 /lib/libm.so.6 2>/dev/null || true
head -n 5 /proc/meminfo
cat /proc/cpuinfo
section fpga_manager
for p in /sys/class/fpga_manager/*; do
    test -d "$p" || continue
    printf '%s\n' "$p"
    for f in name state; do test ! -r "$p/$f" || cat "$p/$f"; done
done
section uio
for p in /sys/class/uio/uio*; do
    test -d "$p" || continue
    printf '%s driver=' "$p"; readlink "$p/device/driver" || true
    test ! -r "$p/name" || cat "$p/name"
    for m in "$p"/maps/map*; do
        test -d "$m" || continue
        printf '%s\n' "$m"
        for f in name addr size offset; do printf '%s=' "$f"; cat "$m/$f"; done
    done
done
section reserved_memory
for p in /sys/firmware/devicetree/base/reserved-memory/*; do
    test -d "$p" || continue
    printf '%s no-map=' "$p"; if test -f "$p/no-map"; then echo yes; else echo no; fi
    test ! -r "$p/reg" || od -An -tx1 "$p/reg"
done
section platform_devices
ls /sys/bus/platform/devices
section camera_display
for p in /sys/class/video4linux/*; do test ! -r "$p/name" || { printf '%s: ' "$p"; cat "$p/name"; }; done
for p in /sys/class/graphics/fb*; do
    test -d "$p" || continue
    for f in name virtual_size bits_per_pixel stride; do test ! -r "$p/$f" || { printf '%s/%s=' "$p" "$f"; cat "$p/$f"; }; done
done
for p in /sys/class/drm/*/status; do test ! -r "$p" || { printf '%s=' "$p"; cat "$p"; }; done
section consumers
ps
section end
echo READ_ONLY_INVENTORY_COMPLETE
