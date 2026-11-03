#!/usr/bin/env bash
set -euo pipefail
tools=${KV260_HOST_TOOLS:-$HOME/.local/share/orb60/kv260-host}
exec "$tools/docker/docker" --host "unix://$tools/docker.sock" "$@"
