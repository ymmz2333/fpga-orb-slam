#!/usr/bin/env bash
# Optional isolated Ubuntu codec regression dependency, no packages installed system-wide.
set -euo pipefail
tools=${KV260_HOST_TOOLS:-$HOME/.local/share/orb60/kv260-host}
mkdir -p "$tools/codec/debs/partial" "$tools/codec/root"
apt-get --download-only --no-install-recommends --yes -o "Dir::Cache::archives=$tools/codec/debs" install ffmpeg > "$tools/codec/download.log" 2>&1
for package in "$tools"/codec/debs/*.deb; do dpkg-deb --extract "$package" "$tools/codec/root"; done
export PATH="$tools/codec/root/usr/bin:$PATH"
export LD_LIBRARY_PATH="$tools/codec/root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
root=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$root"
ffmpeg -version > orb60/build/kv260/codec-version.txt
"$tools/reference/bin/python" orb60/dense/tests/test_prepare_video.py --output orb60/build/kv260/video_regression
