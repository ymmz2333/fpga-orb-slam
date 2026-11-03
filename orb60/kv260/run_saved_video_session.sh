#!/bin/bash
# Run from the KV260 desktop terminal; all computation stays on the two boards.
set -euo pipefail
root=$(cd -- "${1:?Supply the KV260 project root}" && pwd)
config=${2:?Supply the mapping configuration}
connection=${3:?Supply the board connection configuration}
label=${4:-session-$(date +%Y%m%d-%H%M%S)-$$}
case "$config" in /*) ;; *) config="$root/$config";; esac
case "$connection" in /*) ;; *) connection="$root/$connection";; esac
cd "$root/sources"
exec bash orb60/kv260/depth/runtime_exec.sh "$root" python -m orb60.kv260.two_board_session \
    --config "$config" --connection "$connection" --output "$root/two_board_sessions/$label"
