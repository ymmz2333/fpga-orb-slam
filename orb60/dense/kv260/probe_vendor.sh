#!/usr/bin/env bash
set -eo pipefail
cd /workspace
source /opt/vitis_ai/conda/etc/profile.d/conda.sh
conda activate vitis-ai-pytorch
python -m orb60.dense.kv260.vendor_probe
