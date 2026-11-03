#!/usr/bin/env bash
set -eo pipefail
cd /workspace
source /opt/vitis_ai/conda/etc/profile.d/conda.sh
conda activate vitis-ai-pytorch
python -m orb60.dense.kv260.inspect_compiled --model orb60/build/kv260/compiled_diagnostic/midas_kv260_b4096.xmodel --source orb60/build/kv260/quantized/MidasNet_small_int.xmodel --output orb60/build/kv260/compiled_diagnostic/placement.json
