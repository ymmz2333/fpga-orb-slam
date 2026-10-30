#!/bin/sh
# Full volatile PL replacement after verified backup; SD boot files are untouched.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
cd "$(dirname "$0")/.."
test "$(id -u)" = 0
test "$(uname -r)" = 4.14.0-xilinx
test -w /sys/class/fpga_manager/fpga0/firmware
test -d /sys/kernel/config/device-tree/overlays
test ! -d /sys/kernel/config/device-tree/overlays/zslam_hdmi2
test ! -d /sys/bus/platform/devices/43c00000.orb60
sha256sum -c SHA256SUMS
chmod u+x bin/board-probe bin/zynq-slam bin/test-zslam
./bin/board-probe
test "$(od -An -tx1 /sys/firmware/devicetree/base/reserved-memory/buffer@0x20000000/reg | tr -d ' \n')" = 2000000020000000
test -f /sys/firmware/devicetree/base/reserved-memory/buffer@0x20000000/no-map
# Consumers before providers. The current driver links were inspected over SSH.
for dev in xlnx_snd_card.0 amba_pl:xlnx_vdma_lcd 43000000.dma 43c30000.i2s_receiver 43c40000.i2s_transmitter 43c10000.audio_formatter 41600000.i2c 43c20000.clk_wiz 43c00000.DVP_Capture2DDR 43c60000.Measure_Camera_Parametar 43c70000.Check_GPIO reserved-driver@1; do
    path=/sys/bus/platform/devices/$dev
    if test -L "$path/driver"; then
        printf 'UNBIND %s\n' "$dev"
        printf '%s' "$dev" > "$path/driver/unbind"
    fi
done
firmware_name=zslam_hdmi2_$(sha256sum firmware/s_wrapper.bit.bin | cut -c1-16).bin
mkdir -p /lib/firmware
if test -f "/lib/firmware/$firmware_name"; then
    cmp firmware/s_wrapper.bit.bin "/lib/firmware/$firmware_name"
else
    cp firmware/s_wrapper.bit.bin "/lib/firmware/$firmware_name"
fi
printf '0' > /sys/class/fpga_manager/fpga0/flags
printf '%s' "$firmware_name" > /sys/class/fpga_manager/fpga0/firmware
test "$(cat /sys/class/fpga_manager/fpga0/state)" = operating
./bin/board-probe --loaded
mkdir /sys/kernel/config/device-tree/overlays/zslam_hdmi2
cat hardware/orb60-hdmi.dtbo > /sys/kernel/config/device-tree/overlays/zslam_hdmi2/dtbo
sh scripts/bind_wc.sh
echo HDMI2_VOLATILE_PL_AND_UIO_READY
