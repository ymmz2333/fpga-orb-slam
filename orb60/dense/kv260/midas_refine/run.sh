#!/usr/bin/env bash
set -eo pipefail
export MAX_JOBS=2 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1
source /opt/vitis_ai/conda/etc/profile.d/conda.sh
conda activate vitis-ai-pytorch
cd /workspace
if [[ ${1:-} == video-test ]]; then
 shift
 python -m orb60.dense.kv260.midas_refine.video_test "$@"
elif [[ ${1:-} == qat-train ]]; then
 shift
 python -m orb60.dense.kv260.midas_refine.qat_train "$@"
elif [[ ${1:-} == qat-api ]]; then
 shift
 python -m orb60.dense.kv260.midas_refine.qat_api "$@"
elif [[ ${1:-} == qat-smoke ]]; then
 shift
 python -m orb60.dense.kv260.midas_refine.qat_smoke "$@"
elif [[ ${1:-} == finetune ]]; then
 shift
 python -m orb60.dense.kv260.midas_refine.finetune "$@"
elif [[ ${1:-} == calibrate ]]; then
 shift
 python -m orb60.dense.kv260.midas_refine.calibrate "$@"
else
 python -m orb60.dense.kv260.midas_refine.experiment "$@"
fi
