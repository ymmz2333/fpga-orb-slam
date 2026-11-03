#!/usr/bin/env bash
set -eo pipefail
export MAX_JOBS=2 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
cd /workspace
source /opt/vitis_ai/conda/etc/profile.d/conda.sh
conda activate vitis-ai-pytorch
python -m orb60.dense.kv260.fastdepth.pipeline --stage calib --equalization
python -m orb60.dense.kv260.fastdepth.pipeline --stage test --equalization
