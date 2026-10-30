#!/bin/sh
# Usage: sh install_sd_autostart.sh DIRECTORY_WITH_START_CAMERA_AND_ORB_DEMO_INIT
# Only rootfs startup configuration changes. Keep SD firmware and the old release.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
stage=$(CDPATH= cd -- "$1" && pwd)
test "$(id -u)" = 0
test "$(uname -r)" = 4.14.0-xilinx
test -f "$stage/start_camera.sh"
test -f "$stage/orb-demo.init"
sh -n "$stage/start_camera.sh"
sh -n "$stage/orb-demo.init"
release=$(readlink -f /opt/orb-demo/current)
test "$release" = /opt/orb-demo/releases/demo_20261026_handover_quiescent
cd "$release"
sha256sum -c SHA256SUMS
echo '513716173ca48f7a4cb8b6243f9d036188d790aaa387b8f86706d569246d5ce1  bin/zynq-demo' | sha256sum -c -
modules=/opt/zynq-slam/experiments/uvc_20261024_162629/modules
cd "$modules"
echo 'f7049ab3e6fb1ffdbb7570c80fa9945fa3ec573a1a04ccc062a3456dcff6f228  uvcvideo.ko' | sha256sum -c -
echo 'abc327e71f17cb9ddf8b5f4e00c03ce28eaa7bb75b78a10e0aba582ebd8df163  videobuf2-vmalloc.ko' | sha256sum -c -
stamp=$(cat /proc/sys/kernel/random/boot_id)
backup=/opt/orb-demo/acceptance/autostart-$stamp
test ! -e "$backup"
mkdir -p "$backup"
cp /etc/init.d/zynq-slam "$backup/zynq-slam.init.original"
ls -l /etc/rc?.d/*zynq-slam > "$backup/old-symlinks.txt"
cat /opt/orb-demo/maps/current > "$backup/map-pointer.before"
cat /proc/sys/kernel/random/boot_id > "$backup/boot_id.before"
sd=/run/media/mmcblk0p1
sha256sum "$sd/BOOT.BIN" "$sd/zImage" "$sd/system.bit" "$sd/system.dtb" "$sd/uEnv.txt" > "$backup/firmware.before.sha256"
dest=/opt/orb-demo/boot-$stamp
mkdir -p "$dest/modules" "$dest/kernel" "$dest/scripts"
cp "$stage/start_camera.sh" "$dest/start_camera.sh"
cp "$stage/orb-demo.init" "$dest/orb-demo.init"
cp "$modules/uvcvideo.ko" "$modules/videobuf2-vmalloc.ko" "$dest/modules/"
cp /opt/zynq-slam/current/kernel/orb60_wc_uio.ko "$dest/kernel/"
cp /opt/zynq-slam/current/scripts/bind_wc.sh "$dest/scripts/"
chmod 755 "$dest/start_camera.sh" "$dest/orb-demo.init" "$dest/scripts/bind_wc.sh"
cd "$dest"
sha256sum start_camera.sh orb-demo.init modules/*.ko kernel/*.ko scripts/bind_wc.sh > SHA256SUMS
sha256sum -c SHA256SUMS
sh /etc/init.d/zynq-slam stop
test ! -d /run/zynq-slam.lock
test ! -d /run/orb-demo.lock
for level in 0 1 2 3 4 5 6; do
    for prefix in S99 K01; do
        link=/etc/rc$level.d/${prefix}zynq-slam
        if test -L "$link"; then
            test "$(readlink "$link")" = ../init.d/zynq-slam
            rm "$link"
        fi
    done
done
ln -s "$dest" /opt/orb-demo/boot.new
mv -f /opt/orb-demo/boot.new /opt/orb-demo/boot
cp "$dest/orb-demo.init" /etc/init.d/orb-demo.new
chmod 755 /etc/init.d/orb-demo.new
mv -f /etc/init.d/orb-demo.new /etc/init.d/orb-demo
for level in 2 3 4 5; do ln -sfn ../init.d/orb-demo "/etc/rc$level.d/S99orb-demo"; done
for level in 0 1 6; do ln -sfn ../init.d/orb-demo "/etc/rc$level.d/K01orb-demo"; done
sync
sha256sum -c "$backup/firmware.before.sha256"
sh /etc/init.d/orb-demo start
echo "AUTOSTART_INSTALLED backup=$backup"
