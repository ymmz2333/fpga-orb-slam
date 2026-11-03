#!/usr/bin/env bash
set -euo pipefail
root="$(cd "${1:?Usage: install_gui.sh DEPLOY_ROOT}" && pwd)"
python3 -m venv "$root/.venv_gui"
"$root/.venv_gui/bin/pip" install --no-index --find-links "$root/wheels" -r "$root/sources/orb60/kv260/requirements-gui.txt"
chmod +x "$root/sources/orb60/kv260/ps/start_gui.sh"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/orb-studio-kv260.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ORB Studio KV260
Comment=KV260 camera, ORB features, camera trajectory and map
Exec=$root/sources/orb60/kv260/ps/start_gui.sh $root
Terminal=false
Categories=Education;Science;
EOF
printf 'Installed local launcher: %s\n' "$HOME/.local/share/applications/orb-studio-kv260.desktop"
