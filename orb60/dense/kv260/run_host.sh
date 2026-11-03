#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$root"
py=${KV260_REFERENCE_PYTHON:-${KV260_HOST_TOOLS:-$HOME/.local/share/orb60/kv260-host}/reference/bin/python}
out=orb60/build/kv260
mkdir -p "$out"
"$py" -m orb60.dense.kv260.inspect_model --model orb60/build/dense/midas-small-fp16/midas_small_256.onnx --output "$out/model"
"$py" -m orb60.dense.kv260.verify_float --assets orb60/build/dense/assets --samples orb60/build/dense/samples-midas --reference orb60/build/dense/midas-small-fp16 --model "$out/model/midas_static.onnx" --output "$out/float"
"$py" -m orb60.dense.kv260.prepare_replay --saved orb60/build/dense/room_full --video recordings/tt/flight_20261004T184929_998838_6bb93c56/video.mp4 --rgb-cache orb60/build/dense/room_full_detail --regenerate-inputs --output "$out/replay_inputs"
"$py" -m orb60.dense.kv260.worker "$out/model/midas_static.onnx" "$out/replay_inputs/inputs" "$out/replay_inputs/inputs/names.txt" "$out/reference_depth" --backend reference
"$py" -m orb60.dense.kv260.replay fuse --inputs "$out/replay_inputs" --depths "$out/reference_depth" --output "$out/cloud_reference"
"$py" -m orb60.dense.kv260.preview --cloud "$out/cloud_reference/map_0/dense.ply" --output "$out/pointcloud_preview.png"
"$py" -m pytest orb60/dense/kv260/tests orb60/dense/tests/test_geometry.py orb60/dense/tests/test_video.py orb60/dense/tests/test_npu_gate.py -q --junitxml="$out/tests.xml"
