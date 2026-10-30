#!/usr/bin/env bash
set -euo pipefail
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
directory="${1:-$HOME/demo/figures}"
files=("$directory/01_trajectory_xy.png" "$directory/02_frame_timing.png" "$directory/03_orb_share.png" "$directory/04_ate_runs.png")
for path in "${files[@]}"; do test -f "$path"; done
echo 'DISPLAYING_FIGURES: use Right/Left arrows to move through the four PNGs; Esc exits fullscreen'
# Eye of GNOME loads the ordered list; the user advances at their own pace.
exec eog --fullscreen "${files[@]}"
