#!/bin/sh
# SD-resident PS startup; never loads PL, rewrites firmware or retries PL faults.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$root"
sha256sum -c SHA256SUMS
test "$(uname -r)" = 4.14.0-xilinx
sh ./scripts/bind_wc.sh
if ! test -d /sys/module/videobuf2_vmalloc; then insmod modules/videobuf2-vmalloc.ko; fi
if ! test -d /sys/module/uvcvideo; then insmod modules/uvcvideo.ko; fi
n=0
while ! test -c /dev/video0; do
    n=$((n+1))
    if test "$n" -ge 30; then echo 'ERROR: USB camera unavailable; no replay/CPU fallback' >&2; exit 1; fi
    sleep 1
done
exec sh /opt/orb-demo/current/run_zynq.sh
