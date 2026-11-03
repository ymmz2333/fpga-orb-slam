#!/usr/bin/env bash
set -euo pipefail
tools=${KV260_HOST_TOOLS:-$HOME/.local/share/orb60/kv260-host}
export PATH="$tools/docker:$PATH"
exec dockerd --data-root "$tools/docker-data" --exec-root "$tools/docker-exec" --pidfile "$tools/docker.pid" \
    --host "unix://$tools/docker.sock" --bridge none --iptables=false --ip-forward=false --ip-masq=false
