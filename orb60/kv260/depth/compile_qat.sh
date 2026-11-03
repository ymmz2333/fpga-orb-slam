#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
tools=${KV260_HOST_TOOLS:-$HOME/.local/share/orb60/kv260-host}
out="$root/orb60/build/kv260_system/depth_midas_qat"
"$tools/docker/docker" --host "unix://$tools/docker.sock" run --rm --network none --cpus 2 --memory 4g \
 --mount "type=bind,src=$root,dst=/workspace,readonly" \
 --mount "type=bind,src=$out,dst=/workspace/orb60/build/kv260_system/depth_midas_qat" \
 --workdir /workspace --entrypoint /bin/bash \
 xilinx/vitis-ai-cpu@sha256:eaa85efb06924995ebdb973546e7f69169b003b8cc525764bd9524ad554dddbe \
 -c 'set -eo pipefail; source /opt/vitis_ai/conda/etc/profile.d/conda.sh; conda activate vitis-ai-pytorch;
 python -m orb60.kv260.depth.review_ps_ops
 exec python -m orb60.dense.kv260.compile_model --family midas \
 --model orb60/build/kv260_system/depth_midas_qat/export/runtime/Scoped_0_int.xmodel \
 --arch /opt/vitis_ai/compiler/arch/DPUCZDX8G/ZCU104/arch.json \
 --quantization-report orb60/build/kv260_system/depth_midas_qat/export/compile_gate.json \
 --application-acceptance orb60/kv260/config/depth_model_selection.json \
 --inspect-existing --ps-operator-policy orb60/build/kv260_system/depth_midas_qat/ps_operator_policy.json \
 --output orb60/build/kv260_system/depth_midas_qat/compiled'
