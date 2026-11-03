#!/usr/bin/env bash
# Run from the extracted handoff root. Firmware must already be installed by the operator.
set -euo pipefail
cd "$(dirname "$0")/../../.."
python3 -m orb60.dense.kv260.verify_package
test -f models/midas_kv260_b4096.xmodel || { echo 'No accepted target xmodel in this package'; exit 2; }
test -n "${KV260_EXPECTED_XRT_VERSION:-}" || { echo 'Set KV260_EXPECTED_XRT_VERSION from the matched board platform release first'; exit 2; }
python3 -m orb60.dense.kv260.preflight --arch models/arch.json --output board_output/preflight.json --expected-xrt-prefix "$KV260_EXPECTED_XRT_VERSION"
python3 -m orb60.dense.kv260.worker models/midas_kv260_b4096.xmodel acceptance/inputs acceptance/inputs/names.txt board_output/acceptance --backend dpu --preflight board_output/preflight.json --placement models/placement.json
python3 -m orb60.dense.kv260.evaluate numerical --samples acceptance/inputs --reference acceptance/reference --candidate board_output/acceptance --model models/midas_kv260_b4096.xmodel --backend dpu --output board_output/numerical_gate.json
python3 -m orb60.dense.kv260.worker models/midas_kv260_b4096.xmodel replay_inputs/inputs replay_inputs/inputs/names.txt board_output/depths --backend dpu --preflight board_output/preflight.json --placement models/placement.json
python3 -m orb60.dense.kv260.replay fuse --inputs replay_inputs --depths board_output/depths --output board_output/cloud
python3 -m orb60.dense.kv260.evaluate clouds --reference cloud_reference/map_0/dense.ply --candidate board_output/cloud/map_0/dense.ply --output board_output/cloud_comparison.json
