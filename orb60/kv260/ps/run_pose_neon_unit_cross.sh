#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
task_cross_root=${KV260_CROSS_ROOT:-$HOME/.local/share/orb60/kv260-host/cross_arm11_20261103_a}
cd "$project_root"
exec python3 -m orb60.kv260.ps.compile_pose_neon_unit \
  --compiler "$task_cross_root/toolchain/gcc-arm-11.2-2022.02-x86_64-aarch64-none-linux-gnu/bin/aarch64-none-linux-gnu-g++" \
  --eigen "$task_cross_root/sysroot/usr/include/eigen3" \
  --output "$task_cross_root/pose_neon_unit_b"
