#!/bin/sh
set -eu
test "$#" -ge 1 || { echo 'Usage: build_color_rk.sh ISOLATED_DEPLOYMENT_ROOT [TARGET]'; exit 64; }
root=$(CDPATH= cd -- "$1" && pwd)
target=${2:-mono_bridge_color}
case "$target" in mono_bridge_color|mono_bridge_fastview|mono_bridge_fastview2) ;; *) echo 'Unknown target'; exit 64;; esac
test -f "$root/rk_source/DEMO_BRIDGE_SOURCE.json"
cp "$root/workspace/orb60/demo_bridge/rk/mono_bridge.cc" "$root/rk_source/Examples/Monocular/mono_bridge.cc"
cp "$root/workspace/orb60/demo_bridge/rk/BridgeFrame.h" "$root/rk_source/include/BridgeFrame.h"
cp "$root/workspace/orb60/demo_bridge/rk/BridgeDisplay.h" "$root/rk_source/include/BridgeDisplay.h"
cp "$root/workspace/orb60/dense/slam/DenseFrameTelemetry.h" "$root/rk_source/include/DenseFrameTelemetry.h"
cp "$root/workspace/zynq7015_demo/include/zslam/bridge_wire.hpp" "$root/rk_source/include/bridge_wire.hpp"
python3 - "$root" "$target" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])/'rk_source/CMakeLists.txt'
text=p.read_text()
target=sys.argv[2]
if 'add_executable('+target+' ' not in text:
    p.write_text(text+'\nadd_executable('+target+' Examples/Monocular/mono_bridge.cc)\n'
                 'target_link_libraries('+target+' ${PROJECT_NAME})\n'
                 'set_target_properties('+target+' PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/demo_bin")\n')
PY
available=$(awk '/MemAvailable:/{print int($2/1024)}' /proc/meminfo)
test "$available" -ge 1536
cmake -S "$root/rk_source" -B "$root/rk_build"
cmake --build "$root/rk_build" --target "$target" --parallel 1
sha256sum "$root/rk_build/demo_bin/$target"
