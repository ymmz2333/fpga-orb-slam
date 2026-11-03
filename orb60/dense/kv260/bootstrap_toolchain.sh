#!/usr/bin/env bash
# Private WSL binaries only; does not install/start a global Docker service.
set -euo pipefail
tools=${KV260_HOST_TOOLS:-$HOME/.local/share/orb60/kv260-host}
mkdir -p "$tools"
if [[ ! -f "$tools/docker.tgz" ]]; then
    curl -fL --retry 2 https://download.docker.com/linux/static/stable/x86_64/docker-27.5.1.tgz -o "$tools/docker.tgz.part"
    mv "$tools/docker.tgz.part" "$tools/docker.tgz"
fi
printf '%s  %s\n' 4f798b3ee1e0140eab5bf30b0edc4e84f4cdb53255a429dc3bbae9524845d640 "$tools/docker.tgz" | sha256sum --check
tar -xzf "$tools/docker.tgz" -C "$tools"
"$tools/docker/docker" --version
echo 'Start start_toolchain_service.sh in a separate foreground terminal, then pull_toolchain.sh.'
