#!/usr/bin/env bash
set -euo pipefail
project="$(cd -- "$(dirname -- "$0")/.." && pwd)"
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
export LD_LIBRARY_PATH="$project/install/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export OPENCV_CORE_PLUGIN_PATH="$project/install-demo/lib"
export OPENCV_UI_BACKEND=GTK3
test -f "$OPENCV_CORE_PLUGIN_PATH/libopencv_highgui_gtk3.so"
test -r "$XAUTHORITY"
xprop -root _NET_CURRENT_DESKTOP >/dev/null
output="$HOME/demo/$(date -u +%Y%m%dT%H%M%S)-viewer"
mkdir -p "$output"
printf '%s\n' "$output" > "$HOME/demo/latest_viewer.txt"
glxinfo -B > "$output/glxinfo.txt" 2>&1
python3 "$project/scripts/monitor_demo.py" --project "$project" --output "$output"
