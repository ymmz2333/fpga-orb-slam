#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
task_cross_root=${KV260_CROSS_ROOT:-$HOME/.local/share/orb60/kv260-host/cross_arm11_20261103_a}
cd "$project_root"
exec python3 -m orb60.kv260.ps.compile_pose_cross \
  --compiler "$task_cross_root/toolchain/gcc-arm-11.2-2022.02-x86_64-aarch64-none-linux-gnu/bin/aarch64-none-linux-gnu-g++" \
  --sysroot "$task_cross_root/sysroot" \
  --adapter-build "$project_root/orb60/build/kv260_system/private_arm_cross_20261103_a/evidence_files/network_native_20261103_d/BUILD.json" \
  --output "$task_cross_root/pose_quadratic_a" --variant quadratic \
  --equation-proof "$project_root/orb60/build/kv260_system/private_arm_cross_20261103_a/QUADRATIC_NUMPY.json"
