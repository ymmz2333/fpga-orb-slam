#!/usr/bin/env bash
set -euo pipefail
tools=${KV260_HOST_TOOLS:-$HOME/.local/share/orb60/kv260-host}
docker=${KV260_DOCKER:-$tools/docker/docker}
socket=${KV260_DOCKER_HOST:-unix://$tools/docker.sock}
image=xilinx/vitis-ai-cpu@sha256:eaa85efb06924995ebdb973546e7f69169b003b8cc525764bd9524ad554dddbe
"$docker" --host "$socket" pull "$image"
root=$(cd "$(dirname "$0")/../../.." && pwd)
mkdir -p "$root/orb60/build/kv260"
"$docker" --host "$socket" image inspect "$image" > "$root/orb60/build/kv260/container_image.json"
