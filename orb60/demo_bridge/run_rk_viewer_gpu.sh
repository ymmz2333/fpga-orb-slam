#!/bin/sh
# Owned EGL FBOs on Mali; raster Qt presentation avoids broken native composition.
set -eu
test "$#" -ge 1 || { echo 'Usage: run_rk_viewer_gpu.sh DEPLOYMENT_ROOT [viewer options]'; exit 64; }
root=$(CDPATH= cd -- "$1" && pwd);shift
export DISPLAY=${DISPLAY:-:0}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export XAUTHORITY=${XAUTHORITY:-$XDG_RUNTIME_DIR/gdm/Xauthority}
export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}
export LD_LIBRARY_PATH="/usr/lib/aarch64-linux-gnu/mali:$root/gui_runtime/private_libs/usr/lib/aarch64-linux-gnu:${LD_LIBRARY_PATH:-}"
unset LIBGL_ALWAYS_SOFTWARE GALLIUM_DRIVER
export QT_XCB_GL_INTEGRATION=none PYOPENGL_PLATFORM=egl ORB60_VIEWER_RENDERER=egl-raster
export ORB60_VIEWER_POINT_BUDGET=40000 ORB60_POINT_PIXELS=1.5
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
exec "$root/gui_runtime/venv/bin/python" "$root/workspace/orb60/viewer/app.py" --demo-controller http://127.0.0.1:5610 --separate-maps "$@"
