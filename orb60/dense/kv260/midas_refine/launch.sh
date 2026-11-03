#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../../../.." && pwd)
tools=${KV260_HOST_TOOLS:-$HOME/.local/share/orb60/kv260-host}
out="$root/orb60/build/kv260/midas_refine"
mkdir -p "$out"
"$tools/docker/docker" --host "unix://$tools/docker.sock" run --rm --network none --cpus 2 --memory 4g \
 --mount "type=bind,src=$root,dst=/workspace,readonly" \
 --mount "type=bind,src=$out,dst=/workspace/orb60/build/kv260/midas_refine" \
 --workdir /workspace --entrypoint /bin/bash \
 xilinx/vitis-ai-cpu@sha256:eaa85efb06924995ebdb973546e7f69169b003b8cc525764bd9524ad554dddbe \
 -c 'exec bash -c "$(cat /workspace/orb60/dense/kv260/midas_refine/run.sh)" -- "$@"' -- "$@"
