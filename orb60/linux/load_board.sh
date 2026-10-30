#!/bin/sh
# Volatile PL replacement only. SD BOOT.BIN/system.bit/dtb/uEnv are preserved.
set -eu
cd "$(dirname "$0")"
test "$(id -u)" = 0
test -w /sys/class/fpga_manager/fpga0/firmware
test -d /sys/kernel/config/device-tree/overlays
test ! -d /sys/kernel/config/device-tree/overlays/orb60
sha256sum -c firmware.sha256
./board-probe
test "$(od -An -tx1 /sys/firmware/devicetree/base/reserved-memory/buffer@0x20000000/reg | tr -d ' \n')" = 2000000020000000
test -f /sys/firmware/devicetree/base/reserved-memory/buffer@0x20000000/no-map
# Stop consumers before providers. All names are from the saved live inventory.
for dev in xlnx_snd_card.0 amba_pl:xlnx_vdma_lcd 43000000.dma 43c30000.i2s_receiver 43c40000.i2s_transmitter 43c10000.audio_formatter 41600000.i2c 43c20000.clk_wiz; do
    node="/sys/bus/platform/devices/$dev"
    if test -L "$node/driver"; then
        printf 'UNBIND %s\n' "$dev"
        printf '%s' "$dev" > "$node/driver/unbind"
    fi
done
./board-probe
cp orb60_150mhz.bit.bin /lib/firmware/orb60_150mhz.bin
printf '0' > /sys/class/fpga_manager/fpga0/flags
printf 'orb60_150mhz.bin' > /sys/class/fpga_manager/fpga0/firmware
test "$(cat /sys/class/fpga_manager/fpga0/state)" = operating
./board-probe --loaded
mkdir /sys/kernel/config/device-tree/overlays/orb60
cat acz7015-orb60.dtbo > /sys/kernel/config/device-tree/overlays/orb60/dtbo
node=/sys/bus/platform/devices/43c00000.orb60
test -d "$node"
if ! test -L "$node/driver"; then
    printf 'uio_pdrv_genirq' > "$node/driver_override"
    printf '43c00000.orb60' > /sys/bus/platform/drivers/uio_pdrv_genirq/bind
fi
for u in "$node"/uio/uio*; do
    test -d "$u"
    printf 'ORB60_UIO_READY /dev/%s\n' "${u##*/}"
    for m in "$u"/maps/map*; do printf '%s addr=%s size=%s\n' "${m##*/}" "$(cat "$m/addr")" "$(cat "$m/size")"; done
done
echo ORB60_VOLATILE_LOAD_PASS
