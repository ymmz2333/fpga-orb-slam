#!/bin/sh
# Mali EGL rendering by default; explicit diagnostic software mode remains available.
set -eu
test "$#" -ge 1 || { echo 'Usage: run_rk_viewer.sh DEPLOYMENT_ROOT [viewer options]'; exit 64; }
root=$(CDPATH= cd -- "$1" && pwd);shift
if test "${ORB60_GUI_BACKEND:-gpu}" = gpu; then
 exec sh "$root/run_rk_viewer_gpu.sh" "$root" "$@"
fi
export DISPLAY=${DISPLAY:-:0}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export XAUTHORITY=${XAUTHORITY:-$XDG_RUNTIME_DIR/gdm/Xauthority}
export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}
export LD_LIBRARY_PATH="$root/gui_runtime/private_libs/usr/lib/aarch64-linux-gnu:${LD_LIBRARY_PATH:-}"
export QT_XCB_GL_INTEGRATION=xcb_glx PYOPENGL_PLATFORM=glx ORB60_VIEWER_RENDERER=desktop
export LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe
export vblank_mode=0 LP_NUM_THREADS=2
export ORB60_VIEWER_POINT_BUDGET=40000 ORB60_POINT_PIXELS=1.5
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
exec "$root/gui_runtime/venv/bin/python" "$root/workspace/orb60/viewer/app.py" --demo-controller http://127.0.0.1:5610 --separate-maps "$@"
