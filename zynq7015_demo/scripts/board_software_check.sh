#!/bin/sh
# CPU-only validation in a fresh scratch directory; never opens UIO/video/fb.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
cd "$(dirname "$0")/.."
test "$(uname -m)" = armv7l
test -r /lib/ld-linux-armhf.so.3
sha256sum -c SHA256SUMS
test_dir=$(mktemp -d /tmp/zslam-selftest.XXXXXX)
printf 'SELFTEST_OUTPUT=%s\n' "$test_dir"
# Extracted files may lack executable bits after transfer from Windows.
chmod u+x bin/zynq-slam bin/test-zslam
./bin/zynq-slam --help
./bin/test-zslam "$test_dir"
echo CPU_SOFTWARE_CHECK_PASS
