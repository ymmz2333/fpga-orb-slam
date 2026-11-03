#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
exec apt-get -y --no-install-recommends install xvfb xauth libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libegl1 libgles2
