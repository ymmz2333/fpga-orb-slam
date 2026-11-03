#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
tools=${KV260_HOST_TOOLS:-$HOME/.local/share/orb60/kv260-host}
cd "$root"
export QT_QPA_PLATFORM=xcb QT_XCB_GL_INTEGRATION=xcb_glx LIBGL_ALWAYS_SOFTWARE=1
exec xvfb-run -a -s '-screen 0 1920x1080x24' "$tools/gui/bin/python" -m orb60.kv260.gui \
 --dense orb60/build/kv260_system/selected_qat_viewer \
 --allow-software-renderer-for-test \
 --screenshot orb60/build/kv260_system/qa_separate_dense \
 --metrics orb60/build/kv260_system/qa_separate_dense/display_metrics.json --exit-after 12
