#!/usr/bin/env bash
# Requires a private running Docker endpoint, never starts/modifies system services.
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
tools=${KV260_HOST_TOOLS:-$HOME/.local/share/orb60/kv260-host}
docker=${KV260_DOCKER:-$tools/docker/docker}
socket=${KV260_DOCKER_HOST:-unix://$tools/docker.sock}
image=xilinx/vitis-ai-cpu@sha256:eaa85efb06924995ebdb973546e7f69169b003b8cc525764bd9524ad554dddbe
script=${1:-toolchain.sh}
"$docker" --host "$socket" run --rm --network none --mount "type=bind,src=$root,dst=/workspace" --workdir /workspace --entrypoint /bin/bash "$image" "/workspace/orb60/dense/kv260/$script"
