#!/bin/sh
# The one original WC provider owns ORB controls, HDMI controls and all 16MiB.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
cd "$(dirname "$0")/.."
test "$(id -u)" = 0
test "$(uname -r)" = 4.14.0-xilinx
node=/sys/bus/platform/devices/43c00000.orb60
test -d "$node"
if ! test -d /sys/module/orb60_wc_uio; then insmod kernel/orb60_wc_uio.ko; fi
test "$(cat /sys/module/orb60_wc_uio/parameters/write_combine)" = Y
if test -L "$node/driver"; then
    driver=$(readlink "$node/driver")
    case "$driver" in
        */orb60_wc_uio) : ;;
        */uio_pdrv_genirq) printf '43c00000.orb60' > "$node/driver/unbind" ;;
        *) echo "Unexpected UIO owner: $driver" >&2;exit 1 ;;
    esac
fi
printf 'orb60_wc_uio' > "$node/driver_override"
if ! test -L "$node/driver"; then printf '43c00000.orb60' > /sys/bus/platform/drivers/orb60_wc_uio/bind; fi
found=0
for u in "$node"/uio/uio*; do
    test -d "$u" || continue
    test "$(cat "$u/version")" = wc1
    test "$(( $(cat "$u/maps/map0/addr") ))" -eq "$(( 0x43c00000 ))"
    test "$(( $(cat "$u/maps/map0/size") ))" -eq "$(( 0x10000 ))"
    test "$(( $(cat "$u/maps/map1/addr") ))" -eq "$(( 0x43c10000 ))"
    test "$(( $(cat "$u/maps/map1/size") ))" -eq "$(( 0x10000 ))"
    test "$(( $(cat "$u/maps/map2/addr") ))" -eq "$(( 0x20000000 ))"
    test "$(( $(cat "$u/maps/map2/size") ))" -eq "$(( 0x1000000 ))"
    printf '/dev/%s\n' "${u##*/}" > /run/zynq-slam.uio
    printf 'WC_UIO_READY /dev/%s\n' "${u##*/}"
    found=$((found+1))
done
test "$found" = 1
