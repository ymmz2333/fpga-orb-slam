#!/usr/bin/env bash
set -eo pipefail
export MAX_JOBS=2 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
cd /workspace
source /opt/vitis_ai/conda/etc/profile.d/conda.sh
conda activate vitis-ai-pytorch
python -m orb60.dense.kv260.quantize --assets orb60/build/dense/assets --samples orb60/build/dense/samples-midas --reference orb60/build/dense/midas-small-fp16 --output orb60/build/kv260/quantized_reluk --mode calib --recipe reluk-cle
python -m orb60.dense.kv260.quantize --assets orb60/build/dense/assets --samples orb60/build/dense/samples-midas --reference orb60/build/dense/midas-small-fp16 --output orb60/build/kv260/quantized_reluk --mode test --recipe reluk-cle
