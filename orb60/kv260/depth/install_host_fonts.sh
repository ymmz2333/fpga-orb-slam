#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get -y --no-install-recommends install fonts-noto-cjk
fc-cache -f
