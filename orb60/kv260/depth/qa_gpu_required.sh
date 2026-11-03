#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
tools=${KV260_HOST_TOOLS:-$HOME/.local/share/orb60/kv260-host}
cd "$root"
set +e
QT_QPA_PLATFORM=xcb QT_XCB_GL_INTEGRATION=xcb_glx LIBGL_ALWAYS_SOFTWARE=1 \
 xvfb-run -a -s '-screen 0 1920x1080x24' "$tools/gui/bin/python" -m orb60.kv260.gui \
 --dense orb60/build/kv260_system/selected_qat_viewer --exit-after 5 \
 > orb60/build/kv260_system/gpu_required_rejection.log 2>&1
code=$?
set -e
test "$code" = 2
grep -q 'Hardware GPU rendering required' orb60/build/kv260_system/gpu_required_rejection.log
echo GPU_REQUIRED_REJECTION_PASS
