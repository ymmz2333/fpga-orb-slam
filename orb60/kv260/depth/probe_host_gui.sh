#!/usr/bin/env bash
set -euo pipefail
tools=${KV260_HOST_TOOLS:-$HOME/.local/share/orb60/kv260-host}
"$tools/reference/bin/python" -c 'import sys,importlib.util; print(sys.version); print({n:bool(importlib.util.find_spec(n)) for n in ["PySide6","pyqtgraph","cv2","OpenGL"]})'
ls /tmp/.X11-unix /mnt/wslg/.X11-unix 2>/dev/null || true
