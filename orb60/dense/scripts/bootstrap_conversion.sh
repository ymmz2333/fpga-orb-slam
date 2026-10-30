#!/usr/bin/env bash
# Run through prepare_npu_gate.ps1, with resolved Linux asset and venv paths.
set -euo pipefail
assets=$1
conversion_env=$2
tar -xf "$assets/uv-linux.tar.gz" -C "$assets"
uv_binary="$assets/uv-x86_64-unknown-linux-gnu/uv"
if [ ! -x "$conversion_env/bin/python" ]; then
    "$uv_binary" venv --seed --python 3.10.19 "$conversion_env"
fi
"$conversion_env/bin/python" -m pip install --disable-pip-version-check \
    'torch==2.4.0+cpu' 'torchvision==0.19.0+cpu' \
    --index-url https://download.pytorch.org/whl/cpu
"$conversion_env/bin/python" -m pip install --disable-pip-version-check \
    'setuptools==75.8.2' 'numpy==1.26.4' 'opencv-python==4.10.0.84' 'onnx==1.16.1' 'onnxruntime==1.18.1' \
    "$assets/rknn_toolkit2-2.5.0-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
"$conversion_env/bin/python" -m pip freeze > "$assets/conversion-environment.txt"
"$conversion_env/bin/python" -c 'import torch,onnx,onnxruntime; from rknn.api import RKNN; print("CONVERSION_ENV_OK", torch.__version__,onnx.__version__,onnxruntime.__version__)'
