#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
tools=${KV260_HOST_TOOLS:-$HOME/.local/share/orb60/kv260-host}
test -x "$tools/gui/bin/python" || "$tools/reference/bin/python" -m venv "$tools/gui"
exec "$tools/gui/bin/pip" install -r "$root/orb60/kv260/requirements-gui.txt"
