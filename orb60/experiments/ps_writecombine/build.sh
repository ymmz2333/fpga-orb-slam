#!/usr/bin/env bash
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
orb_root="$(cd -- "$source_dir/../.." && pwd)"
output="$(realpath -m "$1")"
kernel_build="${2:-}"
mkdir -p "$output"
arm-linux-gnueabihf-gcc -std=c11 -O2 -Wall -Wextra -Werror -static \
    -mcpu=cortex-a9 -mfpu=neon -I"$orb_root/linux" "$source_dir/bench.c" -o "$output/ddr-bench-arm"
gcc -std=c11 -O2 -Wall -Wextra -Werror -I"$orb_root/linux" "$source_dir/bench.c" -o "$output/ddr-bench-host"
sha256sum "$output/ddr-bench-arm" > "$output/bench.sha256"
echo DDR_BENCH_BUILD_PASS
if [[ -z "$kernel_build" ]]; then
    echo MODULE_NOT_BUILT_matching_kernel_build_required
    exit 0
fi
test -s "$kernel_build/Module.symvers"
test -f "$kernel_build/include/generated/autoconf.h"
test -f "$kernel_build/include/generated/utsrelease.h"
grep -q '"4.14.0-xilinx"' "$kernel_build/include/generated/utsrelease.h"
mkdir "$output/module"
cp "$source_dir/Makefile" "$source_dir/orb60_wc_uio.c" "$output/module/"
make -C "$kernel_build" ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- M="$output/module" modules
modinfo "$output/module/orb60_wc_uio.ko" > "$output/module_info.txt"
echo MODULE_BUILD_COMPLETE_REQUIRES_BOARD_ABI_CHECK
