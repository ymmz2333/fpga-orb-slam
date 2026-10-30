#!/bin/sh
# Install a verified release using a new FAT subdirectory; preserve original boot files.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
release=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
name=${release##*/}
case "$name" in sd_ssh_[0-9]*_[0-9]*) :;; *) echo 'Unexpected release directory' >&2; exit 1;;esac
test "$(id -u)" = 0
test -f "/opt/zynq-slam/acceptance/$name.physical-io-verified"
sd=/run/media/mmcblk0p1
awk '$1=="/dev/mmcblk0p1" && $2=="/run/media/mmcblk0p1" && $3=="vfat" {ok=1} END {exit !ok}' /proc/mounts
cd "$release"
sha256sum -c SHA256SUMS
./bin/board-probe --loaded
test -r /run/zynq-slam.uio
test -f "$sd/BOOT.BIN"
test -f "$sd/zImage"
test -f "$sd/uEnv.txt"
if test -e /etc/init.d/zynq-slam; then cmp scripts/zynq-slam.init /etc/init.d/zynq-slam; fi
for level in 0 1 2 3 4 5 6; do
    test -d "/etc/rc$level.d"
    case "$level" in 2|3|4|5) link=/etc/rc$level.d/S99zynq-slam;; *) link=/etc/rc$level.d/K01zynq-slam;; esac
    if test -e "$link" || test -L "$link"; then
        test -L "$link" && test "$(readlink "$link")" = ../init.d/zynq-slam
    fi
done
target=$sd/zynq-slam/$name
test ! -e "$target"
mkdir -p "$target"
cp firmware/s_wrapper.bit "$target/system.bit"
cp hardware/system.dtb "$target/system.dtb"
cmp firmware/s_wrapper.bit "$target/system.bit"
cmp hardware/system.dtb "$target/system.dtb"
cp "$sd/uEnv.txt" "$target/uEnv.previous.txt"
# Retain the first factory selection when upgrading our own installed release.
if test -L /opt/zynq-slam/current; then
    previous=$(readlink /opt/zynq-slam/current)
    case "$previous" in /opt/zynq-slam/releases/sd_ssh_*) :;; *) echo 'Unexpected current release' >&2;exit 1;;esac
    original=$sd/zynq-slam/${previous##*/}/uEnv.original.txt
    test -f "$original"
    cp "$original" "$target/uEnv.original.txt"
else
    cp "$sd/uEnv.txt" "$target/uEnv.original.txt"
fi
sha256sum "$sd/BOOT.BIN" "$sd/zImage" "$sd/system.bit" "$sd/system.dtb" "$target/uEnv.original.txt" > "$target/original-sha256.txt"
cat > "$target/uEnv.new.txt" <<EOF
bitstream_load_address=0x100000
bitstream_image=zynq-slam/$name/system.bit
kernel_image=zImage
devicetree_image=zynq-slam/$name/system.dtb
uenvcmd=run sdboot
bootcmd=run sdboot
sdboot=if mmcinfo; then fatload mmc 0 \${bitstream_load_address} \${bitstream_image} && fpga loadb 0 \${bitstream_load_address} \${filesize} && fatload mmc 0 \${kernel_load_address} \${kernel_image} && fatload mmc 0 \${devicetree_load_address} \${devicetree_image} && bootz \${kernel_load_address} - \${devicetree_load_address}; fi
EOF
cp scripts/zynq-slam.init /etc/init.d/zynq-slam
chmod 755 /etc/init.d/zynq-slam
ln -sfn "$release" /opt/zynq-slam/current
for level in 2 3 4 5; do ln -sfn ../init.d/zynq-slam "/etc/rc$level.d/S99zynq-slam"; done
for level in 0 1 6; do ln -sfn ../init.d/zynq-slam "/etc/rc$level.d/K01zynq-slam"; done
cp "$target/uEnv.new.txt" "$sd/uEnv.zynq-slam.new"
sync
mv "$sd/uEnv.zynq-slam.new" "$sd/uEnv.txt"
sync
echo "SD_BOOT_INSTALLED release=$name backup=$target/uEnv.original.txt"
echo 'Original BOOT.BIN, zImage, system.bit and system.dtb are preserved. No flash environment write.'
