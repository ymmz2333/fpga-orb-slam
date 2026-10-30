#!/bin/sh
# Restore only the saved SD boot selection. Original boot payloads were preserved.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
release=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
name=${release##*/}
sd=/run/media/mmcblk0p1
backup=$sd/zynq-slam/$name/uEnv.original.txt
test "$(id -u)" = 0
test -f "$backup"
sh "$release/scripts/zslamctl.sh" stop
sed 's/^uenvcmd=.*/uenvcmd=run sdboot/' "$backup" > "$sd/uEnv.zynq-slam.restore"
if grep -q saveenv "$sd/uEnv.zynq-slam.restore"; then echo 'Refuse a flash environment write' >&2; exit 1; fi
sync
mv "$sd/uEnv.zynq-slam.restore" "$sd/uEnv.txt"
for level in 2 3 4 5; do
    link=/etc/rc$level.d/S99zynq-slam
    if test -L "$link" && test "$(readlink "$link")" = ../init.d/zynq-slam; then rm "$link"; fi
done
for level in 0 1 6; do
    link=/etc/rc$level.d/K01zynq-slam
    if test -L "$link" && test "$(readlink "$link")" = ../init.d/zynq-slam; then rm "$link"; fi
done
sync
echo 'Original SD boot selection restored; reboot selects the original PL/device tree. No reboot was issued.'
