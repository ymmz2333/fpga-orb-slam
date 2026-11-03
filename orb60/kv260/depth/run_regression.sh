#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
tools=${KV260_HOST_TOOLS:-$HOME/.local/share/orb60/kv260-host}
cd "$root"
exec "$tools/reference/bin/python" -m pytest -q orb60/dense/kv260/tests orb60/dense/tests/test_geometry.py orb60/dense/tests/test_video.py
