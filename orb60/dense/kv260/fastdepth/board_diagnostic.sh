#!/usr/bin/env bash
# Explicit diagnostic entry: checksums -> read-only profile -> real 20-frame inference -> numerical gate.
# No firmware/boot changes, and no continuation past a failed numerical gate.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
python3 -m orb60.dense.kv260.verify_package
test -n "${KV260_EXPECTED_XRT_VERSION:-}" || { echo 'Set KV260_EXPECTED_XRT_VERSION from the matched platform release'; exit 2; }
python3 -m orb60.dense.kv260.preflight --arch diagnostic_models/fastdepth/arch.json --output board_output/fastdepth/preflight.json --expected-xrt-prefix "$KV260_EXPECTED_XRT_VERSION"
python3 -m orb60.dense.kv260.worker diagnostic_models/fastdepth/fastdepth_kv260_b4096.xmodel acceptance_fastdepth/inputs acceptance_fastdepth/inputs/names.txt board_output/fastdepth/acceptance --backend dpu --family fastdepth --preflight board_output/fastdepth/preflight.json --placement diagnostic_models/fastdepth/placement.json
python3 -m orb60.dense.kv260.evaluate numerical --samples acceptance_fastdepth/inputs --reference acceptance_fastdepth/reference --candidate board_output/fastdepth/acceptance --model diagnostic_models/fastdepth/fastdepth_kv260_b4096.xmodel --backend dpu --output board_output/fastdepth/numerical_gate.json
python3 -m orb60.dense.kv260.worker diagnostic_models/fastdepth/fastdepth_kv260_b4096.xmodel replay_inputs/inputs replay_inputs/inputs/names.txt board_output/fastdepth/depths --backend dpu --family fastdepth --preflight board_output/fastdepth/preflight.json --placement diagnostic_models/fastdepth/placement.json
python3 -m orb60.dense.kv260.replay fuse --inputs replay_inputs --depths board_output/fastdepth/depths --output board_output/fastdepth/cloud
python3 -m orb60.dense.kv260.evaluate clouds --reference candidate_fastdepth/cloud_reference/map_0/dense.ply --candidate board_output/fastdepth/cloud/map_0/dense.ply --output board_output/fastdepth/cloud_comparison.json
