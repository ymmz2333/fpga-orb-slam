#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$1" && pwd)
project=$(CDPATH= cd -- "$root/../.." && pwd)
cd "$project"
unset ORB60_VALID_MASK ORB60_DENSE_EXPORT ORB60_DENSE_LIVE_DIR
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 ORB60_VIEWER_FPS=30
export PYTHONPATH="$root/workspace"
export LD_LIBRARY_PATH="$root/rk_source/lib:$project/install/lib:${LD_LIBRARY_PATH:-}"
exec /usr/bin/python3 -u -m orb60.demo_bridge.controller --config "$root/rk.local.json" --port 5610
