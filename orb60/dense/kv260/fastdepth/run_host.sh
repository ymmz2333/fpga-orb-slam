#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../../../.." && pwd)
cd "$root"
py=${KV260_REFERENCE_PYTHON:-${KV260_HOST_TOOLS:-$HOME/.local/share/orb60/kv260-host}/reference/bin/python}
if [[ ! -f orb60/build/kv260/replay_inputs/keyframes.json ]]; then
    "$py" -m orb60.dense.kv260.prepare_replay --saved orb60/build/dense/room_full --video recordings/tt/flight_20261004T184929_998838_6bb93c56/video.mp4 --rgb-cache orb60/build/dense/room_full_detail --regenerate-inputs --output orb60/build/kv260/replay_inputs
fi
"$py" -m orb60.dense.kv260.fastdepth.fetch
"$py" -m orb60.dense.kv260.fastdepth.pipeline --stage float
"$py" -m orb60.dense.kv260.worker orb60/build/kv260/fastdepth/assets/fast_depth_224x224.onnx orb60/build/kv260/replay_inputs/inputs orb60/build/kv260/replay_inputs/inputs/names.txt orb60/build/kv260/fastdepth/reference_depth --backend reference --family fastdepth
"$py" -m orb60.dense.kv260.replay fuse --inputs orb60/build/kv260/replay_inputs --depths orb60/build/kv260/fastdepth/reference_depth --output orb60/build/kv260/fastdepth/cloud_reference
"$py" -m orb60.dense.kv260.preview --cloud orb60/build/kv260/fastdepth/cloud_reference/map_0/dense.ply --output orb60/build/kv260/fastdepth/pointcloud_preview.png --family FastDepth
