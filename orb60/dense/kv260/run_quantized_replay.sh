#!/usr/bin/env bash
# CPU INT8 reference diagnostics, including when numerical acceptance fails.
set -eo pipefail
export MAX_JOBS=2 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
cd /workspace
source /opt/vitis_ai/conda/etc/profile.d/conda.sh
conda activate vitis-ai-pytorch
python -m orb60.dense.kv260.worker orb60/build/kv260/quantized/quantized_reference.json orb60/build/kv260/replay_inputs/inputs orb60/build/kv260/replay_inputs/inputs/names.txt orb60/build/kv260/quantized_depth --backend quantized-reference
python -m orb60.dense.kv260.replay fuse --inputs orb60/build/kv260/replay_inputs --depths orb60/build/kv260/quantized_depth --output orb60/build/kv260/cloud_quantized
python -m orb60.dense.kv260.evaluate clouds --reference orb60/build/kv260/cloud_reference/map_0/dense.ply --candidate orb60/build/kv260/cloud_quantized/map_0/dense.ply --output orb60/build/kv260/quantized_cloud_comparison.json
