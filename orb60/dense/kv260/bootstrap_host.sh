#!/usr/bin/env bash
# Private host tools only. Run in WSL; does not change the retained RK environment.
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
toolroot=${KV260_HOST_TOOLS:-$HOME/.local/share/orb60/kv260-host}
mkdir -p "$toolroot"
uv="$root/orb60/build/dense/assets/uv-x86_64-unknown-linux-gnu/uv"
if [[ ! -x "$toolroot/reference/bin/python" ]]; then
    "$uv" venv --seed --python 3.10.19 "$toolroot/reference"
fi
"$uv" pip install --python "$toolroot/reference/bin/python" 'torch==2.4.0+cpu' 'torchvision==0.19.0+cpu' --index-url https://download.pytorch.org/whl/cpu
"$uv" pip install --python "$toolroot/reference/bin/python" 'numpy==1.26.4' 'onnx==1.16.1' 'onnxruntime==1.18.1' 'opencv-python-headless==4.10.0.84' 'scipy==1.14.1' 'onnxsim==0.4.36' 'pytest==8.3.5' 'matplotlib==3.9.4'
"$toolroot/reference/bin/python" -m pip freeze > "$toolroot/reference-requirements.txt"
echo "KV260_REFERENCE_PYTHON=$toolroot/reference/bin/python"
