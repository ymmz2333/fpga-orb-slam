#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
task_cross_root=${KV260_CROSS_ROOT:-$HOME/.local/share/orb60/kv260-host/cross_arm11_20261103_a}
cd "$project_root"
exec python3 -m orb60.kv260.ps.compile_keyframe_cadence \
  --compiler-manifest "$task_cross_root/pose_neon_a/CROSS_COMPILE.json" \
  --source "$project_root/orb60/build/kv260_system/private_arm_cross_20261103_a/Tracking_retained.cc" \
  --output "$task_cross_root/keyframe_10_a" --interval 10
