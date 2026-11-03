#!/usr/bin/env bash
# Executed inside the pinned Vitis AI CPU image; does not touch RK environments.
set -euo pipefail
export MAX_JOBS=2 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
cd /workspace
set +u # Vendor Conda activation reads optional, unset MKL environment variables.
source /opt/vitis_ai/conda/etc/profile.d/conda.sh
conda activate vitis-ai-pytorch
set -u
python -m pip freeze > orb60/build/kv260/vitis-ai-environment.txt
python -m orb60.dense.kv260.toolchain_info --arch /opt/vitis_ai/compiler/arch/DPUCZDX8G/ZCU104/arch.json --output orb60/build/kv260/compiled
python -m orb60.dense.kv260.quantize --assets orb60/build/dense/assets --samples orb60/build/dense/samples-midas --reference orb60/build/dense/midas-small-fp16 --output orb60/build/kv260/quantized --mode calib
python -m orb60.dense.kv260.quantize --assets orb60/build/dense/assets --samples orb60/build/dense/samples-midas --reference orb60/build/dense/midas-small-fp16 --output orb60/build/kv260/quantized --mode test
model=$(find orb60/build/kv260/quantized -maxdepth 1 -name '*.xmodel' -print -quit)
test -n "$model"
python -m orb60.dense.kv260.compile_model --model "$model" --arch /opt/vitis_ai/compiler/arch/DPUCZDX8G/ZCU104/arch.json --quantization-report orb60/build/kv260/quantized/quantization_test.json --output orb60/build/kv260/compiled
