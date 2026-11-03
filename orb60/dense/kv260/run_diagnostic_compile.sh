#!/usr/bin/env bash
set -eo pipefail
cd /workspace
source /opt/vitis_ai/conda/etc/profile.d/conda.sh
conda activate vitis-ai-pytorch
python -m orb60.dense.kv260.compile_model --model orb60/build/kv260/quantized/MidasNet_small_int.xmodel --arch /opt/vitis_ai/compiler/arch/DPUCZDX8G/ZCU104/arch.json --quantization-report orb60/build/kv260/quantized/quantization_test.json --output orb60/build/kv260/compiled_diagnostic --diagnostic-only "$@"
